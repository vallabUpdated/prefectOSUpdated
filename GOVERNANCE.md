# Agent Governance Layer — Feature Summary

Operon-class agentic governance, native to PrefectOS. One module
(`agent_governance.py`), one policy file (`agent_policy.json`), one API
(`governance_api.py`, mounted at /governance).

| Capability | What it does | Where |
|---|---|---|
| Deny-by-default policy | Every agent tool/model call authorized BEFORE execution against an allowlist (action + resource globs). Unknown agent or unlisted action = denied. No LLM in the enforcement path. | `PolicyEngine`, `agent_policy.json` |
| Human-in-the-loop gates | L2 agents and `always_gate` actions wait for a named human; the approval seals the approver's identity. Wired into email intake: the "Process documents" click IS the gate approval. | `Governor.authorize` → `record_outcome`, `email_review.process_intake` |
| Earned autonomy | L1 observe → L2 approve-all → L3 notify → L4 autonomous. Promotion after clean approved streaks; ANY incident demotes to L1 instantly and blocks re-promotion until ops clears it. | `AutonomyTracker` |
| Signed receipts | Every allow/gate/deny/outcome hash-chained AND HMAC-signed (`PREFECTOS_SIGNING_KEY`). Tampering breaks the chain; forgery fails the signature. `--verify` / GET /governance/verify. | `SignedReceiptLedger` |
| Shadow mode (CCTV) | `AGENT_GOV_MODE=shadow`: everything evaluated + receipted, nothing blocked or gated. Would-be denials receipted as `shadow_denied`. Two weeks of shadow writes the enforcement policy. | `Governor(shadow=True)`, `--shadow-report` |
| Circuit breaker | Freeze one agent or ALL, instantly; outranks even shadow mode; the freeze and release are themselves receipted. | `Governor.freeze/unfreeze`, `--freeze`, POST /governance/freeze |
| Policy rehearsal | Replay past receipts against a proposed policy: "this change would have blocked N calls — here they are." Evidence-based rule editing. | `replay_policy`, `--replay`, POST /governance/replay |
| Observability API | Agent roster with levels/streaks/frozen state, latest receipts, verification, shadow census. | `governance_api.py` → /governance/* |

Config: `PREFECTOS_SIGNING_KEY` (required, env only), `AGENT_GOV_MODE`
(enforce|shadow), `AGENT_POLICY`, `AGENT_GOV_STATE`. Tests:
`tests/test_agent_governance.py` (18) + governed-intake E2E
(`e2e_test_governed_intake.py`, recorded).
