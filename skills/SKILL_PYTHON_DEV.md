---
name: Python Development
description: Idiomatic, production-quality Python — project layout, typing, packaging, framework conventions.
keywords: python, flask, fastapi, django, pandas, numpy, streamlit, jupyter, asyncio, sqlalchemy, pydantic, pip, venv, cli, script
stages: plan, spec, env, execute, test
---

# Skill: Python Development

You are proficient in modern Python (3.11+). Apply these guidelines whenever the task involves Python code.

## Code Style
- Follow PEP 8; use type hints on all public function signatures.
- Prefer f-strings, `pathlib.Path` over `os.path`, and `dataclasses` / `pydantic` models over bare dicts.
- Use context managers for files, DB connections, and locks.
- Handle errors explicitly — never use a bare `except:`; catch the narrowest exception that makes sense.

## Project Layout
- Keep an importable package layout: `app.py` / `main.py` entrypoint, modules split by responsibility (`db.py`, `models.py`, `routes/`).
- Configuration comes from environment variables via `python-dotenv`; never hard-code secrets.
- Pin dependencies with compatible-release ranges in `requirements.txt` (e.g. `flask>=3.0,<4.0`).

## Frameworks
- **Flask**: use the app-factory pattern for anything beyond a single file; blueprints per feature area; `flask-cors` only when a separate frontend needs it.
- **FastAPI**: pydantic models for request/response schemas; dependency injection via `Depends`; run with `uvicorn`.
- **CLI tools**: use `argparse` (stdlib-only) or `typer`; always provide `--help` text.

## Quality Bar
- Every module gets a short docstring stating its purpose.
- Fail fast on missing configuration at startup, not deep inside a request handler.
- Log with the `logging` module, not `print`, in anything long-running.
