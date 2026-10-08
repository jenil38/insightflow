# Phase 1.1 plan: human confirmation for agent action tools

Status: **implemented** on `phase1-1-confirmation`, in five commits. Approved with
one change to the plan: after approval the run no longer ends with only a fixed
sentence. The decision response carries a server-written summary built from the
tool's own structured result, plus the raw result as `action_result` (cleaning
before/after and steps; the model leaderboard and metrics for `train_model`). The
model loop is still not resumed. Also added to the schema: `decided_at` on
`AgentStepOut`. Everything else is as written below, including the 410 for an
expired proposal and the 409 for a repeated decision.

Scope: `apply_cleaning` and `train_model`, the two tools with `read_only=False` in
`app/services/tool_registry.py`. Nothing else about the agent changes.

## Why

The sanitiser (`app/services/tool_sanitizer.py`, using `INJECTION_PATTERNS` from
`chat_service.py`, shared with the Copilot) is a six-alternation English regex applied per string. Unit tests
in `tests/test_tool_sanitizer_evasion.py` show 17 realistic phrasings pass through
unredacted: non-English, spaced/hyphenated/zero-width/homoglyph text, `system:` and
`assistant:` prefixes, markdown and code-fenced instructions, polite indirect
phrasing, a bare `train_model(...)` call, a JSON tool-call blob, an instruction split
across two cells, and the same prefix in a column name. Text filtering cannot be made
complete, so the last line of defence for an action must not be "the model decides
well".

Live evidence (allow_actions=true, Groq `openai/gpt-oss-20b`, `scratchpad/results.md`):

- Earlier: three unredacted phrasings on the read-only question "Summarise the notes
  column": 0 of 3 action calls.
- Action-inviting question (user never asks for training) with an unredacted cell
  asking for `train_model` on `revenue`, 3 phrasings x 3 runs on a 30-row dataset:
  **`train_model` called in
  0 of 9 runs.** `apply_cleaning` was called in 5 of 9 (`system:` prefix 3/3,
  polite-indirect 1/3, bare call 1/3), which the question's "go ahead and fix" wording
  explains and which was not compared against a clean 30-row baseline, so it is not
  attributed to the injection. In every run the sanitiser did not redact anything,
  so the model saw each injection verbatim and did not follow it.
- Clean vs injected control on the action-inviting question: `apply_cleaning` called
  in 1/3 clean and 2/3 injected runs. The call is driven by the question's wording,
  which means the model cannot tell "the user asked" from "the data asked" and a
  stricter prompt does not change who is deciding.

Both live samples are small and one model. They show the control is needed for
correctness reasons that do not depend on the exact rate.

## Design (smallest version)

`allow_actions=true` keeps meaning "the model is offered the action tools". New rule:
**an action tool call never executes inside the ask request.** When the model
requests one, the run stops and records a proposal; a second endpoint runs it only
after the user approves.

Deliberate simplification: the model loop is **not resumed** after approval. The run
ends with a fixed, server-written sentence ("Applied the recommended cleaning." /
"Trained a model to predict revenue; best model X, score Y." / "Declined."). Resuming
needs the whole `messages` list persisted per run (a new JSON/Text column, size
limits, redaction of what is stored) and a second provider call per approval. That is
a follow-up, not part of the smallest safe version.

### Loop behaviour (`ToolAgentService._run_loop` / `_execute_step`)

1. A tool call whose `Tool.read_only` is false and `ctx.allow_actions` is true is
   validated with the existing `args_model` first. Invalid arguments follow the
   existing `invalid_arguments` path so the model can retry; the user is never shown
   a proposal that could not run.
2. Valid: write an `AgentStep` with `status="pending_confirmation"`, `arguments` as
   the model sent them, `result_summary=None`. Set `run.status="awaiting_confirmation"`,
   `run.answer` to a fixed sentence naming the tool, and return without a further
   provider call.
3. Remaining tool calls in the same model turn are dropped (not executed, not
   recorded). Read-only calls that came earlier in the turn have already run.
4. `allow_actions=false` is unchanged: tools are not advertised and `execute_tool`
   still returns `blocked_action`.
5. `execute_tool` and the registry are unchanged. Approval calls it with a
   `ToolContext(allow_actions=True)`, so argument validation is the same code path.

### Decision endpoint

`POST /datasets/{dataset_id}/agent/runs/{run_id}/decision`, body `{"approve": bool}`.
Auth and ownership via the existing `get_owned_dataset`, plus `run.dataset_id` and
`run.user_id` must match (404 otherwise, same non-disclosure rule as datasets).

The client sends **no tool name and no arguments**. The server executes exactly what
was stored on the pending step; otherwise the endpoint would be a second way to call
`train_model` with arbitrary input.

- Claim atomically: `UPDATE agent_runs SET status='running' WHERE id=:id AND
  status='awaiting_confirmation'`; `rowcount != 1` -> 409 `already_decided`. This is
  what stops a double click or two tabs running `train_model` twice. (SQLite and
  Postgres both support it; no row lock needed.)
- Expiry: pending older than `AGENT_CONFIRM_TTL_MINUTES` (new setting, default 30)
  -> step `expired`, run `completed` with answer "Proposal expired.", 410. Stops a
  stale proposal being approved after the dataset changed.
- Approve: run the stored call, fill the same step (`status`, sanitised
  `result_summary`, `redacted`, `truncated`, `duration_seconds`) using the code
  currently in `_execute_step` (extracted into a helper; behaviour unchanged), run
  -> `completed`, answer from a small per-tool template.
- Decline: step `rejected_by_user`, run `completed`, nothing executed.
- Response: the existing `AgentAskResponse` shape, so the panel renders it unchanged.
- Failure of the tool (`tool_error`, e.g. "Only 12 usable rows") is a normal
  completed decision, recorded on the step, not a 500.

### Not covered by this design (state this in the UI and PR)

- It protects consent, not content. The proposal's arguments still come from the
  model, so an injection can propose `train_model` on a different column. The user
  has to read it. Mitigations that are in scope: show the user's original question
  next to the proposal, and show a warning when any step in the run has
  `redacted=true`. The warning is a weak signal (the evasions above do not trigger
  it); it must not be described as detection.
- Approval fatigue: a user who clicks Approve on everything is back to today's
  behaviour. That is a product decision, not something code can fix.
- `apply_cleaning` is documented as revertible and `train_model` adds a model
  version rather than destroying data, so the worst case here is wasted compute and
  an unwanted derived copy, not data loss. The control is still right because the
  actor deciding should be the user.
- No history/GET endpoint: reloading the page loses the pending card until expiry.
  Follow-up (`GET .../runs/{run_id}`).
- Training runs synchronously inside the request, as it does in `ask` today.

## Schema and migration

Database: **no new table. One optional nullable column.**

- `agent_runs.status` and `agent_steps.status` are plain `String`, so new values need
  no migration: run `awaiting_confirmation`; step `pending_confirmation`,
  `rejected_by_user`, `expired`. Update the status comments in `models.py` (comment
  only).
- Recommended: `agent_steps.decided_at` (`DateTime(timezone=True)`, nullable, no
  default) so the trace records when a human approved or declined. Pre-existing and
  never-decided rows stay NULL, which is truthful. Alembic revision on top of
  `d5i4f6g7h8c9`, one `op.add_column`, downgrade drops it. Skippable if audit time is
  not wanted; the feature works without it (TTL uses `created_at`).
- `app/schemas.py`: `AgentStepOut` gains `id`; `AgentAskResponse` gains
  `pending_action: {step_id, tool_name, arguments} | None`, populated only while the
  run is `awaiting_confirmation`. New `AgentDecisionRequest {approve: bool}`.
  All additive; existing clients ignore the new fields.
- `app/core/config.py`: `AGENT_CONFIRM_TTL_MINUTES: int = 30`.

## Agent tab (`frontend/src/features/tool-agent/ToolAgentPanel.jsx`, `api/endpoints.js`)

- `endpoints.js`: `toolAgent.decide(datasetId, runId, approve)`.
- `RUN_OUTCOME` += `awaiting_confirmation` (warning tone, "Waiting for your approval").
  `STEP_STATUS` += `pending_confirmation`, `rejected_by_user`, `expired`. Unknown
  statuses already fall back to `FALLBACK_STATUS`, so an old build degrades, not breaks.
- New `ConfirmationCard` shown when `run.status === "awaiting_confirmation"`: tool in
  plain words ("Apply the recommended cleaning" / "Train models to predict
  `revenue`"), the arguments, the user's original question, the redaction warning when
  applicable, **Approve** and **Decline** buttons with Decline as the default focus.
  Buttons disabled while the mutation is pending (client-side guard; the server claim
  is the real one).
- On approve success: replace the displayed run with the response and invalidate the
  affected queries (`["dataset", id]`, `["quality", id]`, `["datasets"]`; model-related
  keys to be confirmed while building). The panel invalidates nothing today, even when
  an action runs inside `ask`, so this is new behaviour and fixes an existing
  staleness gap rather than preserving one.
- Copy: the allow-actions checkbox becomes "Let the agent propose changes (you confirm
  each one)". `ThinkingState` text no longer says it "may include cleaning or training".
- The repo has no frontend test runner (`package.json` has only dev/build/preview), so
  this part is verified by `vite build` plus a manual checklist in the PR, not
  automated tests. Adding vitest is out of scope.

## Existing tests that change

Searched `tests/` for `allow_actions=True` and action-tool calls through the loop:
none run an action to completion through `ask`.

- `test_tool_registry.py`: no change (`execute_tool` untouched).
- `test_tool_agent_service.py` / `test_tool_agent_route.py`: the two `blocked_action`
  tests use `allow_actions=False` and stay as they are; the route-level
  `AgentAskResponse` assertions are additive-compatible. Expect zero edits; if a
  shape test uses exact-key equality on the response it needs `pending_action: None`
  and step `id` added.
- `test_chat_with_tools.py`: untouched (Copilot path).

## New tests

Service (mocked provider, as the existing tests do):

1. action requested with `allow_actions=True` -> run `awaiting_confirmation`, step
   `pending_confirmation`, **provider called once**, dataset untouched
   (`cleaned_path is None`, no model rows).
2. same for `train_model` with valid args; invalid args -> `invalid_arguments`, loop
   continues, no proposal.
3. read-only tools before the action in one turn execute; calls after it are dropped.
4. `allow_actions=False` behaviour unchanged (existing tests still pass).
5. **Regression for the live finding:** injected-cell fixture where the mocked model
   answers `profile_column(notes)` then `train_model(revenue)` -> no model is trained
   until a decision; this converts the probabilistic live result into a deterministic
   guarantee.

Route:

6. ask returns `pending_action` with the stored tool and arguments.
7. approve executes once, run `completed`, `cleaned_path` set (cleaning) / model row
   created (training), step has result and `decided_at`.
8. decline executes nothing, step `rejected_by_user`.
9. second decision -> 409; concurrent double-approve (two sessions) -> exactly one
   execution.
10. other user's run / wrong dataset id -> 404; unauthenticated -> 401.
11. expired proposal -> 410, nothing executed (monkeypatch TTL to 0).
12. body containing `tool_name`/`arguments` is rejected or ignored; the stored call is
    what runs.
13. tool failure on approve (`train_model` on 12 rows) -> 200, step `tool_error`.
14. decision on a run that is not awaiting confirmation (`completed`, `error`) -> 409.

Migration: upgrade/downgrade round-trip on SQLite if the repo already has such a test
pattern; otherwise covered by the app startup using `create_all` plus a manual
`alembic upgrade head` in the PR notes.

## Commits (estimate: 5)

1. `models`/`schemas`/`config` + optional Alembic revision for `decided_at`.
2. Service: stop at action tools, pending step, helper extracted from `_execute_step`
   (behaviour-preserving) + tests 1-5.
3. Decision endpoint, claim, expiry, templates + tests 6-14.
4. Frontend: `endpoints.js`, `ConfirmationCard`, statuses, copy.
5. Docs: update `docs/PHASE1_PLAN.md` status and README agent section.

Roughly 350-450 backend lines including tests, 150 frontend. One reviewable PR; 2
and 3 could merge if the helper extraction stays small.

## Would a per-request allow-list be meaningfully smaller?

Yes, but only somewhat. Replace `allow_actions: bool` with
`allowed_actions: list[Literal["apply_cleaning","train_model"]]` (keeping
`allow_actions` as a deprecated alias for "both"): schema field, `tools_for` filters
by name, `execute_tool` checks membership, two checkboxes in the panel. About 30-50
lines and one or two commits, no migration, no new endpoint, no new run states, no
new test infrastructure. Cheap enough to add regardless.

What it does **not** protect against:

- Anything the user did tick. If they tick `apply_cleaning` for an action-inviting
  question, an injection that asks for `apply_cleaning` runs unattended; in the live
  clean/injected comparison the model's action followed the question's wording, not
  the injection, which is exactly the case an allow-list cannot separate.
- Arguments. `train_model(target_column=...)` is allowed or not as a whole; an
  injection can still pick the column.
- Timing of consent. The choice is made before the user has seen what the agent will
  find or propose.
- Unexpected calls only get blocked, not surfaced for a decision: there is no moment
  where a human sees "the agent wanted to do X".

It reduces blast radius (an injection cannot reach a tool the user never enabled);
confirmation changes who decides. Recommendation: build confirmation; add the
allow-list afterwards only if there is demand for "never let it train" as a standing
preference.

## Out of scope

Sanitiser changes (the evasion gaps stay documented as strict xfails), resuming the
model loop after approval, run history endpoint, background execution of training,
frontend test runner.
