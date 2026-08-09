"""
comprehension.py — turn an existing (possibly undocumented) codebase into a
bounded, prompt-ready digest for the COMPREHENDER agent.

This is the substrate for the legacy-comprehension entry stage: before the
planner proposes any change, PrefectOS reads the system as it exists today.
The digest is deliberately size-capped so it fits a single agent invocation:

  1. A directory tree (vendor/binary/VCS dirs pruned).
  2. Full text of high-signal files (READMEs, configs, dependency manifests).
  3. Head excerpts of source files, largest-first within a byte budget.

stdlib only — no new dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Directories that are never useful to a comprehension pass.
SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    "env", ".idea", ".vscode", "dist", "build", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "site-packages", "coverage", ".next", ".cache", "target",
}

# Extensions we read as text source.
SOURCE_EXTS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".cs", ".go", ".rb", ".php",
    ".sql", ".sh", ".bat", ".ps1", ".html", ".css", ".gosu", ".gs", ".gsx",
    ".cbl", ".cob", ".cpy", ".pli", ".rpg",  # legacy cores are the point
    ".c", ".h", ".cpp", ".hpp", ".rs", ".kt", ".scala", ".vb",
}

# Filenames whose *entire* content is high-signal (within per-file cap).
PRIORITY_NAMES = {
    "readme.md", "readme.txt", "readme.rst", "claude.md", "architecture.md",
    "requirements.txt", "pyproject.toml", "package.json", "pom.xml",
    "build.gradle", "dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "makefile", ".env.example", "settings.py", "config.py", "app.config",
    "web.config", "appsettings.json", "schema.sql", "openapi.yaml",
    "openapi.json", "swagger.yaml", "manifest.json",
}

SECRET_NAMES = {".env", ".env.local", ".env.production", "credentials.json",
                "id_rsa", "id_ed25519", ".npmrc", ".pypirc"}

MAX_TOTAL_BYTES     = 120_000   # whole digest budget (~30k tokens)
MAX_PRIORITY_BYTES  = 8_000     # per priority file
MAX_SOURCE_BYTES    = 4_000     # per source-file excerpt
MAX_TREE_ENTRIES    = 400


@dataclass
class DigestStats:
    files_seen:     int = 0
    files_included: int = 0
    files_skipped_secret: list[str] = field(default_factory=list)
    truncated:      bool = False


def _is_probably_binary(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return b"\x00" in fh.read(1024)
    except OSError:
        return True


def _read_capped(path: Path, cap: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"[unreadable: {exc}]"
    if len(text) > cap:
        return text[:cap] + f"\n… [truncated — {len(text):,} chars total]"
    return text


def _walk(root: Path) -> list[Path]:
    """Deterministic, pruned file walk."""
    out: list[Path] = []
    stack = [root]
    while stack:
        d = stack.pop()
        try:
            children = sorted(d.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError:
            continue
        for child in children:
            if child.is_dir():
                if child.name.lower() not in SKIP_DIRS and not child.is_symlink():
                    stack.append(child)
            elif child.is_file():
                out.append(child)
    return sorted(out, key=lambda p: str(p.relative_to(root)).lower())


def build_codebase_digest(
    root: Path | str,
    max_total_bytes: int = MAX_TOTAL_BYTES,
) -> tuple[str, DigestStats]:
    """Return (digest_markdown, stats) for the codebase under `root`.

    Raises FileNotFoundError / NotADirectoryError for a bad path so the
    caller can fail the stage loudly instead of comprehending nothing.
    """
    root = Path(root).expanduser().resolve()
    if not root.exists():
        raise FileNotFoundError(f"Codebase path does not exist: {root}")
    if not root.is_dir():
        raise NotADirectoryError(f"Codebase path is not a directory: {root}")

    stats = DigestStats()
    files = _walk(root)
    stats.files_seen = len(files)

    # ── 1. tree ────────────────────────────────────────────────────────────
    tree_lines = [f"# Codebase digest: {root.name}", "", "## File tree", "```"]
    for p in files[:MAX_TREE_ENTRIES]:
        tree_lines.append(str(p.relative_to(root)))
    if len(files) > MAX_TREE_ENTRIES:
        tree_lines.append(f"… and {len(files) - MAX_TREE_ENTRIES} more files")
    tree_lines.append("```")
    parts = ["\n".join(tree_lines)]
    used = len(parts[0])

    def _emit(header: str, body: str) -> bool:
        nonlocal used
        block = f"\n\n## {header}\n```\n{body}\n```"
        if used + len(block) > max_total_bytes:
            stats.truncated = True
            return False
        parts.append(block)
        used += len(block)
        stats.files_included += 1
        return True

    # ── 2. priority files (full-ish) ───────────────────────────────────────
    priority, source = [], []
    for p in files:
        name = p.name.lower()
        if name in SECRET_NAMES:
            stats.files_skipped_secret.append(str(p.relative_to(root)))
            continue
        if name in PRIORITY_NAMES:
            priority.append(p)
        elif p.suffix.lower() in SOURCE_EXTS:
            source.append(p)

    for p in priority:
        if _is_probably_binary(p):
            continue
        if not _emit(str(p.relative_to(root)), _read_capped(p, MAX_PRIORITY_BYTES)):
            break

    # ── 3. source excerpts, largest files first (they hold the logic) ─────
    if not stats.truncated:
        for p in sorted(source, key=lambda q: q.stat().st_size, reverse=True):
            if _is_probably_binary(p):
                continue
            if not _emit(f"{p.relative_to(root)} (excerpt)",
                         _read_capped(p, MAX_SOURCE_BYTES)):
                break

    if stats.files_skipped_secret:
        parts.append(
            "\n\n## Withheld files\nThe following files look like credentials "
            "and were NOT included in this digest: "
            + ", ".join(stats.files_skipped_secret)
        )

    return "".join(parts), stats
