# Part of the PrefectOS core package — batch_ingest.
"""Exception-only LLM resolver — enforces the 20% fresh-token budget.

Two call paths, same token discipline:
  1. Pooled (production): a PooledAgent injected by the BatchOrchestrator —
     batch token budget, concurrency semaphore, pool metering, and the
     cached system prompt all come from core/pooled_agents.py.
  2. Direct (standalone/dev): the module falls back to its own Anthropic
     client with the same `cache_control: ephemeral` system prompt.

Either way the user turn contains ONLY the failing rows (~200-400 fresh
tokens) against a ~1,100-token cached system prompt: fresh share per call
~= 20-25%. Clean docs (the majority) consume zero tokens.
"""
from __future__ import annotations

import json
import os

MODEL = os.getenv("INGEST_EXCEPTION_MODEL", "claude-haiku-4-5-20251001")
BASE_URL = os.getenv("INGEST_LLM_BASE_URL", "")        # e.g. LiteLLM proxy
MAX_ROWS_PER_CALL = 20

SYSTEM_PROMPT = """You are the PrefectOS statement-exception resolver for BFSI \
document processing. You receive ONLY the rows of a bank statement that failed \
deterministic validation, never the full document. For each failing row, decide:

1. amounts: identify the transaction amount and the running balance from the raw \
text. Amounts use Indian comma grouping and two decimals; balances may be negative.
2. direction: "debit" or "credit", consistent with the expected balance delta \
provided by the validator.
3. channel: one of NEFT, RTGS, IMPS, UPI, CHQ, SWIFT-IN, SWIFT-OUT, INT-TRF, \
or null if genuinely absent.
4. narration: the cleaned narration text with amounts removed.
5. resolvable: false if the raw text is too corrupted to repair — do not guess.

Rules:
- Never invent digits. If an amount is ambiguous, set resolvable=false.
- A balance_chain_break may be a mis-read amount OR a genuinely anomalous \
statement; repair only when the raw text supports exactly one reading.
- Respond with ONLY a JSON array, one object per input row, keys: \
txn_id, amount, balance, direction, channel, narration, resolvable. \
No prose, no markdown fences."""


def _direct_client():
    """Provider-aware: INGEST_LLM_PROVIDER=bedrock -> AWS Bedrock via IAM
    (no API key on the box); anything else -> Anthropic API / LiteLLM proxy."""
    provider = (os.getenv("INGEST_LLM_PROVIDER")
                or os.getenv("PREFECTOS_LLM_PROVIDER", "anthropic")).lower()
    if provider == "bedrock":
        from anthropic import AsyncAnthropicBedrock
        return AsyncAnthropicBedrock(
            aws_region=os.getenv("AWS_REGION", "ap-south-1"))
    from anthropic import AsyncAnthropic
    kwargs = {}
    if BASE_URL:
        kwargs["base_url"] = BASE_URL
    return AsyncAnthropic(**kwargs)


def _build_payload(row_exc: list[dict]) -> str:
    return json.dumps([{"txn_id": e["txn_id"], "raw": e.get("raw", ""),
                        "failure": e["reason"],
                        "expected_delta": e.get("expected_delta"),
                        "observed_delta": e.get("observed_delta")}
                       for e in row_exc])


async def _call(payload: str, resolver=None) -> tuple[str, dict] | None:
    """Route through the pooled agent when provided, else the direct client.
    Returns (text, usage) or None when no LLM is configured / budget spent."""
    if resolver is not None:
        try:
            return await resolver.acall(payload, max_tokens=1024)
        except Exception:                    # budget exhausted / tier down -> HITL
            return None
    prov = (os.getenv("INGEST_LLM_PROVIDER")
            or os.getenv("PREFECTOS_LLM_PROVIDER", "anthropic")).lower()
    if not os.getenv("ANTHROPIC_API_KEY") and not BASE_URL and prov != "bedrock":
        import logging
        logging.getLogger("prefectos").warning(
            "LLM not configured (no ANTHROPIC_API_KEY / BASE_URL / bedrock) — "
            "exceptions will escalate to HITL. Set the key in /etc/prefectos.env "
            "and run scripts/check_llm.py to verify.")
        return None
    msg = await _direct_client().messages.create(
        model=MODEL, max_tokens=1024,
        system=[{"type": "text", "text": SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": payload}])
    usage = {"input_tokens": msg.usage.input_tokens,
             "cache_read_tokens": getattr(msg.usage, "cache_read_input_tokens", 0) or 0,
             "output_tokens": msg.usage.output_tokens}
    return (msg.content[0].text if msg.content else ""), usage


async def resolve_exceptions(result, resolver=None) -> dict | None:
    """Repair row-level exceptions. Returns final output dict, or None to escalate.

    Header/totals-scope exceptions escalate straight to HITL — the LLM only
    ever adjudicates rows, keeping calls small and the blast radius bounded.
    """
    row_exc = [e for e in result.exceptions if e.get("scope") == "row"]
    other_exc = [e for e in result.exceptions if e.get("scope") != "row"]
    if other_exc or not row_exc:
        return None
    if len(row_exc) > MAX_ROWS_PER_CALL:          # doc is garbage, not an exception
        return None

    reply = await _call(_build_payload(row_exc), resolver=resolver)
    if reply is None:
        return None
    text, usage = reply
    try:
        repairs = json.loads(text)
        by_id = {r["txn_id"]: r for r in repairs if r.get("resolvable")}
    except (json.JSONDecodeError, KeyError, TypeError):
        return None
    if len(by_id) < len(row_exc):                  # LLM abstained on some rows
        return None

    for txn in result.transactions:
        fix = by_id.get(txn["txn_id"])
        if fix:
            txn.update(amount=fix["amount"], balance=fix["balance"],
                       direction=fix["direction"], channel=fix["channel"],
                       narration=fix["narration"], repaired_by="llm")
    out = result.to_output()
    out["status"] = "resolved_by_llm"
    out["usage"] = usage
    return out
