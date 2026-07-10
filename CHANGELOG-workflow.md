# Workflow change log — cross-document migrations

Template diffs in this repo don't capture the *cross-document* edits an adopting repo must make
(skill ↔ agent ↔ CLAUDE.md ↔ docs moves). This log records them, newest first: one entry per
workflow change, listing the edits to replay in a target repo. Companion to
[`ADOPTING.md`](ADOPTING.md) (the from-scratch runbook).

## 2026-07-10 — #175: the task-runner workflow (developed in KubeCoder, not yet synced here)

The workflow's execution core moved from LLM-driven skills into a script. Developed and validated
in `../KubeCoder` first; this repo's templates (`orchestrator/`, `project/`, `tools/`) sync after
the validation slices. An adopting repo replays:

**New pipeline.** `/triage` → `/plan-slice` → `/run-slice` + `tools/ai_workflow/task_runner.py`.
Canonical contract: the target repo's `docs/conventions/task-workflow.md` (folder layout, verdict
schema, bounded loops, escalation ladder, session mechanics).

**Skills.**
- `/write-slice`, `/major-change`, `/minor-change` — **deleted.** Triage's output folder *is* the
  slice (`slices/NNN_slug/slice.md`; triage allocates the number, opens the Kanban card, archives
  source cards, adds the README Pending line). The major/minor distinction no longer exists —
  planning is slice-level, execution is uniform per task.
- `/plan-slice` — **new**: interactive session that dispatches plan-writer/plan-reviewer to break a
  slice into 3–6 ordered, project-local tasks (10 the hard limit — the cap is per slice, not per
  project as pre-#175); verifies requirement fidelity itself; seeds `verification.json`. Task
  folders are `tasks/NN_slug/` — two-digit ids, visually distinct from three-digit slice numbers;
  a letter suffix (`04a`) inserts a task between existing ones mid-run.
- `/run-slice` — **rewritten thin**: preflight → launch the runner as a background shell → handle
  bail-outs (`bailout.json` reasons → `/write-task` + `--resume`, or defer to operator) →
  close-out. It never drives the dev loop.
- `/write-task` — **new**: author one task folder from a findings / missing-task write-up.
- Every skill carries a self-sufficient `description:` frontmatter (the root CLAUDE.md skill list
  is gone).

**Agents.** All dev agents rewritten to the thin shape (identity + output contract + bounds); the
output contract is literally the verdict-file schema. `code-tester` (Sonnet, fresh per round,
fixes-and-closes trivial issues) and `test-agent` (Sonnet, verification handovers) are new;
code-writer loses testing (keeps lint); reviewers describe problems and never prescribe fixes;
tester and code-reviewer receive `slice.md` and the task's `plan.md` as requirements — framed, not
raw: the tester mines the plan for coverage but never treats it as verified truth, the reviewer
judges outcomes rather than approach (plan deviation that meets requirements is not a finding;
missed planned edge behavior, broken pinned interfaces, and silent substitutions against
`slice.md` are), and both are scope-guarded (the slice spans tasks; only this task is under
test/review). The plan-writer's companion JSONs
(`requirements.json`, `file_map.json`, `test_plan.json`) are gone. The external-surface-probe /
substitution-test blocks are deleted in favor of a one-line grounded-claims rule. "Never work
around environmental problems — report `blocked` and stop" is now a bound in every agent.
`slice-verifier` (the `/run-slice` close-out check, on probation) keeps its evidence discipline
unchanged but is reframed for the new pipeline: the log is seeded by `/plan-slice`, not maintained
by an orchestrator, and its artifact blindness now names the current slice-folder files — it
deliberately does NOT read `slice.md`/`plan.md` (unlike the dev-loop tester/reviewer), staying the
one check with no shared framing.

**Tools.** `claude_session.py` gains `--cwd`, `--agent`, `--model`, quiet-by-default stderr
(`-v` restores) and a `run_claude()` library entry; `task_runner.py` is new (spawns fresh
`claude --agent` sessions with `FORCE_PROMPT_CACHING_5M=1`, cwd = the task's project);
`track_build.py` gains `--diagnose`. A session that ends without its verdict file or with
uncommitted changes gets **one resume-nudge** to finish its protocol; after that a missing verdict
is `blocked` and a dirty tree bails — the runner never `git add -A`s an agent's leftovers.
Runner output goes to `<slice>/log.txt`, never stdout (`-v` echoes it) — the orchestrator reads
exit code + `state.json`/`bailout.json`, so no progress stream ever floods its context. A crashed
run (host restart, quota stop, Ctrl-C) reattaches on `--resume`: `state.json` tracks the in-flight
session id and the worktree is preserved for it (consults and timed-out sessions never reattach).
The post-task checkpoint consult is unconditional (`--no-checkpoint` removed), and preflight fails
hard (exit 2, both in the runner and `scripts/preflight.py`) on a dirty working tree.

**CLAUDE.md set.**
- Root: stripped to a generic project brief (orchestrator guidance, skill list, agent management,
  deploy/cexec mechanics, Trello/notification detail all removed). Keep: slice-workflow pointer,
  specs layout, commit discipline + the push-green-light hard rule, design philosophy summary,
  conventions, issue-tracking pointer.
- Deploy happy path → `docs/operations/deploy-operations.md`; cexec was already in worker docs.
- Two-board Trello model + MCP ids + card conventions + push-notification rule →
  `~/.claude/CLAUDE.md` (host-global; cross-project by design). **Deferred:** the same content
  into the env-pod CLAUDE.md template (worker `internal/claudemd` — application code, needs a
  task).
- Subproject CLAUDE.mds: Design-philosophy → `docs/conventions/change-discipline.md` (now with the
  internal-vs-external boundary), Decision-making sections deleted, testing policy notes → each
  project's `docs/testing.md`, worker's VS-Code packaging → `worker/docs/vscode-extension.md`.
- "Never dismiss failures as flaky" lives in code-tester/test-agent definitions + a run-slice
  note, not CLAUDE.md.

**Docs.** `documentation-model.md`: diet rule ("state every fact exactly once; no recap
sentences; 100 lines is big") + primary doc keeper is `/plan-slice`.

**Known open items.** Skill-vs-agent-type naming collisions (`arch-design`, `update-docs` vs
`update-architecture`) unresolved; Trello **Accepted** list is vestigial (triage now archives
source cards directly); docs-diet splitting of oversized topic docs (`config-model.md` etc.) not
yet done; env-template CLAUDE.md addition deferred (above).
