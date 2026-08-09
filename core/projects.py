# Auto-split from Orchestrator.py — part of the PrefectOS core package.
"""Per-request project directories + launched-app URL detection."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

from .config import log, PROJECTS_ROOT

# ─────────────────────────────────────────────────────────────────────────────

class ProjectManager:
    """
    Creates a unique project directory for every run.

    Layout:
        projects/
          20250628_140201_build_fastapi_task_manager/
            agent_registry.json      ← live-updated registry
            audit_log.json           ← final run summary
            plan.md
            spec.md
            requirements.txt
            setup_env.sh
            .venv/
            src/                     ← generated source files
    """

    def __init__(self, base: Path = PROJECTS_ROOT) -> None:
        self.base = base
        self.base.mkdir(parents=True, exist_ok=True)

    def create(self, activity: str) -> tuple[Path, str]:
        """
        Create a new project directory and return (project_dir, thread_id).
        Both are derived from the same timestamp + slug so they are
        identical and unique — LangGraph uses thread_id for checkpoint isolation.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug      = re.sub(r"[^a-z0-9]+", "_", activity.lower())[:40].strip("_")
        base_name = f"{timestamp}_{slug}"

        # Parallel runs started in the same second with similar activities
        # would slug to the same id — and the id is also the LangGraph
        # thread_id, so a collision would share checkpoints between runs.
        # mkdir(exist_ok=False) claims a name atomically; suffix and retry
        # on collision.
        self.base.mkdir(parents=True, exist_ok=True)
        name, n = base_name, 1
        while True:
            project_dir = self.base / name
            try:
                project_dir.mkdir(exist_ok=False)
                break
            except FileExistsError:
                n += 1
                name = f"{base_name}_{n}"

        # write a project manifest immediately
        manifest = {
            "project_id":  name,
            "activity":    activity,
            "created_at":  datetime.now().isoformat(timespec="seconds"),
            "status":      "running",
        }
        (project_dir / "project.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )

        log.info("New project: %s", project_dir)
        return project_dir, name   # name is also the thread_id

    def list_projects(self) -> list[dict]:
        """Return summary of all past projects."""
        projects = []
        for p in sorted(self.base.iterdir()):
            manifest_path = p / "project.json"
            if manifest_path.exists():
                projects.append(json.loads(manifest_path.read_text(encoding="utf-8")))
        return projects

    def complete(self, project_dir: Path) -> None:
        """Mark the project manifest as completed."""
        manifest_path = project_dir / "project.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["status"]       = "completed"
        manifest["completed_at"] = datetime.now().isoformat(timespec="seconds")
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")




import re as _re

def detect_server_url(project_dir: Path) -> str | None:
    """
    Scan generated source files for a server port and return
    'http://127.0.0.1:<port>' or None if not found.

    Checks (in order):
      1. app.run(port=XXXX) or app.run(host=..., port=XXXX)
      2. PORT = XXXX  /  port = XXXX  (module-level assignment)
      3. argparse default  --port XXXX
      4. uvicorn.run(..., port=XXXX)
      5. Falls back to 5000 if a Flask/FastAPI app.py exists with no port
    """
    candidates = ["app.py", "main.py", "run.py", "server.py", "wsgi.py"]
    port_patterns = [
        _re.compile(r'app\.run\s*\([^)]*port\s*=\s*(\d{4,5})'),
        _re.compile(r'uvicorn\.run\s*\([^)]*port\s*=\s*(\d{4,5})'),
        _re.compile(r'^\s*PORT\s*=\s*(\d{4,5})', _re.MULTILINE),
        _re.compile(r'^\s*port\s*=\s*(\d{4,5})', _re.MULTILINE),
        _re.compile(r'default\s*=\s*(\d{4,5}).*port', _re.IGNORECASE),
        _re.compile(r'--port[\'",\s]+(\d{4,5})'),
    ]

    for name in candidates:
        path = project_dir / name
        if not path.exists():
            # also check one level deep (e.g. src/app.py)
            hits = list(project_dir.rglob(name))
            if hits:
                path = hits[0]
            else:
                continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pat in port_patterns:
            m = pat.search(text)
            if m:
                return f"http://127.0.0.1:{m.group(1)}"
        # Flask/FastAPI present but no explicit port → default 5000/8000
        if "flask" in text.lower() or "Flask(" in text:
            return "http://127.0.0.1:5000"
        if "fastapi" in text.lower() or "FastAPI(" in text:
            return "http://127.0.0.1:8000"
    return None


