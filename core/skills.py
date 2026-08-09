# Auto-split from Orchestrator.py — part of the PrefectOS core package.
"""Specialist skill cards (skills/SKILL_*.md) and keyword matching."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import log, SKILLS_DIR
from .parsing import parse_skill_card

# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Skill:
    skill_id:    str            # e.g. "PYTHON_DEV" (from SKILL_PYTHON_DEV.md)
    name:        str
    description: str
    keywords:    list[str]      # matched against the user's activity prompt
    stages:      list[str]      # pipeline stages this skill applies to
    content:     str            # markdown body injected into agent prompts
    path:        Path

    def as_dict(self) -> dict:
        return {
            "skill_id":    self.skill_id,
            "name":        self.name,
            "description": self.description,
            "keywords":    self.keywords,
            "stages":      self.stages,
        }


class SkillFactory:
    """
    Reads skills/SKILL_*.md cards (frontmatter: name / description / keywords /
    stages, body: guidelines) and matches them against the user's activity
    prompt by keyword. Matched skills are injected into agent system prompts
    via AgentFactory.spawn(skills=...) so each agent works with the specialist
    knowledge the request calls for.
    """

    ALL_STAGES = ["plan", "spec", "env", "execute", "test"]

    def __init__(self, skills_dir: Path = SKILLS_DIR) -> None:
        self.skills_dir = skills_dir
        self._skills: dict[str, Skill] = {}
        if skills_dir.exists():
            for md in sorted(skills_dir.glob("SKILL_*.md")):
                skill = self._parse(md)
                self._skills[skill.skill_id] = skill
        else:
            log.warning("Skills directory not found: %s — no skills loaded", skills_dir)

    # ── public ──────────────────────────────────────────────────────────────

    def available(self) -> list[Skill]:
        return list(self._skills.values())

    def match(self, activity: str, stage: str | None = None) -> list[Skill]:
        """Return skills whose keywords appear in the activity (word-boundary,
        case-insensitive), optionally filtered to those applying to `stage`."""
        matched = []
        for skill in self._skills.values():
            if stage and stage not in skill.stages:
                continue
            for kw in skill.keywords:
                if re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", activity, re.IGNORECASE):
                    matched.append(skill)
                    break
        return matched

    def register_card(self, skill_id: str, card: str) -> Path:
        """Write a new SKILL_<id>.md card to the skills dir and load it into
        the factory so subsequent runs can match it."""
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        skill_id = skill_id.removeprefix("SKILL_")
        path = self.skills_dir / f"SKILL_{skill_id}.md"
        n = 2
        while path.exists():
            path = self.skills_dir / f"SKILL_{skill_id}_{n}.md"
            n += 1
        path.write_text(card, encoding="utf-8")
        skill = self._parse(path)
        self._skills[skill.skill_id] = skill
        log.info("SkillFactory ▶ new skill registered: %s → %s", skill.skill_id, path.name)
        return path

    @staticmethod
    def render_context(skills: list[Skill]) -> str:
        """Format matched skills as a system-prompt section."""
        if not skills:
            return ""
        lines = [
            "## Assigned Skills",
            "",
            "The orchestrator has assigned you the following specialist skills "
            "based on the user's request. Apply their guidelines in your output.",
            "",
        ]
        for s in skills:
            lines.append(s.content.strip())
            lines.append("")
        return "\n".join(lines)

    # ── private ─────────────────────────────────────────────────────────────

    def _parse(self, md_path: Path) -> Skill:
        raw  = md_path.read_text(encoding="utf-8")
        meta: dict[str, str] = {}
        body = raw
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n", raw, re.DOTALL)
        if m:
            body = raw[m.end():]
            for line in m.group(1).splitlines():
                if ":" in line:
                    key, _, val = line.partition(":")
                    meta[key.strip().lower()] = val.strip()

        def _csv(key: str, default: list[str]) -> list[str]:
            val = meta.get(key, "")
            return [v.strip().lower() for v in val.split(",") if v.strip()] or default

        skill_id = md_path.stem.replace("SKILL_", "")
        return Skill(
            skill_id=skill_id,
            name=meta.get("name", skill_id.replace("_", " ").title()),
            description=meta.get("description", ""),
            keywords=_csv("keywords", []),
            stages=_csv("stages", list(self.ALL_STAGES)),
            content=body.strip(),
            path=md_path,
        )


