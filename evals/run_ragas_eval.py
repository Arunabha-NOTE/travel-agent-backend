"""
RAGAS Evaluation — KB-Driven Test Generation  (RAGAS 0.4.3)
============================================================
Strategy:
  1. Sample real chunks from the pgvector knowledge base
  2. LLM generates a factual question FROM each chunk
  3. Re-query pgvector with that question (real retrieval path)
  4. LLM answers using retrieved contexts
  5. LLM generates ground truth from the source chunk
  6. Score each sample with 4 RAGAS metrics directly via .ascore()

Because every question originates from KB content, all four metrics
produce meaningful, non-trivial scores.

Usage (from chatbot-backend root):
    python evals/run_ragas_eval.py
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import warnings
from pathlib import Path

from dotenv import load_dotenv
import openai
from langchain_openai import ChatOpenAI
from sentence_transformers import SentenceTransformer

from ragas.llms.base import llm_factory
from ragas.metrics.collections import (
    ContextPrecisionWithoutReference,
    ContextRecall,
    Faithfulness,
    AnswerRelevancy,
)
from ragas.embeddings.base import BaseRagasEmbedding

warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=UserWarning)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")

# ── Config ────────────────────────────────────────────────────────────────────
LLM_API_KEY = os.environ["LLM_API_KEY"]
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.minimax.io/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "minimax-m2.7")

OUTPUT_DIR = Path(__file__).parent
DATASET_FILE = OUTPUT_DIR / "ragas_dataset.json"
RESULTS_CSV = OUTPUT_DIR / "ragas_detailed_results.csv"

SEED_QUERIES = [
    "flight booking airline schedule departure arrival",
    "hotel accommodation check-in amenities",
    "museum attraction opening hours admission tickets",
    "transportation airport taxi train bus route",
    "travel itinerary planning day tour sightseeing",
    "weather forecast travel packing tips",
    "city guide restaurants dining nightlife",
    "Delhi Goa Pune Mumbai travel guide",
]
NUM_TEST_CASES = 5


# ── Shared LLM helpers ────────────────────────────────────────────────────────
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_think(text: str) -> str:
    """Remove MiniMax chain-of-thought <think>…</think> blocks from output."""
    return _THINK_RE.sub("", text).strip().strip('"').strip()


def _langchain_llm(temperature: float = 0) -> ChatOpenAI:
    return ChatOpenAI(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        model=LLM_MODEL,
        temperature=temperature,
        n=1,
    )


def _ragas_llm():
    """RAGAS 0.4.3 instructor-based LLM wrapper for metric scoring."""
    client = openai.AsyncOpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    return llm_factory(
        model=LLM_MODEL,
        provider="openai",
        client=client,
        temperature=0,
    )


class LocalSTEmbedding(BaseRagasEmbedding):
    """Wrap the local all-MiniLM-L6-v2 model as a RAGAS embedding."""

    def __init__(self):
        self._model = SentenceTransformer("all-MiniLM-L6-v2")

    def embed_text(self, text: str) -> list[float]:
        return self._model.encode([text], convert_to_numpy=True)[0].tolist()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts, convert_to_numpy=True).tolist()

    async def aembed_text(self, text: str) -> list[float]:
        return self.embed_text(text)

    async def aembed_texts(self, texts: list[str]) -> list[list[float]]:
        return self.embed_texts(texts)


# ── Step 1: Sample diverse, content-rich chunks ───────────────────────────────
def sample_kb_chunks(n: int = NUM_TEST_CASES) -> list[str]:
    from app.agents.rag.vector_store import get_vector_store

    store = get_vector_store()
    seen: dict[str, str] = {}

    for q in SEED_QUERIES:
        if len(seen) >= n * 5:
            break
        for doc in store.similarity_search(q, k=6):
            key = doc.page_content[:80]
            content = doc.page_content.strip()
            if (
                key not in seen
                and len(content) > 300
                and not content.startswith("{")
                and "URL:" not in content[:80]
                and content.count(" ") > 40
            ):
                seen[key] = content

    chunks = list(seen.values())
    step = max(1, len(chunks) // n)
    sel = [chunks[i] for i in range(0, len(chunks), step)][:n]
    print(f"  → {len(seen)} candidate chunks, selected {len(sel)}")
    return sel


# ── Step 2-5: Generate Q / GT / contexts / answer ────────────────────────────
Q_PROMPT = """\
You are a travel trivia creator. Given the travel-related text below, write
ONE specific factual question answerable directly from the text.
Rules: avoid yes/no; use what/how/when/where/which; max 25 words; output ONLY the question.

TEXT:
{chunk}

QUESTION:"""

GT_PROMPT = """\
You are a travel fact-checker. Using ONLY the text below, write a concise
1-3 sentence answer. No outside knowledge.

TEXT:
{chunk}

QUESTION:
{question}

ANSWER:"""

ANS_PROMPT = """\
You are a helpful travel assistant. Answer using ONLY the context below.
If context is insufficient, say so.

CONTEXT:
{ctx}

QUESTION:
{q}

ANSWER:"""


def make_question(chunk: str, llm: ChatOpenAI) -> str:
    raw = llm.invoke(Q_PROMPT.format(chunk=chunk[:1800])).content
    return _strip_think(raw)


def make_ground_truth(chunk: str, q: str, llm: ChatOpenAI) -> str:
    raw = llm.invoke(GT_PROMPT.format(chunk=chunk[:1800], question=q)).content
    return _strip_think(raw)


def retrieve_contexts(q: str, k: int = 4) -> list[str]:
    from app.agents.rag.vector_store import get_retriever

    docs = get_retriever(k=k).invoke(q)
    return [d.page_content for d in docs] if docs else ["<no context retrieved>"]


def make_answer(q: str, contexts: list[str], llm: ChatOpenAI) -> str:
    ctx = "\n\n---\n\n".join(contexts)
    raw = llm.invoke(ANS_PROMPT.format(ctx=ctx[:3000], q=q)).content
    return _strip_think(raw)


def build_dataset() -> list[dict]:
    llm = _langchain_llm()
    chunks = sample_kb_chunks()
    records = []
    for i, chunk in enumerate(chunks, 1):
        print(
            f"\n  [{i}/{len(chunks)}] Chunk ({len(chunk)} chars): {chunk[:80].strip()}..."
        )
        q = make_question(chunk, llm)
        gt = make_ground_truth(chunk, q, llm)
        cx = retrieve_contexts(q)
        a = make_answer(q, cx, llm)
        print(f"    Q : {q}")
        print(f"    GT: {gt[:90]}...")
        print(f"    Cx: {len(cx)} chunks  |  A: {a[:90]}...")
        records.append(
            {
                "user_input": q,
                "retrieved_contexts": cx,
                "response": a,
                "reference": gt,
                # human-readable extras saved to JSON
                "question": q,
                "contexts": cx,
                "answer": a,
                "ground_truth": gt,
            }
        )
    return records


# ── Step 6: Score with RAGAS metrics directly ─────────────────────────────────
async def _score_all(records: list[dict]) -> dict[str, list[float]]:
    """Score every sample with each metric using RAGAS 0.4.3 keyword-arg API."""
    ragas_llm = _ragas_llm()
    ragas_embs = LocalSTEmbedding()

    cp_metric = ContextPrecisionWithoutReference(llm=ragas_llm)
    cr_metric = ContextRecall(llm=ragas_llm)
    ff_metric = Faithfulness(llm=ragas_llm)
    ar_metric = AnswerRelevancy(llm=ragas_llm, embeddings=ragas_embs, strictness=1)

    metric_names = [
        "context_precision",
        "context_recall",
        "faithfulness",
        "answer_relevancy",
    ]
    all_scores: dict[str, list[float]] = {n: [] for n in metric_names}

    for i, r in enumerate(records, 1):
        ui = r["user_input"]
        ctx = r["retrieved_contexts"]
        res = r["response"]
        ref = r["reference"]

        print(f"  Scoring sample {i}/{len(records)} …", end=" ", flush=True)

        # ContextPrecisionWithoutReference(user_input, response, retrieved_contexts)
        try:
            result = await cp_metric.ascore(
                user_input=ui, response=res, retrieved_contexts=ctx
            )
            all_scores["context_precision"].append(
                result.value if hasattr(result, "value") else float(result)
            )
        except Exception as e:
            print(f"\n    [context_precision] error: {e}")
            all_scores["context_precision"].append(float("nan"))

        # ContextRecall(user_input, retrieved_contexts, reference)
        try:
            result = await cr_metric.ascore(
                user_input=ui, retrieved_contexts=ctx, reference=ref
            )
            all_scores["context_recall"].append(
                result.value if hasattr(result, "value") else float(result)
            )
        except Exception as e:
            print(f"\n    [context_recall] error: {e}")
            all_scores["context_recall"].append(float("nan"))

        # Faithfulness(user_input, response, retrieved_contexts)
        try:
            result = await ff_metric.ascore(
                user_input=ui, response=res, retrieved_contexts=ctx
            )
            all_scores["faithfulness"].append(
                result.value if hasattr(result, "value") else float(result)
            )
        except Exception as e:
            print(f"\n    [faithfulness] error: {e}")
            all_scores["faithfulness"].append(float("nan"))

        # AnswerRelevancy(user_input, response)
        try:
            result = await ar_metric.ascore(user_input=ui, response=res)
            all_scores["answer_relevancy"].append(
                result.value if hasattr(result, "value") else float(result)
            )
        except Exception as e:
            print(f"\n    [answer_relevancy] error: {e}")
            all_scores["answer_relevancy"].append(float("nan"))

        print("done")

    return all_scores


def run_ragas(records: list[dict]) -> dict[str, float]:
    print("\n--- Running RAGAS (scoring each sample directly) ---\n")

    scores_per_metric = asyncio.run(_score_all(records))

    # Aggregate: mean ignoring NaN
    def mean(vals: list[float]) -> float:
        valid = [v for v in vals if v == v]  # filter NaN
        return sum(valid) / len(valid) if valid else float("nan")

    agg = {k: mean(v) for k, v in scores_per_metric.items()}

    print("\n" + "=" * 60)
    print("        RAGAS EVALUATION RESULTS  (RAGAS 0.4.3)")
    print("=" * 60)
    labels = {
        "context_precision": "Context Precision (pgvector relevance)",
        "context_recall": "Context Recall    (coverage of ground truth)",
        "faithfulness": "Faithfulness      (no hallucinations)",
        "answer_relevancy": "Answer Relevancy  (on-topic response)",
    }
    for key, label in labels.items():
        val = agg[key]
        bar = "█" * round(val * 20) if val == val else "N/A"
        print(f"  {label:<45} {val:.4f}  {bar}")
    print("=" * 60)
    print("  Scores: 0.0 (worst) → 1.0 (best)\n")

    # ── Per-row CSV ────────────────────────────────────────────────────────────
    import pandas as pd

    rows = []
    for i, r in enumerate(records):
        row = {
            "question": r["question"],
            "answer": r["answer"][:120],
            "ground_truth": r["ground_truth"][:120],
        }
        for k, vals in scores_per_metric.items():
            row[k] = vals[i]
        rows.append(row)
    pd.DataFrame(rows).to_csv(RESULTS_CSV, index=False)
    print(f"  Detailed results → {RESULTS_CSV}")

    return agg


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    print("\n=====================================================")
    print("  RAGAS Evaluation — KB-Driven (Travel Chatbot RAG)")
    print("=====================================================")
    print(f"  LLM   : {LLM_MODEL} @ {LLM_BASE_URL}")
    print("  Embed : all-MiniLM-L6-v2 (local)")
    print(f"  Cases : {NUM_TEST_CASES}\n")

    print("Step 1: Sampling KB and auto-generating test dataset...")
    records = build_dataset()
    with open(DATASET_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    print(f"\nDataset saved → {DATASET_FILE}  ({len(records)} rows)")

    print("\nStep 2: Running RAGAS evaluation...")
    run_ragas(records)


if __name__ == "__main__":
    main()
