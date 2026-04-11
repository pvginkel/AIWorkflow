# Run Slice

Run the implementation workflow for a slice. Argument: the slice number (e.g., `001`).

## What this skill does

You are the orchestrator. You drive per-subproject dev agents through the slice workflow by invoking `claude` via the session manager script. The session manager handles environment setup, session tracking, and state persistence automatically.

**Session manager:** All `claude` invocations go through `python3 {{ session_manager_path }}`. No need to manually `unset CLAUDECODE` or `cd` into project directories.

**Prompt delivery:** Prompts are delivered via file or stdin — never as inline shell arguments (to avoid shell escaping issues with backticks, quotes, and special characters).

```bash
# Preferred for long/complex prompts: write a file, pass it with --prompt-file
python3 {{ session_manager_path }} start --project {{ subproject }} --timeout 7200 --prompt-file /tmp/prompt.txt --response-file /tmp/response.txt

# Fine for short prompts: heredoc via stdin
python3 {{ session_manager_path }} start --project {{ subproject }} --timeout 7200 <<'EOF'
Please read the brief and come back with informed questions.
EOF
```

**Response handling:** The session manager streams progress to stderr and writes the agent's final response to stdout (or to a file via `--response-file`). Use `--response-file` when running in the background so you can read the response after completion.

**Push notifications:** Use `python3 {{ notification_script }} --title "Slice <NUMBER>" "<message>"` to notify the user. Send a notification when:
- The slice completes successfully.
- The slice is blocked and needs user attention (agent failure, test failures requiring user input, missing work reported by a downstream agent, significant API contract gaps).

Do **not** notify for routine progress. Only notify when the user needs to act or when the workflow has reached its end.

## Slice file formats

Slices are authored by the `/write-slice` skill. The files the runner reads:

- **`acceptance_criteria.json`** — testable conditions with `id` (prefixed by subproject — e.g., `BE-`/`FE-`/`PO-`/`RE-`), `area`, `description`, `status` (`pending`/`passed`/`failed`).
- **`api_contract.json`** — structured API spec with `endpoints` (id, method, path, status_codes, key fields, `verified` flag), `schema_changes`, and `removals`.
- **Per-subproject briefs** (`{{ subproject }}_brief.md`) — scoped task descriptions for each dev agent.
- **`overview.md`** — what the slice delivers, dependencies, scope.
- **`ux_design.md`** (optional) — UX guidance for slices with non-trivial UI work.

When sending briefs to agents, reference the relevant acceptance criteria and API contract IDs so the agent knows exactly which conditions and endpoints its work must satisfy.

## Procedure

### Step 0: Identify the slice and verify test infrastructure

Resolve the argument to the slice directory under `{{ specs_repo_path }}/slices/`. For example, argument `001` resolves to `{{ specs_repo_path }}/slices/001_<name>/`.

Read all documents in the slice directory. Determine which agents need to run based on which brief files exist.

**Pre-flight: verify test infrastructure.** Before starting any agent, confirm tests can actually run. Code that hasn't been tested is not done.

{% block preflight_checks %}
{# Project-specific pre-flight commands. These should verify that:
   - The test suite can collect tests without environment errors
   - External services (DB, queues, storage) are reachable
   - Any special startup requirements are met
   Replace with the actual commands for your stack.
#}
Run minimal commands that confirm the test harness is healthy before dispatching any dev agent. Examples:

```bash
# <subproject> tests: verify test collection works
cd {{ project_root }}/{{ subproject }} && {{ test_command }} --collect-only 2>&1 | tail -5
```

If any pre-flight check fails: notify the user and **stop immediately**. Do not start any dev agent.
{% endblock %}

### Step 0b: Pre-flight review with user

After reading all slice documents and passing infrastructure checks, present a pre-flight summary to the user before starting any agent work.

1. **Work rundown.** Summarize what will run: which agents, a brief description of what each will deliver.
2. **High-impact decisions.** Flag decisions with significant architectural or data-model implications. Skip this section if the slice is primarily low-impact CRUD/UI work.
3. **Clarifications.** If anything is ambiguous, ask the user now — before any agent starts.
4. **Notify and wait.** Send a push notification and wait for the user to respond before proceeding. Do not start Step 1 until the user has confirmed.

### Step 0c: UX design (if applicable)

Check whether `ux_design.md` already exists in the slice directory.

- **If it exists:** it was authored as part of the slice. No action needed — provide it to the relevant dev agent in their step below.
- **If it doesn't exist and the slice has frontend or portal work:** assess whether the slice warrants dedicated UX guidance (new screens, novel interactions, complex state management, ambiguous UI behavior). If so, generate one using Codex:
  ```bash
  python3 {{ project_root }}/tools/ai_workflow/codex_exec.py --prompt-file /tmp/ux_prompt.txt --response-file {{ specs_repo_path }}/slices/<SLICE_DIR>/ux_design.md
  ```
  The first line of the prompt must be `$frontend-ux-designer`. Follow the project's UX prompt conventions (what you're designing, what to read, current state, problems, constraints, deliverable).

### Step 1: Run the "leading" subproject

{% block leading_subproject %}
{# In most monorepos, one subproject leads the others (e.g., backend defines
   the API, then frontend/portal consume it). Pick the leading subproject
   and dispatch it first. The dispatch pattern is the same regardless of
   which subproject leads.
#}
If the slice has a leading subproject (e.g., a backend that defines APIs for consumers), run it first. Otherwise, dispatch the dev agents in any order.
{% endblock %}

Start a new session in the leading subproject:

```bash
python3 {{ session_manager_path }} start --project {{ subproject }} --timeout 7200 --response-file /tmp/{{ subproject }}_response.txt <<'EOF'
Please read {{ specs_repo_path }}/slices/<SLICE_DIR>/{{ subproject }}_brief.md and come back with informed questions.
EOF
```

Check the exit code:
- `0` — success, read the response from `/tmp/{{ subproject }}_response.txt`.
- `1` — error, notify the user and stop.
- `2` — timeout, check `.claude/sessions/{{ subproject }}.json`. If the last invocation has `duration_ms > 0`, the agent was working — resume with a nudge. If `duration_ms == 0` or state is stale, restart.

Answer all informed questions yourself based on your knowledge of the project documentation. Be thorough and precise — you know this project deeply.

**Do not prescribe implementation details.** Your answers describe **what** needs to happen and **why**, not **how**. Do not include code snippets or specific implementation patterns. The agent reads the codebase, writes the plan, and designs the implementation — that's the whole point of the workflow.

**Log the Q&A exchange** to `{{ specs_repo_path }}/slices/<SLICE_DIR>/qa_log.md`:

```markdown
## {{ subproject | title }} — Round N

Q: <agent's question>
A: <your answer>

Q: <agent's question>
A: <your answer>
```

**Log deferred items.** If any Q&A exchange surfaces work that is out of scope for the current slice but needs future attention, log it to your issue log immediately — don't rely on the QA log alone.

**Decide whether to allow follow-up questions.** Use your judgment:
- If the questions show the agent has a good understanding and your answers are just clarifications, skip the follow-up round.
- If the questions reveal significant gaps or confusion, allow a follow-up round by ending your answer with: *"Please come back with follow-up questions. Do not start the implementation if you don't have any."*

**When ready to execute**, write the final answers plus execution instruction to a prompt file, then resume:

```bash
python3 {{ session_manager_path }} resume --project {{ subproject }} --timeout 7200 --prompt-file /tmp/{{ subproject }}_execute.txt
```

**Pick the workflow for this agent** based on the brief plus what you learned from Q&A:

- **Minor workflow** (`docs/minor_change_workflow.md`) — pattern-following work with existing precedent, no new architectural decisions, narrow diff (roughly ≤ ~200 lines / ≤ ~5 files), executable without a written plan.
- **Major workflow** (`docs/major_change_workflow.md`) — anything that introduces new patterns, crosses module boundaries, or involves design decisions worth capturing in a written plan. Default to major when in doubt.

Asymmetry across subprojects is expected — e.g., backend major, portal minor when portal mirrors a sibling change.

The prompt file should end with: *"Use the workflow in docs/<chosen_workflow>.md to implement the brief. Commit ALL your work when done — including any plan files, feature docs, or other generated artifacts. Run 'git status' before your final commit to make sure nothing is left uncommitted."*

Wait for the agent to complete. Do not poll for progress — the session manager streams progress to stderr. On success, finish the session:

```bash
python3 {{ session_manager_path }} finish --project {{ subproject }}
```

### Step 2: Regenerate derived artifacts (if applicable)

{% block regen_step %}
{# If your monorepo has artifacts generated from the leading subproject
   (e.g., OpenAPI client for frontend/portal), regenerate them here. Commit
   the regenerated files before dispatching consumer subprojects so they
   work against the updated spec.

   Delete this whole block if nothing downstream depends on generated
   artifacts.
#}
If downstream subprojects depend on artifacts generated from the leading subproject (e.g., an OpenAPI client), regenerate them now and commit the result before dispatching the consumer agents.
{% endblock %}

### Step 3: Review the API contract (if applicable)

Read the generated OpenAPI spec (or equivalent) and compare it against `api_contract.json`. For each endpoint entry:

1. Verify the endpoint exists in the spec (method + path).
2. Check that `key_request_fields` and `key_response_fields` appear in the schemas.
3. Confirm the `status_codes` are documented.
4. Update the `verified` field to `true` or `false`.

For `schema_changes`, verify the change is reflected. For `removals`, verify the **absence** of the removed item. Write the updated `api_contract.json` back to the slice directory.

If any endpoint has `verified: false`, assess whether it's a significant gap or a minor difference. Significant gaps → notify the user and stop. Minor differences are fine.

### Step 4+: Run the consumer subprojects

For each remaining subproject with a brief file, run `claude` using the same pattern as Step 1 (ask questions, log Q&A, pick workflow, execute, finish). The sequence is the same; only the project name changes.

**UX design:** If `ux_design.md` exists, include it in the initial prompt: ask the agent to read it alongside the brief.

**Check for testing infrastructure gaps.** If the agent's questions reveal that it needs testing infrastructure from the leading subproject (e.g., a seeding endpoint for Playwright), **stop the agent immediately**. Send the leading subproject's agent to implement the missing infrastructure first, then resume. Testing infrastructure gaps are blocking.

### Step N: Run the full test suite

After all agents have completed, run the full test suite to verify everything is green:

```bash
{{ full_suite_command }}
```

Run this in the background (`run_in_background: true`). The background task mechanism notifies you automatically when it completes — do **not** poll with sleep+check commands.

**If all tests pass:** proceed to acceptance-criteria verification.

**If any tests fail:**

1. Read the test output for failures.
2. For each failure, identify which agent owns it based on where the failing test lives.
3. **Diagnose before fixing.** Understand *why* the test fails before writing a fix. When a consumer subproject's tests fail after a leading-subproject change, the cause is almost always test infrastructure referencing the old behavior — look at how passing tests start their services, not how create_app() is structured.
4. Send the owning agent back to fix it. Tell them explicitly: *"The test suite was green before your changes. These failures are regressions caused by your code changes (all unpushed commits). Find and fix the root cause."* Include the full failure output and your diagnosis.
5. Re-run the suite. Repeat until green or blocked.
6. **Maximum 3 fix rounds per agent.** If an agent cannot get its tests green after 3 attempts, notify the user and stop — the slice may be mis-classified or too large.

### Step N+1: Verify acceptance criteria

Walk through `{{ specs_repo_path }}/slices/<SLICE_DIR>/acceptance_criteria.json`:

1. For each criterion, determine whether it is satisfied (passing test, code inspection, API spec inspection).
2. Update the `status` field: `"passed"` or `"failed"`.
3. Write the updated JSON back.

For any `"failed"` criteria, decide whether they are blocking (core functionality missing → send the owning agent back) or non-blocking (minor gap → log to the issue tracker and continue).

### Step N+2: Review QA log and update issue tracker

Review `{{ specs_repo_path }}/slices/<SLICE_DIR>/qa_log.md` end-to-end. Look for:

- **Deferred work** — features or improvements that were explicitly deferred.
- **Known limitations** — architectural shortcuts that will need revisiting.
- **Contract/spec drift** — cases where implementation diverged from the original brief.
- **Design decisions with future implications.**

For each, create an entry in your issue log.

### Step N+3: Report results

Summarize what happened: which agents ran, any issues, API contract review result, test suite result, acceptance criteria result. Move the slice from "Pending" to "Completed" in `{{ specs_repo_path }}/README.md`.

Notify the user that the slice is complete (or partially complete if there are outstanding items).

## Important notes

- **The test suite is green before every slice.** This is a hard assumption. If tests fail after a slice run, the slice caused the regression. Never dismiss failures as "pre-existing" or "flaky."
- **No backwards compatibility.** When answering agent questions, never suggest backwards-compatible workarounds. Prefer clean breaking changes.
- **Answer questions yourself.** You have full access to all project documentation. Do not ask the user to answer the dev agent's questions.
- **Do not put code in briefs or answers.** Describe *what* and *why*, not *how*.
- **Stop on failure.** If any agent fails, report and stop. Do not proceed to the next step.
- **Do not run agents in parallel.** Subprojects may have dependencies — the leading subproject must complete before consumers can start.
- **Run subprojects sequentially**, not in parallel. Resource constraints during test suites make parallel runs unreliable.
- **Timeouts.** Dev agents may take a long time, especially running test suites. Default timeout is 2 hours per invocation. On timeout, check the session state file at `.claude/sessions/<project>.json` before deciding to resume or restart.
- **Session state files** live at `.claude/sessions/<project>.json`. You can read them at any time to check invocation history and session IDs.
- **Agents must always use one of the change workflows.** If an agent can't make progress using the workflow, the slice is too large — report to the user to discuss splitting it.
