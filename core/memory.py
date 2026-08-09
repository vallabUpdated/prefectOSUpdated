# Auto-split from Orchestrator.py — part of the PrefectOS core package.
"""Long-term run memory: record completed runs, recall similar ones."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .config import log, MEMORY_ROOT
from .projects import detect_server_url

if TYPE_CHECKING:
    from .state import GraphState

# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MemoryRecord:
    """Distilled experience from one completed run — what was asked, how it was
    planned, what stack/files came out, and what testing/launch revealed."""
    project_id:      str
    created_at:      str
    activity:        str
    skills:          list[str]      # skill ids that were assigned that run
    requirements:    str            # requirements.txt content
    files:           list[str]      # generated file paths
    plan_excerpt:    str
    spec_excerpt:    str
    test_notes:      str            # launch blockers / test report head
    server_url:      str
    generated_skill: str

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MemoryRecord":
        known = {f: d.get(f, "" if f not in ("skills", "files") else [])
                 for f in cls.__dataclass_fields__}
        return cls(**known)


# Common words that would make every activity look related to every other one.
_MEMORY_STOPWORDS = {
    "a", "an", "the", "and", "or", "with", "for", "to", "of", "in", "on", "at",
    "is", "be", "it", "that", "this", "i", "we", "you", "my", "me", "please",
    "build", "create", "make", "made", "want", "need", "using", "use", "app",
    "application", "simple", "basic", "new", "project", "system", "web",
}


class MemoryStore:
    """
    Long-term memory over past runs. Each completed run is distilled into a
    JSON MemoryRecord under memory/<project_id>.json (written by write_audit,
    so both the CLI and the web backend record automatically). Before each
    stage, recall(activity) ranks past records by keyword overlap and the top
    matches are injected into agent prompts — agents see *how* similar past
    projects were planned, what stack they used, and what broke at launch.
    """

    def __init__(self, root: Path = MEMORY_ROOT) -> None:
        self.root = root

    # ── public ──────────────────────────────────────────────────────────────

    def all_records(self) -> list[MemoryRecord]:
        records = []
        if not self.root.exists():
            return records
        for p in sorted(self.root.glob("*.json")):
            try:
                records.append(MemoryRecord.from_dict(
                    json.loads(p.read_text(encoding="utf-8"))))
            except (json.JSONDecodeError, TypeError) as exc:
                log.warning("Skipping unreadable memory %s: %s", p.name, exc)
        return records

    def record_run(self, state: "GraphState") -> MemoryRecord:
        """Distil a completed run's state into a memory record and persist it."""
        project_dir = Path(state["project_dir"])

        skills: list[str] = []
        sa_path = project_dir / "skills_assigned.json"
        if sa_path.exists():
            assignments = json.loads(sa_path.read_text(encoding="utf-8"))
            for stage_skills in assignments.values():
                if isinstance(stage_skills, list):
                    skills += [s["skill_id"] for s in stage_skills if isinstance(s, dict)]
        skills = sorted(set(skills))

        rec = MemoryRecord(
            project_id=state["thread_id"],
            created_at=datetime.now().isoformat(timespec="seconds"),
            activity=state["activity"],
            skills=skills,
            requirements=state.get("requirements", "")[:600],
            files=list(state.get("source_files", {}).keys()),
            plan_excerpt=state.get("plan", "")[:900],
            spec_excerpt=state.get("spec", "")[:900],
            test_notes=state.get("test_report", "")[:700],
            server_url=detect_server_url(project_dir) or "",
            generated_skill=state.get("generated_skill", ""),
        )
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / f"{rec.project_id}.json").write_text(
            json.dumps(rec.as_dict(), indent=2), encoding="utf-8"
        )
        log.info("MemoryStore ▶ recorded run memory: %s", rec.project_id)
        return rec

    def recall(
        self,
        activity:        str,
        k:               int = 3,
        exclude_project: str | None = None,
    ) -> list[MemoryRecord]:
        """Top-k past runs most relevant to the activity. Matches on the past
        run's activity (weight 3) and its skills/requirements/files (weight 1);
        records below a minimum score are dropped rather than padded in."""
        query = self._tokens(activity)
        if not query:
            return []
        scored: list[tuple[float, MemoryRecord]] = []
        for rec in self.all_records():
            if exclude_project and rec.project_id == exclude_project:
                continue
            primary   = self._tokens(rec.activity)
            secondary = self._tokens(
                " ".join(rec.skills) + " " + rec.requirements + " " + " ".join(rec.files)
            )
            score = 3 * len(query & primary) + len(query & secondary)
            if score >= 3:
                scored.append((score, rec))
        scored.sort(key=lambda t: (-t[0], t[1].created_at))
        return [rec for _, rec in scored[:k]]

    @staticmethod
    def render_context(memories: list["MemoryRecord"]) -> str:
        """Format recalled runs as a system-prompt section."""
        if not memories:
            return ""
        lines = [
            "## Relevant Past Project Experience",
            "",
            "The orchestrator has built similar projects before. Use these as "
            "reference for stack choices, structure, and pitfalls — but follow "
            "the current activity's requirements where they differ.",
            "",
        ]
        for m in memories:
            lines += [
                f"### Past project: {m.activity}  ({m.created_at[:10]})",
                f"- Skills used: {', '.join(m.skills) or 'none'}",
                f"- Stack (requirements): {' '.join(m.requirements.split()) or 'n/a'}",
                f"- Files produced: {', '.join(m.files[:12]) or 'n/a'}",
                f"- Plan approach: {' '.join(m.plan_excerpt.split())[:400] or 'n/a'}",
                f"- Testing/launch notes: {' '.join(m.test_notes.split())[:300] or 'n/a'}",
                "",
            ]
        return "\n".join(lines)

    # ── private ─────────────────────────────────────────────────────────────

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {
            t for t in re.findall(r"[a-z0-9]+", text.lower())
            if len(t) > 1 and t not in _MEMORY_STOPWORDS
        }


