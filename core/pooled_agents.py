# PrefectOS core — pooled agents for the batch data plane.
"""PooledAgent / PooledAgentFactory — additive; existing agents untouched.

`AgentFactory` + `_EphemeralAgent` (core/agents.py) stay exactly as they are
for one-shot governed tasks (Stage 0 comprehension, planning, generation).

This module adds the second agent shape needed for burst document processing:

  PooledAgent   long-lived, stateless between calls, async, created once per
                batch role (classifier / resolver), reused for every call in
                the burst. System prompt (agent file + skill cards) is sent
                with `cache_control: ephemeral`, so it bills as cache reads
                after the first call — the mechanism behind the 20%
                fresh-token budget.

  TokenBudget   per-batch spend meter. Fresh input + output tokens count;
                cache reads do not. Exhaustion raises
                TokenBudgetExhaustedError (a BudgetExhaustedError, so all
                existing handlers catch it) — remaining exceptions then
                escalate to HITL instead of burning money.

  Semaphore     caps concurrent in-flight LLM calls to the inference tier's
                real capacity, so a burst cannot stampede the GPU pool.

No LangChain dependency: the Anthropic SDK is imported lazily, and any
OpenAI-compatible endpoint (LiteLLM proxy -> vLLM) works via base_url.
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import log, AGENTS_DIR
from .errors import BudgetExhaustedError
from .routing import resolve_role, RouteConfig
from .pool_registry import PoolRegistry

try:
    from decision_ledger import record as ledger_record, sha256_text
except ImportError:                                    # standalone tests
    def ledger_record(*a, **kw): pass                  # noqa: E731
    def sha256_text(t):                                # noqa: E731
        import hashlib; return hashlib.sha256(t.encode()).hexdigest()


class TokenBudgetExhaustedError(BudgetExhaustedError):
    """Per-batch fresh-token budget spent; further LLM calls must escalate."""


@dataclass
class TokenBudget:
    limit: int
    fresh_input: int = 0
    cache_read: int = 0
    output: int = 0

    @property
    def spent(self) -> int:                 # cache reads are NOT fresh spend
        return self.fresh_input + self.output

    @property
    def remaining(self) -> int:
        return max(self.limit - self.spent, 0)

    def charge(self, usage) -> None:
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        self.fresh_input += (usage.input_tokens or 0)
        self.cache_read += cache_read
        self.output += (usage.output_tokens or 0)

    def check(self) -> None:
        if self.spent >= self.limit:
            raise TokenBudgetExhaustedError(
                f"Batch token budget exhausted "
                f"({self.spent}/{self.limit} fresh tokens). "
                f"Remaining exceptions escalate to HITL.")

    def snapshot(self) -> dict:
        total = self.fresh_input + self.cache_read
        return {"limit": self.limit, "fresh_input": self.fresh_input,
                "cache_read": self.cache_read, "output": self.output,
                "spent": self.spent, "remaining": self.remaining,
                "fresh_share_pct": round(100 * self.fresh_input / total, 1)
                                   if total else None}


@dataclass
class PooledAgent:
    """One long-lived agent role serving many calls within a batch."""
    agent_id: str
    role: str
    system_prompt: str
    route: RouteConfig
    budget: TokenBudget
    semaphore: asyncio.Semaphore
    pool_registry: PoolRegistry | None = None
    _client: object = field(default=None, repr=False)

    def _get_client(self):
        if self._client is None:
            if getattr(self.route, "provider", "anthropic") == "bedrock":
                import os
                from anthropic import AsyncAnthropicBedrock
                self._client = AsyncAnthropicBedrock(
                    aws_region=os.getenv("AWS_REGION", "ap-south-1"))
                return self._client
            from anthropic import AsyncAnthropic
            kwargs = {}
            if self.route.base_url:
                kwargs["base_url"] = self.route.base_url
            if self.route.api_key:
                kwargs["api_key"] = self.route.api_key
            self._client = AsyncAnthropic(**kwargs)
        return self._client

    async def acall(self, user_content: str, max_tokens: int = 1024) -> tuple[str, dict]:
        """One pooled call. Returns (text, usage_dict). Budget-checked,
        semaphore-bounded, registry-metered. Raises TokenBudgetExhaustedError
        BEFORE spending when the budget is already gone."""
        self.budget.check()
        t0 = time.perf_counter()
        async with self.semaphore:
            if self.pool_registry:
                self.pool_registry.call_started(self.agent_id)
            try:
                msg = await self._get_client().messages.create(
                    model=self.route.model,
                    max_tokens=max_tokens,
                    system=[{"type": "text", "text": self.system_prompt,
                             "cache_control": {"type": "ephemeral"}}],
                    messages=[{"role": "user", "content": user_content}],
                )
            except Exception as exc:
                if self.pool_registry:
                    self.pool_registry.call_finished(
                        self.agent_id, ok=False, elapsed_s=time.perf_counter() - t0)
                raise
        self.budget.charge(msg.usage)
        usage = {
            "input_tokens": msg.usage.input_tokens,
            "cache_read_tokens": getattr(msg.usage, "cache_read_input_tokens", 0) or 0,
            "output_tokens": msg.usage.output_tokens,
        }
        if self.pool_registry:
            self.pool_registry.call_finished(
                self.agent_id, ok=True, elapsed_s=time.perf_counter() - t0,
                fresh_tokens=usage["input_tokens"] + usage["output_tokens"],
                cached_tokens=usage["cache_read_tokens"])
        text = msg.content[0].text if msg.content else ""
        return text, usage


class PooledAgentFactory:
    """Creates pooled agents for a batch. Mirrors AgentFactory's contract
    (CLAUDE_<id>.md definition files, ledger record on spawn) but registers
    aggregate pool records instead of per-call lifecycle rows."""

    def __init__(self, batch_id: str, project_dir: Path,
                 agents_dir: Path = AGENTS_DIR,
                 token_budget_limit: int | None = None,
                 max_concurrency: int | None = None):
        self.batch_id = batch_id
        self.agents_dir = Path(agents_dir)
        self.budget = TokenBudget(limit=token_budget_limit or int(
            os.getenv("BATCH_TOKEN_BUDGET", "500000")))
        self.semaphore = asyncio.Semaphore(max_concurrency or int(
            os.getenv("POOL_MAX_CONCURRENCY", "16")))
        self.pool_registry = PoolRegistry(project_dir)
        self._pools: dict[str, PooledAgent] = {}

    def get(self, agent_id: str, role: str,
            extra_context: str = "") -> PooledAgent:
        """Create-or-reuse a pooled agent. `extra_context` (e.g. batch-time
        skill cards) is folded into the CACHED system prompt exactly once."""
        if agent_id in self._pools:
            return self._pools[agent_id]

        md_path = self.agents_dir / f"CLAUDE_{agent_id}.md"
        system_prompt = (md_path.read_text(encoding="utf-8")
                         if md_path.exists()
                         else f"You are the PrefectOS {role} agent.")
        if not md_path.exists():
            log.warning("PooledAgentFactory ▶ no %s — using minimal prompt",
                        md_path.name)
        if extra_context:
            system_prompt += "\n\n" + extra_context

        route = resolve_role(role)
        agent = PooledAgent(agent_id=agent_id, role=role,
                            system_prompt=system_prompt, route=route,
                            budget=self.budget, semaphore=self.semaphore,
                            pool_registry=self.pool_registry)
        self._pools[agent_id] = agent

        self.pool_registry.register_pool(
            agent_id=agent_id, role=role, model=route.model,
            tier=route.tier, batch_id=self.batch_id)
        ledger_record(
            "agent_spawn",                       # same event as AgentFactory
            agent_id=agent_id, stage=f"batch:{role}", model=route.model,
            provider=route.tier, slot=len(self._pools),
            budget_limit=self.budget.limit, pooled=True,
            batch_id=self.batch_id, skills=[], memories=[],
            system_prompt_sha256=sha256_text(system_prompt),
            agent_file=md_path.name if md_path.exists() else "(builtin)")
        log.info("PooledAgentFactory ▶ pool [%s] role=%s model=%s tier=%s",
                 agent_id, role, route.model, route.tier)
        return agent

    def usage_summary(self) -> dict:
        return {"token_budget": self.budget.snapshot(),
                "pools": self.pool_registry.snapshot()}
