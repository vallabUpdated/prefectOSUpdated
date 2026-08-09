#!/usr/bin/env python3
"""PrefectOS LLM preflight — run this ONCE after setting your key, before any batch.

    python3 scripts/check_llm.py

Verifies, in order:
  1. Which provider/model the resolver route resolves to
  2. That a real call succeeds (tiny, ~₹0.02)
  3. That prompt caching engages on the second call (your 20%-fresh-token
     economics depend on this) — cache_read_tokens must be > 0
Exit 0 = ready for batches. Non-zero = fix the printed issue first.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main() -> int:
    from core.routing import resolve_role
    route = resolve_role("resolver")
    print(f"provider : {route.tier}")
    print(f"model    : {route.model}")
    print(f"base_url : {route.base_url or '(default endpoint)'}")

    if route.tier == "anthropic" and not route.base_url \
            and not os.getenv("ANTHROPIC_API_KEY"):
        print("\n✗ ANTHROPIC_API_KEY is not set.")
        print("  Get one at console.anthropic.com -> API keys, put it in")
        print("  /etc/prefectos.env, then:  set -a; source /etc/prefectos.env; set +a")
        return 2

    if route.tier == "bedrock":
        from anthropic import AsyncAnthropicBedrock
        client = AsyncAnthropicBedrock(
            aws_region=os.getenv("AWS_REGION", "ap-south-1"))
    else:
        from anthropic import AsyncAnthropic
        kwargs = {}
        if route.base_url:
            kwargs["base_url"] = route.base_url
        client = AsyncAnthropic(**kwargs)

    system = [{"type": "text",
               "text": "You are the PrefectOS preflight probe. Reply with exactly "
                       "the single word OK and nothing else. " + ("pad " * 400),
               "cache_control": {"type": "ephemeral"}}]

    async def probe(n: int):
        msg = await client.messages.create(
            model=route.model, max_tokens=8, system=system,
            messages=[{"role": "user", "content": f"probe {n}"}])
        u = msg.usage
        return (msg.content[0].text.strip() if msg.content else "",
                u.input_tokens,
                getattr(u, "cache_creation_input_tokens", 0) or 0,
                getattr(u, "cache_read_input_tokens", 0) or 0)

    try:
        text1, in1, cw1, cr1 = await probe(1)
    except Exception as exc:
        print(f"\n✗ Call FAILED: {type(exc).__name__}: {exc}")
        print("  Common causes: wrong/expired key, no Console credits,")
        print("  model name typo, or (bedrock) IAM/verification not ready.")
        return 3
    print(f"\ncall 1   : '{text1}' — fresh_in={in1} cache_write={cw1} cache_read={cr1}")

    text2, in2, cw2, cr2 = await probe(2)
    print(f"call 2   : '{text2}' — fresh_in={in2} cache_write={cw2} cache_read={cr2}")

    if cr2 > 0:
        pct = 100 * in2 / (in2 + cr2)
        print(f"\n✔ READY — key works, caching engaged "
              f"(call 2 fresh share {pct:.0f}%). Batches will run on this config.")
        return 0
    print("\n! Key works but cache_read=0 on call 2 — caching may be unsupported "
          "on this route (e.g. some proxies). Batches will run; token costs "
          "will be ~4-5x the cached estimates.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
