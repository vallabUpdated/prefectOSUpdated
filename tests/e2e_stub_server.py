"""Real server.py + dashboard, but with the chat model stubbed (no LLM calls).

Backend half of the parallel-run E2E test (see e2e_parallel_runs.py):

    python tests/e2e_stub_server.py      # serves the UI on port 5056
    python tests/e2e_parallel_runs.py    # drives it with Playwright

Run artifacts go to tests/.e2e_tmp/ so the repo's projects/ and memory/
directories stay clean.
"""
import sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(__file__).resolve().parent / ".e2e_tmp"
sys.path.insert(0, str(ROOT))

import Orchestrator as orch
from langchain_core.language_models import FakeListChatModel

CANNED = """# Plan

This is a deterministic stub response used by the parallel-run E2E test.

- Step 1: scaffold the project
- Step 2: implement the feature
- Step 3: add tests

requirements.txt:
```text
# no dependencies
```

### FILE: main.py
```python
def main():
    print("hello from the E2E stub")

if __name__ == "__main__":
    main()
```

### FILE: tests/test_main.py
```python
def test_main():
    assert True
```

### TEST REPORT
- Syntax check: all files compile
- Launch risk: none (plain CLI script, no server port)
"""


class SlowFakeChat(FakeListChatModel):
    """Fake chat model with latency so parallel runs genuinely overlap."""

    def _call(self, messages, stop=None, run_manager=None, **kwargs):
        time.sleep(0.8)
        return super()._call(messages, stop=stop, run_manager=run_manager, **kwargs)


def _fake_model(*args, **kwargs):
    return SlowFakeChat(responses=[CANNED])


# Stub both providers before any pipeline runs
orch.ChatAnthropic = _fake_model
orch.ChatOllama = _fake_model

# Redirect run artifacts + memory away from the repo's real directories
TEST_PROJECTS = TMP / "projects"
TEST_MEMORY = TMP / "memory"
TEST_PROJECTS.mkdir(parents=True, exist_ok=True)
TEST_MEMORY.mkdir(parents=True, exist_ok=True)
orch.PROJECTS_ROOT = TEST_PROJECTS
orch.MEMORY_ROOT = TEST_MEMORY

import server
server.PROJECTS_ROOT = TEST_PROJECTS

if __name__ == "__main__":
    print("Stub orchestrator UI -> http://127.0.0.1:5056")
    server.app.run(port=5056, debug=False, threaded=True)
