"""Minimal input guardrails for prompt-injection and data-exfiltration attempts."""

from __future__ import annotations

import re


_BLOCK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "instruction_override",
        re.compile(
            r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|prompts)|"
            r"disregard\s+(system|developer)\s+prompt|"
            r"you\s+are\s+now\s+(developer|system|admin)",
            re.IGNORECASE,
        ),
    ),
    (
        "prompt_exfiltration",
        re.compile(
            r"reveal|show|print|dump|leak", re.IGNORECASE
        ),
    ),
    (
        "sensitive_internal_request",
        re.compile(
            r"system\s+prompt|developer\s+prompt|hidden\s+prompt|"
            r"env(ironment)?\s+variables?|api\s*key|secret|token|password|"
            r"raw\s+sql|json\s+query|database\s+query|internal\s+schema|"
            r"tool\s+request|tool\s+response|request\s+body|response\s+body|"
            r"exact\s+(json|request|response)|raw\s+tool\s+output|"
            r"request\s+payload|response\s+payload",
            re.IGNORECASE,
        ),
    ),
]


def evaluate_user_prompt(message: str) -> tuple[bool, str | None]:
    """Return whether a message should be blocked by minimal guardrails."""
    text = (message or "").strip()
    if not text:
        return False, None

    lowered = text.lower()
    for reason, pattern in _BLOCK_PATTERNS:
        if pattern.search(lowered):
            # For prompt_exfiltration, only block when paired with internal target terms.
            if reason == "prompt_exfiltration":
                if re.search(
                    r"system\s+prompt|developer\s+prompt|hidden\s+prompt|"
                    r"api\s*key|secret|token|password|sql|database|internal|"
                    r"tool\s+request|tool\s+response|request\s+body|response\s+body|"
                    r"payload|raw\s+json|exact\s+json",
                    lowered,
                    re.IGNORECASE,
                ):
                    return True, reason
                continue
            return True, reason

    return False, None
