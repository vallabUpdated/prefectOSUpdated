# Auto-split from Orchestrator.py — part of the PrefectOS core package.
"""Agent-output parsers and generated-file defaults."""
from __future__ import annotations

import re
from pathlib import Path

from .config import log

# ─────────────────────────────────────────────────────────────────────────────

def parse_env_blocks(raw: str) -> tuple[str, str]:
    bash_m = re.search(r"```bash\s*(.*?)```", raw, re.DOTALL)
    env_script = bash_m.group(1).strip() if bash_m else _default_env_script()
    req_m = re.search(
        r"requirements\.txt.*?```(?:text|plaintext|)?\s*(.*?)```",
        raw, re.DOTALL | re.IGNORECASE,
    )
    if not req_m:
        blocks       = re.findall(r"```(?:\w*)\s*(.*?)```", raw, re.DOTALL)
        requirements = blocks[-1].strip() if len(blocks) >= 2 else _default_requirements()
    else:
        requirements = req_m.group(1).strip()
    return env_script, requirements


def parse_file_blocks(raw: str) -> dict[str, str]:
    pattern = re.compile(r"###\s*FILE:\s*(.+?)\n```(?:\w*)\s*(.*?)```", re.DOTALL)
    files: dict[str, str] = {}
    for m in pattern.finditer(raw):
        files[m.group(1).strip()] = m.group(2).strip()
    if not files:
        log.warning("No FILE blocks found — saving raw output.")
        files["generated_output.txt"] = raw
    return files


def parse_test_output(raw: str) -> tuple[dict[str, str], str]:
    """Split TESTER output into ({test file path: content}, test report markdown)."""
    pattern = re.compile(r"###\s*FILE:\s*(.+?)\n```(?:\w*)\s*(.*?)```", re.DOTALL)
    files: dict[str, str] = {}
    for m in pattern.finditer(raw):
        files[m.group(1).strip()] = m.group(2).strip()
    rep_m  = re.search(r"###\s*TEST REPORT\s*\n(.*)$", raw, re.DOTALL)
    report = rep_m.group(1).strip() if rep_m else ""
    if not files and not report:
        report = raw.strip()   # unstructured output — keep it all as the report
    return files, report


def syntax_check(src_dir: Path) -> list[str]:
    """py_compile every generated .py file; return a list of error strings."""
    import py_compile
    errors = []
    for p in sorted(src_dir.rglob("*.py")):
        if ".venv" in p.parts:
            continue
        try:
            py_compile.compile(str(p), doraise=True)
        except py_compile.PyCompileError as exc:
            errors.append(f"{p.relative_to(src_dir)}: {exc.msg}")
        except OSError as exc:
            errors.append(f"{p.relative_to(src_dir)}: {exc}")
    return errors


def parse_skill_card(raw: str) -> tuple[str, str] | None:
    """Parse SKILL_WRITER output: a 'SKILL_ID: <ID>' line followed by a fenced
    markdown block holding the full card. Returns (skill_id, card) or None."""
    m = re.search(r"SKILL_ID:\s*([A-Z][A-Z0-9_]*)", raw)
    if not m:
        return None
    skill_id = m.group(1).removeprefix("SKILL_")
    rest = raw[m.end():]
    block = re.search(r"```(?:markdown|md)?\s*\n(---.*)\n```", rest, re.DOTALL)
    if block:
        card = block.group(1).strip()
    else:
        # no fence — accept the remainder if it starts with frontmatter
        card = rest.strip()
        if not card.startswith("---"):
            return None
    return skill_id, card + "\n"


def _default_env_script() -> str:
    return (
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "python -m venv .venv\n"
        "# Unix:    source .venv/bin/activate\n"
        "# Windows: .venv\\Scripts\\activate\n"
        ".venv/bin/pip install --upgrade pip\n"
        ".venv/bin/pip install -r requirements.txt\n"
        'echo "Environment ready."\n'
    )


def _default_requirements() -> str:
    return (
        "python-dotenv>=1.0,<2.0\nanthropic>=0.40,<1.0\n"
        "langchain-anthropic>=0.3,<1.0\nlanggraph>=0.2,<1.0\n"
        "langchain-core>=0.3,<1.0\n"
    )


