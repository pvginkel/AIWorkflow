# Authoring guide — keeping the plugin's artifacts lean and drift-free

Rules for writing and maintaining the plugin's artifacts: agent definitions, skills, the contract
docs, and the `.aiworkflowrc` each project provides. They exist to prevent duplication, keep
context windows clean, and make drift easy to spot. The mechanics of adopting the plugin are in
[`ADOPTING.md`](ADOPTING.md); the project contract is
[`plugins/dev/docs/project-contract.md`](../plugins/dev/docs/project-contract.md).

## Single source of truth (the no-duplication rule)

**Every claim about how things work lives in exactly one place.** Before adding content to a file,
search for anything that already says it. If it exists: delete the new copy and reference the
existing location, promote the content to a broader scope if it should apply more widely, or
reconcile the drift if the two say subtly different things.

Duplication is a drift trap first, a token cost second: two copies diverge, and agents reading
different copies behave differently. This is why the plugin references generic concerns (issue
tracker, notifications, the spec repo, the testing strategy) rather than restating them — the
concrete facts live once, in the project's `.aiworkflowrc`/manifest or the host
`~/.claude/CLAUDE.md`.

## Agent definitions — thin: identity + output contract + bounds

Each `agents/<name>.md` contains only what makes *this* agent different:

1. **Frontmatter** — `name` and `description` (**both required**; see below), plus `model` if the
   role pins one.
2. **Role** — one paragraph: what the agent is and what it produces.
3. **Output contract** — where it writes its artifact and the exact verdict-JSON shape it must end
   with (the runner reads that verdict; a missing/invalid one is a protocol failure).
4. **Bounds** — the rules that make it different: adversarial sweep, "describe the problem never the
   fix", "run don't read", commit discipline, "never work around an environmental problem → report
   `blocked`".

It must **not** contain project architecture rules (those load from the component's `CLAUDE.md`/docs
at dispatch — the agent reads them, it doesn't repeat them), "read CLAUDE.md first" (it's automatic),
or generic filler.

## `description` is mandatory — an agent without one silently isn't registered

**Every agent needs a `description`.** Claude Code only registers an agent that has one — an agent
with just a `name` is silently dropped and **cannot be dispatched at all**, not even by name. (Learned
the hard way: dev agents once shipped with no description on the theory that name-dispatched agents
don't need one, and *every* run silently fell back to `general-purpose`. The files were present and
valid — they just weren't registered.) The official plugin docs don't call this out; treat a missing
`description` as the first thing to check when an agent "isn't there."

The description is also what an LLM reads to *choose* an agent, so make it accurate: for a
conditionally-dispatched agent (e.g. `arch-design`) say **when to use it**; for one always dispatched
by name (`code-writer`, `code-reviewer`, …) a one-line role statement is enough — but it is still
mandatory.

Installed in the plugin, agents resolve as `dev:<name>` everywhere (and `kc session
create-headless --agent dev:<name>` resolves them headlessly). Project-local `.claude/agents/` still
merge hierarchically from the session cwd up to the git root, if a project adds its own.

## Skills — the orchestration sequence, not the agents' content

A skill is a task-specific workflow the user triggers by name. It contains: what it does (one
paragraph), the numbered procedure, real shell invocations (reference plugin files via
`${CLAUDE_PLUGIN_ROOT}/...`), and the decision points where it stops and asks. Frontmatter carries
`name` (mandatory, kebab-case, **identical to the directory name**), `description`, and an
`argument-hint`; `allowed-tools` and `model` are available when a skill needs them.

One skill per directory: `plugins/dev/skills/<name>/SKILL.md`. The file name is always `SKILL.md` —
the directory is what names the skill. Supporting files (scripts, references) may sit beside it.
The legacy `commands/<name>.md` layout still loads, but Claude Code marks it deprecated internally;
new work goes in `skills/`.

It must **not** restate an agent's behavior (the agent definition owns that), restate `CLAUDE.md`,
or carry generic Claude Code etiquette. Think of a skill as a script that choreographs agents, not
a place to explain what they do.

`description` is the **trigger**, not just a label: it is always in context, and Claude reads it to
decide whether to invoke the skill on its own. Say when to use the skill, not merely what it is. To
keep one operator-only (no autonomous invocation), set `disable-model-invocation: true`.

## `CLAUDE.md` discipline (the project side)

The plugin can't ship a `CLAUDE.md` (it is project/user memory, discovered by walking the repo). A
project provides one, and the rules for keeping it disciplined live with the rest of the CLAUDE.md
contract, in
[`plugins/dev/docs/project-contract.md`](../plugins/dev/docs/project-contract.md#keeping-claudemd-disciplined)
— **not here**. They have to ship *inside* the plugin: `/dev:onboard` applies them in repos that have
this guide nowhere on disk, and a plugin cannot read its own marketplace's docs.

## Keep the set honest

Periodically (or whenever you feel friction): read each artifact end to end and delete anything
stale, restated elsewhere, or that you don't remember adding. Scan agent definitions for sentences
that restate `CLAUDE.md` or the workflow contract; scan skills for sentences describing what an
agent *does* (vs. when it runs). If two files reference the same rule, pick one and delete the other.
The goal isn't minimalism — it's that every claim lives in exactly one place, so a reader (human or
agent) always knows where to look and never reconciles conflicting versions.
