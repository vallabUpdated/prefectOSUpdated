# Auto-split from Orchestrator.py — part of the PrefectOS core package.
"""Ephemeral one-shot agents and the budgeted AgentFactory."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from langchain_anthropic import ChatAnthropic
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate

from decision_ledger import record as ledger_record, sha256_text

from .config import (log, LLM_PROVIDER, OLLAMA_BASE_URL,
                     WORKER_MODEL, SUPERVISOR_MODEL, MAX_AGENTS)
from .errors import BudgetExhaustedError
from .registry import AgentRegistry, AgentStatus
from .skills import Skill, SkillFactory
from .memory import MemoryRecord, MemoryStore

# ─────────────────────────────────────────────────────────────────────────────

class _EphemeralAgent:
    """
    Single-use LangChain agent.
    Reports every state transition to the AgentRegistry so it is
    always visible at runtime.
    """

    def __init__(
        self,
        agent_id:      str,
        llm:           ChatAnthropic,
        system_prompt: str,
        md_path:       Path,
        registry:      AgentRegistry,
    ) -> None:
        self.agent_id  = agent_id
        self.md_path   = md_path
        self._llm      = llm
        self._sys      = system_prompt
        self._alive    = True
        self._registry = registry
        self._t0       = time.perf_counter()

        self._prompt = ChatPromptTemplate.from_messages([
            ("system", "{system}"),
            ("human",  "{user}"),
        ])
        self._chain = self._prompt | self._llm

        # Mark ALIVE as soon as the object is fully constructed
        self._registry.mark_alive(agent_id)

    def invoke(self, user_message: str) -> str:
        if not self._alive:
            raise RuntimeError(f"[{self.agent_id}] Already torn down.")
        log.info("[%s] Invoking LangChain chain …", self.agent_id)
        try:
            response = self._chain.invoke({"system": self._sys, "user": user_message})
            text     = response.content if hasattr(response, "content") else str(response)
            elapsed  = time.perf_counter() - self._t0
            log.info("[%s] %d chars received", self.agent_id, len(text))
            self._teardown(elapsed=elapsed, output_chars=len(text))
            return text
        except Exception as exc:
            self._registry.mark_failed(self.agent_id, str(exc))
            raise

    def _teardown(self, elapsed: float, output_chars: int) -> None:
        self._llm    = None   # type: ignore[assignment]
        self._chain  = None   # type: ignore[assignment]
        self._prompt = None   # type: ignore[assignment]
        self._sys    = ""
        self._alive  = False
        self._registry.mark_torn_down(
            self.agent_id, elapsed_s=elapsed, output_chars=output_chars
        )


# ─────────────────────────────────────────────────────────────────────────────
# AgentFactory — budget enforcement + registry integration
# ─────────────────────────────────────────────────────────────────────────────

class AgentFactory:
    """
    Reads CLAUDE_*.md files, enforces MAX_AGENTS budget, updates AgentRegistry
    on every spawn, and creates _EphemeralAgent instances that self-report
    ALIVE and TORN_DOWN transitions back to the registry.
    """

    def __init__(
        self,
        agents_dir: Path,
        mcp_config: Path,
        registry:   AgentRegistry,
    ) -> None:
        self.agents_dir      = agents_dir
        self.mcp_config      = mcp_config
        self._registry       = registry
        self._total_spawned  = 0
        self._validate_env()

    @property
    def budget_remaining(self) -> int:
        return MAX_AGENTS - self._total_spawned

    @property
    def total_spawned(self) -> int:
        return self._total_spawned

    def spawn(
        self,
        agent_id:   str,
        stage:      str,
        supervisor: bool = False,
        inject_mcp: bool = False,
        skills:     list["Skill"] | None = None,
        memories:   list["MemoryRecord"] | None = None,
    ) -> _EphemeralAgent:
        if self._total_spawned >= MAX_AGENTS:
            raise BudgetExhaustedError(
                f"Agent budget exhausted ({MAX_AGENTS} max). "
                "Increase MAX_AGENTS or split the task."
            )

        md_path = self.agents_dir / f"CLAUDE_{agent_id}.md"
        if not md_path.exists():
            raise FileNotFoundError(f"Agent definition not found: {md_path}")

        system_prompt = md_path.read_text(encoding="utf-8")
        if inject_mcp:
            system_prompt += "\n\n" + self._mcp_context()
        if skills:
            system_prompt += "\n\n" + SkillFactory.render_context(skills)
            log.info(
                "AgentFactory ▶ [%s] equipped with skills: %s",
                agent_id, ", ".join(s.skill_id for s in skills),
            )
        if memories:
            system_prompt += "\n\n" + MemoryStore.render_context(memories)
            log.info(
                "AgentFactory ▶ [%s] recalled memories: %s",
                agent_id, ", ".join(m.project_id for m in memories),
            )

        model_name = SUPERVISOR_MODEL if supervisor else WORKER_MODEL
        if LLM_PROVIDER == "ollama":
            llm = ChatOllama(model=model_name, base_url=OLLAMA_BASE_URL)
        else:
            llm = ChatAnthropic(
                model=model_name,
                anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
                max_tokens=4096,
            )

        self._total_spawned += 1

        # Register PENDING first, then _EphemeralAgent.__init__ will mark ALIVE
        self._registry.register(
            agent_id=agent_id,
            slot=self._total_spawned,
            model=model_name,
            stage=stage,
        )

        log.info(
            "AgentFactory ▶ spawning [%s] with %s  (budget: %d/%d)",
            agent_id, model_name, self._total_spawned, MAX_AGENTS,
        )
        ledger_record(
            "agent_spawn",
            agent_id=agent_id,
            stage=stage,
            model=model_name,
            provider=LLM_PROVIDER,
            slot=self._total_spawned,
            budget_limit=MAX_AGENTS,
            skills=[s.skill_id for s in (skills or [])],
            memories=[m.project_id for m in (memories or [])],
            system_prompt_sha256=sha256_text(system_prompt),
            agent_file=md_path.name,
        )
        return _EphemeralAgent(
            agent_id=agent_id,
            llm=llm,
            system_prompt=system_prompt,
            md_path=md_path,
            registry=self._registry,
        )

    def display_agent_file(self, agent_id: str) -> str:
        md_path = self.agents_dir / f"CLAUDE_{agent_id}.md"
        if not md_path.exists():
            return f"[Not found: {md_path}]"
        content = md_path.read_text(encoding="utf-8")
        sep = "═" * 70
        print(f"\n{sep}")
        print(f"  AGENT DEFINITION FILE  →  {md_path.name}")
        print(f"  Budget: {self._total_spawned}/{MAX_AGENTS} used  |  {self.budget_remaining} remaining")
        print(sep)
        print(content)
        print(sep + "\n")
        return content

    def available(self) -> list[str]:
        return [p.stem.replace("CLAUDE_", "") for p in self.agents_dir.glob("CLAUDE_*.md")]

    def _validate_env(self) -> None:
        if LLM_PROVIDER == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
            raise EnvironmentError("ANTHROPIC_API_KEY is not set.")

    def _mcp_context(self) -> str:
        if not self.mcp_config.exists():
            return ""
        cfg = json.loads(self.mcp_config.read_text(encoding="utf-8"))
        lines = ["## Available MCP Servers\n"]
        for name, details in cfg.get("mcpServers", {}).items():
            caps = details.get("capabilities", [])
            lines.append(f"### {name}")
            lines.append(f"Description: {details.get('description','')}")
            if caps:
                lines.append("Capabilities: " + ", ".join(f"`{c}`" for c in caps))
            lines.append("")
        return "\n".join(lines)


