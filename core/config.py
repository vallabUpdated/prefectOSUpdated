# Auto-split from Orchestrator.py — part of the PrefectOS core package.
"""Environment, constants, logging, and feature toggles."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any
import importlib.util

if importlib.util.find_spec("dotenv") is not None:
    from dotenv import load_dotenv
else:
    def load_dotenv(*_args: Any, **_kwargs: Any) -> bool:
        return False

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("orchestrator")

# NOTE: config.py lives in core/, so the repo root is one level up.
ROOT_DIR      = Path(__file__).resolve().parents[1]
AGENTS_DIR    = ROOT_DIR / "claude_agents"
SKILLS_DIR    = ROOT_DIR / "skills"         # ← SKILL_*.md specialist skill cards
MEMORY_ROOT   = ROOT_DIR / "memory"         # ← one JSON memory record per completed run
MCP_CONFIG    = ROOT_DIR / "mcp_config.json"
PROJECTS_ROOT = ROOT_DIR / "projects"       # ← all per-request project dirs live here

# ── LLM provider ────────────────────────────────────────────────────────────
LLM_PROVIDER    = os.environ.get("DEFAULT_PROVIDER", "anthropic").lower()
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

if LLM_PROVIDER == "ollama":
    WORKER_MODEL     = os.environ.get("OLLAMA_WORKER_MODEL", "qwen2.5:14b")
    SUPERVISOR_MODEL = os.environ.get("OLLAMA_SUPERVISOR_MODEL", "qwen2.5:14b")
else:
    WORKER_MODEL     = os.environ.get("ANTHROPIC_WORKER_MODEL", "claude-haiku-4-5")
    SUPERVISOR_MODEL = os.environ.get("ANTHROPIC_SUPERVISOR_MODEL", "claude-sonnet-4-6")

MAX_AGENTS = 10

# Governed RAG toggle. CLI: --no-rag. Web/server: set RAG_DISABLED=1.
# Read/mutate as core.config.RAG_ENABLED so all modules see one value.
RAG_ENABLED = os.getenv("RAG_DISABLED", "").lower() not in ("1", "true", "yes")
