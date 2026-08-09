# Auto-split from Orchestrator.py — part of the PrefectOS core package.
"""Per-run singletons (registry/factory via contextvars) + venv creation."""
from __future__ import annotations

import contextvars
import shutil
import subprocess
import sys
from pathlib import Path

from .config import log, SKILLS_DIR, MEMORY_ROOT
from .registry import AgentRegistry
from .agents import AgentFactory
from .skills import SkillFactory
from .memory import MemoryStore

# ─────────────────────────────────────────────────────────────────────────────

def create_venv(venv_path: Path, req_path: Path) -> None:
    if venv_path.exists():
        shutil.rmtree(venv_path)
    log.info("Creating venv: %s", venv_path)
    subprocess.run([sys.executable, "-m", "venv", str(venv_path)], check=True)
    pip = (
        venv_path / "Scripts" / "pip.exe"
        if sys.platform == "win32"
        else venv_path / "bin" / "pip"
    )
    subprocess.run([str(pip), "install", "--upgrade", "pip"], check=True)
    subprocess.run([str(pip), "install", "-r", str(req_path)], check=True)
    log.info("venv ready ✔")


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singletons (created fresh per run inside main())
# ─────────────────────────────────────────────────────────────────────────────

# These are set in main() after the project dir is known, then used by nodes.
# The ContextVars support multiple concurrent pipeline runs in one process
# (the web backend runs each pipeline on its own thread): each run thread
# binds its own registry/factory via set_run_context(), and node functions
# resolve them per run — contextvars propagate into LangGraph's task
# execution. The module globals remain as the single-run CLI fallback.
_registry: AgentRegistry | None = None
_factory:  AgentFactory  | None = None
_registry_var: contextvars.ContextVar[AgentRegistry | None] = \
    contextvars.ContextVar("orch_registry", default=None)
_factory_var: contextvars.ContextVar[AgentFactory | None] = \
    contextvars.ContextVar("orch_factory", default=None)


def set_run_context(registry: AgentRegistry, factory: AgentFactory) -> None:
    """Bind this run's registry/factory to the current thread/context."""
    global _registry, _factory
    _registry_var.set(registry)
    _factory_var.set(factory)
    _registry, _factory = registry, factory   # single-run CLI fallback


def _get_registry() -> AgentRegistry:
    reg = _registry_var.get()
    if reg is not None:
        return reg
    assert _registry is not None, "Registry not initialised — call main() first"
    return _registry


def _get_factory() -> AgentFactory:
    fac = _factory_var.get()
    if fac is not None:
        return fac
    assert _factory is not None, "Factory not initialised — call main() first"
    return _factory


# SkillFactory is stateless per run (just reads skills/SKILL_*.md), so a single
# lazily-created instance serves both the CLI and the web backends.
_skill_factory: SkillFactory | None = None


def _get_skill_factory() -> SkillFactory:
    global _skill_factory
    if _skill_factory is None:
        _skill_factory = SkillFactory(SKILLS_DIR)
    return _skill_factory


_memory_store: MemoryStore | None = None


def _get_memory_store() -> MemoryStore:
    global _memory_store
    if _memory_store is None:
        _memory_store = MemoryStore(MEMORY_ROOT)
    return _memory_store

