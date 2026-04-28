import uuid
from sqlalchemy import select

from app.core.logging import get_logger
from app.models.chat_message import ChatMessage, MessageSenderRole
from app.models.chat_room import ChatRoom
from app.models.user import User
from app.core.config import settings
from app.agents.langchain_agent import calculate_minimax_cost

logger = get_logger(__name__)


async def _summarize_with_minimax(
    old_summary: str | None, new_messages: list[ChatMessage]
) -> tuple[str | None, int, int]:
    import re
    from openai import AsyncOpenAI

    if not settings.LLM_API_KEY or settings.LLM_API_KEY == "changeme":
        logger.warning("No LLM API key configured. Skipping summarize.")
        return None, 0, 0

    client = AsyncOpenAI(
        api_key=settings.LLM_API_KEY,
        base_url=settings.LLM_BASE_URL,
    )

    prompt = (
        "Summarize the following new chat messages and incorporate them into the provided "
        "existing summary. Output ONLY the new updated summary. Be concise but do not lose "
        "important constraints or preferences mentioned by the user."
    )
    if old_summary:
        prompt += f"\n\nEXISTING SUMMARY:\n{old_summary}"

    prompt += "\n\nNEW MESSAGES:\n"
    for msg in new_messages:
        prompt += f"[{msg.sender_role.value}]: {msg.content}\n"

    try:
        response = await client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Please generate the new summary."},
            ],
            max_tokens=512,
            temperature=0.3,
        )
        raw = response.choices[0].message.content or ""
        # Strip <think>...</think> reasoning blocks that minimax-m2.7 emits
        raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL)

        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0

        return raw.strip() or None, prompt_tokens, completion_tokens
    except Exception as e:
        logger.error("Failed to generate summary with Minimax", error=str(e))
        return None, 0, 0


async def check_and_summarize(chat_id: uuid.UUID):
    """
    Background worker that checks if the chat has > 10 unsummarized messages.
    If so, it generates a new summary and updates the ChatRoom.
    """
    try:
        logger.info("Summarizer check started", chat_id=str(chat_id))
        # We need a new isolated session to commit bg tasks safely without interfering with the ongoing request.
        from app.db.session import async_session_maker

        async with async_session_maker() as bg_db:
            # Lock or just fetch recent unsummarized messages
            result = await bg_db.execute(
                select(ChatMessage)
                .where(
                    ChatMessage.chat_room_id == chat_id,
                    ChatMessage.is_summarized.is_(False),
                    ChatMessage.sender_role.in_(
                        [MessageSenderRole.user, MessageSenderRole.assistant]
                    ),
                )
                .order_by(ChatMessage.created_at.asc())
            )
            unsummarized_msgs = list(result.scalars().all())

            # We skip the absolute latest message to leave it unsummarized and fresh in the immediate context buffer
            if len(unsummarized_msgs) > 10:
                target_msgs = unsummarized_msgs[
                    :-1
                ]  # take all except the very last one

                room_res = await bg_db.execute(
                    select(ChatRoom).where(ChatRoom.id == chat_id)
                )
                room = room_res.scalars().first()
                if not room:
                    return

                (
                    new_summary,
                    s_prompt_tokens,
                    s_completion_tokens,
                ) = await _summarize_with_minimax(room.context_summary, target_msgs)

                if new_summary:
                    room.context_summary = new_summary
                    for msg in target_msgs:
                        msg.is_summarized = True

                    # Update user aggregate usage for summarization cost
                    if room.user_id:
                        user_res = await bg_db.execute(
                            select(User).where(User.id == room.user_id)
                        )
                        user = user_res.scalars().first()
                        if user:
                            msg_cost = calculate_minimax_cost(
                                s_prompt_tokens, s_completion_tokens
                            )
                            user.total_tokens += s_prompt_tokens + s_completion_tokens
                            user.total_cost += msg_cost
                            user.token_usage_millions = (
                                float(user.total_tokens) / 1_000_000.0
                            )

                    await bg_db.commit()
                    logger.info(
                        "Chat context summarized and usage updated",
                        chat_id=str(chat_id),
                        msg_count=len(target_msgs),
                        tokens=s_prompt_tokens + s_completion_tokens,
                    )
            else:
                logger.info(
                    "Summarizer skipped",
                    chat_id=str(chat_id),
                    unsummarized_count=len(unsummarized_msgs),
                )

    except Exception as e:
        logger.warning(f"Error in background summarizer: {str(e)}")
