"""Real server.py + dashboard, with the document-processing model stubbed.

Lets the loan/account suites run end to end — agents, phases, per-document
progress, tokens — without calling a real LLM, so the orchestrator's view of a
document job can be exercised for free.

    python tests/e2e_docjob_server.py     # serves the UI on port 5057

Sample documents are written to tests/.e2e_tmp/docs and run output to
tests/.e2e_tmp/out, so the repo's projects/ and memory/ stay clean.
"""
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(__file__).resolve().parent / ".e2e_tmp"
sys.path.insert(0, str(ROOT))

import Orchestrator as orch
import loan_processing as loan

# A reply that satisfies both agent roles: a plan, and an assessment.
CANNED = """```json
{
  "documents": [
    {"name": "payslip_march.txt", "kind": "income", "action": "process"},
    {"name": "bank_statement.txt", "kind": "bank_statement", "action": "process"},
    {"name": "id_card.txt", "kind": "identity", "action": "process"},
    {"name": "employment_letter.txt", "kind": "employment", "action": "process"}
  ],
  "decision": "APPROVE",
  "summary": "Deterministic stub reply used by the document-job E2E harness.",
  "findings": [
    {"criterion": "Income verified", "status": "pass", "evidence": "payslip_march.txt"},
    {"criterion": "Identity verified", "status": "pass", "evidence": "id_card.txt"}
  ],
  "risks": [],
  "conditions": []
}
```"""


class StubLLM:
    """Stands in for ChatAnthropic — same call shape, no network, real latency."""

    def __init__(self, delay: float = 3.0) -> None:
        self._delay = delay

    def invoke(self, messages):                                    # noqa: D102
        time.sleep(self._delay)
        return SimpleNamespace(
            content=CANNED,
            usage_metadata={"input_tokens": 812, "output_tokens": 464},
            response_metadata={},
        )


loan._make_llm = lambda max_tokens: StubLLM()

# Keep pipeline runs stub-driven too, so both kinds of run can be tried here.
try:
    from langchain_core.language_models import FakeListChatModel
    orch.ChatAnthropic = lambda *a, **k: FakeListChatModel(responses=["# Plan\n\nstub"])
    orch.ChatOllama = orch.ChatAnthropic
except Exception:                                                  # noqa: BLE001
    pass

TEST_PROJECTS = TMP / "projects"
TEST_MEMORY = TMP / "memory"
DOCS = TMP / "docs"
OUT = TMP / "out"
for d in (TEST_PROJECTS, TEST_MEMORY, DOCS, OUT):
    d.mkdir(parents=True, exist_ok=True)

SAMPLES = {
    "payslip_march.txt": "EMPLOYER: Northwind Ltd\nEMPLOYEE: A. Kumar\n"
                         "GROSS PAY: 145000\nNET PAY: 121500\nPERIOD: March 2026\n",
    "bank_statement.txt": "ACCOUNT: 0092841\nOPENING: 240000\nCLOSING: 318400\n"
                          "CREDITS: 121500, 40000\nDEBITS: 12000, 31100\n",
    "id_card.txt": "NAME: A. Kumar\nID: XXXX-4417\nDOB: 1989-04-02\n"
                   "ADDRESS: 14 Nehru Road, Pune\n",
    "employment_letter.txt": "Confirming A. Kumar has been employed with Northwind "
                             "Ltd since 2019 as a Senior Analyst.\n",
}
for name, text in SAMPLES.items():
    (DOCS / name).write_text(text, encoding="utf-8")

orch.PROJECTS_ROOT = TEST_PROJECTS
orch.MEMORY_ROOT = TEST_MEMORY

import server
server.PROJECTS_ROOT = TEST_PROJECTS

if __name__ == "__main__":
    print("Stub document-processing UI -> http://127.0.0.1:5057")
    print(f"  sample documents: {DOCS}")
    print(f"  output folder:    {OUT}")
    server.app.run(port=5057, debug=False, threaded=True)
