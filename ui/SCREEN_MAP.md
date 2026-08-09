# PrefectOS UI — Screen Map for SME Daily Use

Personas: **Engineer** (starts runs), **Approver** (delivery head / senior eng),
**Auditor** (compliance, read-only), **Admin**.

## Screens

**1. Start Run** — `StartRun.jsx` ✅ built
Inputs: activity + template chips (bug fix / enhancement / compliance / new
module), run type (greenfield vs govern/enhance), codebase source (server
path | git URL+branch | previously-indexed RAG collection), client tag
(required — segregates every artifact), provider (per-run, constrained by
client policy), advanced: RAG toggle + backend, matched-skill exclude chips,
venv skip, read-only agent budget.

**2. Approval Gate** — `ApprovalGateV2.jsx` ✅ built
Edit/Diff tabs (LCS line diff of agent proposal vs approver edits),
approver identity on the gate and in the decision payload, mandatory
rejection reason (category + ≥10-char text, sealed as the terminal ledger
event), delegate-to-approver reassignment.

**3. Run Board** — exists (`RunBoard.jsx`); extend with client-tag filter
and "pending my approval" lens.

**4. Audit / Evidence** — filters (date, client, status, agent, event),
multi-select runs → evidence export pack (zip | summarized PDF, optional
"prepared for" watermark), one-click ledger verify per run.

**5. Regulatory Intelligence** — exists; add inputs: doc upload/URL +
jurisdiction + effective date + applicable clients (feeds `regulatory`
RAG collection); obligation-mapping accept/edit/reject reusing the gate
interaction.

**6. Skills** — card editor + approval gate for `skill_writer_node`
auto-generated skills (a skill silently changes all future runs — it is a
governance surface).

**7. Admin** — users & roles, per-provider keys, client workspaces +
provider policy, notification channels (email/Slack/Teams; reminder cadence,
escalation), retention.

## Server wiring the two new components need

- `POST /run` — accept `run_type, client_tag, provider, codebase{source,…},
  rag{enabled,backend}, skills_excluded, no_venv`. Map to existing pipeline
  inputs; `client_tag` → `project.json` + `run_started` ledger event.
- `GET /skills/match?activity=` — reuse `SkillFactory.match()` for the
  live matched-skills preview.
- `GET /rag/collections` — list `rag_index/*` (label, chunk count) for the
  "previously indexed" picker.
- `POST /approve/:runId` — accept `{decision, edited_content, decided_by,
  rejection, delegate_to}`. Seal `decided_by` in every gate ledger event;
  on reject, seal `run_rejected {category, reason, decided_by}` as the
  terminal event (closes the known rejected-run seal gap). `delegate`
  reassigns the pending gate and notifies.
- Session/auth — even simple email login; `currentUser` must be real for
  `decided_by` to mean anything to an auditor.

## Priority order

1. Auth + `decided_by` in ledger (converts "a human approved" → "who").
2. Client tag end-to-end (run → artifacts → evidence export).
3. Notifications (async approvals = daily-use viability).
4. Evidence export pack. 5. Regulatory inputs. 6. Skill gate.
