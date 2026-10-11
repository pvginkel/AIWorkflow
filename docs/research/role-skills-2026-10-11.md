---
issue: AIWF-56
---

# Reaching a skill from a run-loop role — the options

**Ruled 2026-10-11:** D1 (a), D2 executor + fix rounds + reviewer + plan-writer + plan-reviewer,
D3 the backticked name in the plan's text, D4 left to `/dev:plan-slice` — every recommendation.
Built as dev 0.9.92.

**Recommendation.** Keep the trim, and have the driver hand a role the file. When the text a
dispatch is built from names a skill as `<plugin>:<skill>`, the driver resolves the name against
the installed plugins and adds one line to the dispatch: this session has no Skill tool, and the
skill is this file, to read before the work it governs. A plan names a skill as it does today.
The phase's reviewer is pointed at the same file as its writer. It costs about 40 tokens on the
dispatches that need it, and nothing on the others. It is about 40 lines of driver code. Giving
the Skill tool back costs ≈ 5 k tokens on every turn of every role. Agent-definition preloading
does not work for a role session (witnessed below).

## 1. What happens today

**The trim.** Every role is spawned `-e CLAUDE_CODE_DISABLE_BUNDLED_SKILLS=1
--disable-slash-commands` (`SPAWN_ENV`, `SPAWN_FLAGS` in `run_loop.py`;
[agent-dispatch.md](../../plugins/dev/docs/agent-dispatch.md) § Spawning). It shipped in 0.9.6 and
0.9.8. The premise was "a headless role invokes no skill": two invocations in 809 corpus sessions
(`turns-plan.md` § T3). At the time, `--disable-slash-commands` measured −3,233 tokens on
`claude -p`, 1.2 k of it bundled skills and the rest the dev and kubecoder skill descriptions. The
docs say what the flag does: "Disable all skills and commands for this session".

**The premise has changed.** The operator's standing rule is that "a style guide or how-to for
whoever writes the next file reaches agents through a skill" (`~/.claude/CLAUDE.md`).
`kubecoder:jenkins-pipelines` is the first of these skills (ruled 2026-09-23,
AnsibleSpecs `reviews/2026-09-jenkinsfile-review/plan.md` § 4). ARCH-20 asks for a second, the
producer manual. An interactive session picks such a skill up from its listing by the
description's trigger ("Use whenever writing, editing or reviewing a Jenkinsfile"). A role sees no
listing and has no Skill tool.

**Where skills are named.** Plan text, written in the interactive `/dev:plan-slice` session, which
does see the listing. No dispatch the plugin writes names one. A gitblit search over every Specs
repo for `kubecoder:jenkins-pipelines` gives four plans and one slice:

- Ansible 046's `plan.md` (":52 — load it for any Jenkinsfile or vars work") and its `slice.md`;
- Ansible 056's `plan.md`;
- Ansible 037's backlog `plan.md`;
- DHCPApp 001's `plan.md` (":162 — Load the `kubecoder:jenkins-pipelines` skill before writing the
  file").

No other skill is named for loading. The other plan hits are slices that edit a skill.

**What roles do instead.** They search the disk, a turn or two each. In the logs: Ansible 056 P3
code-writer "Locate the jenkins-pipelines skill"; 046 P2 "Locate the jenkins-pipelines skill on
disk"; DHCPApp 001 P4 "Inspect Dnsmasq repo state and locate jenkins skill"; the 056 plan-writer r1
"Locate jenkins-pipelines skill". No reviewer turns up in those logs: the reviewer of a Jenkinsfile
phase is not told about the guide, and does not go looking for it. The search can also go wrong.
This pod's cache holds seven kubecoder versions side by side: 0.8.4, 0.10.0, 0.10.6, 0.10.9,
0.10.10, 0.10.11 and 0.10.12. `ls` puts 0.8.4 last, and 0.8.4 has no `jenkins-pipelines`. The
skill's text changed between 0.10.9 and 0.10.11 (different md5). A role that takes "the newest
directory" by sort order can read a stale guide, or none.

**What is installed.** `~/.claude/plugins/installed_plugins.json` is the record. It maps
`kubecoder@kubecoder-config` to `installPath`
`…/cache/kubecoder-config/kubecoder/0.10.12` (and `dev@aiworkflow` to its own). A skill is
`<installPath>/skills/<name>/SKILL.md`. None of the five kubecoder skills uses
`${CLAUDE_PLUGIN_ROOT}` or `${CLAUDE_SKILL_DIR}`, so reading the file raw loses nothing today.

**Witnessed (2026-10-11, Claude Code 2.1.296, Haiku through `kc session create-headless`, cwd a
scratch repo).** Each session was asked, without tools, for its tools, its skill listing, and
whether the text of `jenkins-pipelines` was in its context. `skilltest` is a project agent with
`skills: [kubecoder:jenkins-pipelines]`, and `skilltest2` the same with the bare name.

| # | spawn | Skill tool | listing | skill text in context |
|---|---|---|---|---|
| v1 | no trim | yes | 38 skills | no (listing line only) |
| v2 | bundled off | yes | 25 (dev 8, kubecoder 5, other plugins 12) | no |
| v3 | `--disable-slash-commands` | **no** | none | no |
| v4 | the role's: both, `--agent dev:code-writer` | **no** | none | no |
| v5 | both, `--agent skilltest` | no | none | **no**: preload ignored |
| v6 | bundled off, `--agent skilltest` (slash commands on) | yes | 25 | **no**: preload ignored for a main-thread agent |
| v7 | `--disable-slash-commands`; the session dispatches `skilltest` as a sub-agent | n/a | n/a | **no** |
| v8 | slash commands on; sub-agent `skilltest` | n/a | n/a | **yes**: quoted `## The hard rules`, FILE-1–3 |
| v9 | slash commands on; sub-agent `skilltest2` (bare name) | n/a | n/a | **yes** |

So `--disable-slash-commands` alone removes the Skill tool and the listing, and the bundled-skills
variable only shortens the listing. `skills:` preloading reaches a sub-agent, and only when the
session that dispatches it has slash commands on. It never reaches an `--agent` main-thread
session, which is what every role is.

**What the listing costs today.** Two sessions as a code-writer is spawned (bundled off,
`--strict-mcp-config`, `--agent dev:code-writer`, "Reply OK") differ only in
`--disable-slash-commands`. The first turn's input was **30,470 with the listing and 25,498
without: −4,972 tokens**, about 20 % of the role's prefix. That is up from August's ≈ 2.0 k
because more plugins are installed now (anthropic-skills 9, cowork-plugin-management 2,
plugin-authoring). It is a Haiku count. The Opus count was not taken; it should be within a few
percent.

## 2. The options

**(a) The driver points at the file.** It scans the phase's own section in `plan.md` (the
executor and fix rounds read it through the digest, the reviewer reads it directly), plus the
plan's rulings, for `` `<plugin>:<skill>` ``. It resolves each name through
`installed_plugins.json`. Each name that resolves adds one line to the executor, fix-round and
reviewer dispatches of that phase: "This session has no Skill tool; the skills this phase names
are files — read each before the work it governs: `kubecoder:jenkins-pipelines` →
`<path>`." The plan loop does the same from `slice.md` and `plan.md` for the plan-writer and the
plan-reviewer.

- Cost: about 40 tokens per such dispatch, plus one Read whose content then rides the session.
  A Skill call would load the same content.
- Code: about 40 lines (the resolver, plus the line in both loops) and about six tests.
- Drift: the path is resolved at dispatch time from the installed record, so it always points
  at the version an interactive session would load. A name that resolves to nothing is said
  once in the line ("names no installed skill"), so the role does not go searching.
- Portable: the plugin knows no skill. It resolves whatever a project's plan names, and
  excludes its own `dev:` namespace.

**(a′) The same, inlined.** The driver pastes SKILL.md into the dispatch instead of its path.
That saves the Read turn and costs ≈ 3 k tokens per dispatch for `jenkins-pipelines` (12 KB),
more for a larger skill (`kubecoder:onboard` is 136 KB). It is wasted on a fix round that never
touches the governed file.

**(b) Give the Skill tool back.** Drop `--disable-slash-commands`, everywhere or only on the
dispatches whose phase names a skill. Everywhere costs ≈ 5 k tokens on every turn of every role,
and the 0.9.8 trim is undone. Only where named, it costs ≈ 5 k per turn on those sessions and
needs the same scan as (a), so (a) gets the same result for 40 tokens. A narrower listing, through
`skillOverrides` set to off per skill, needs `--settings`, which `kc session create-headless`
does not pass. That would be a KubeCoder change for no gain over (a).

**(c) `skills:` in the agent definitions.** It does not work for a role, as v5 and v6 show. It
would also write host skill names into the plugin's agents, which breaks the portability rule.
This one is closed.

**(d) A `Skills:` line beside `Target:`.** It is explicit and parseable, and the plan-reviewer
could check that the skill exists. But it adds a plan-format rule, a parser, and a template line,
for what the backticked name in the phase text already says. If the operator wants plans to name
skills reliably, the cheaper move is one sentence in `/dev:plan-slice` and the plan template:
"when the work touches a convention a skill carries, name the skill in the phase as
`<plugin>:<skill>`".

**(e) A skill catalog in every dispatch.** This recovers the description trigger for a phase
whose plan did not name the skill. The driver lists name, trigger sentence and path for a set of
skills in every code-writer and reviewer dispatch: about 500 tokens for the five kubecoder skills
(1,892 characters of descriptions). The set has to come from somewhere the plugin does not own:
an `.aiworkflowrc` list per project, which is duplicated across every project that writes
Jenkinsfiles, or "every installed plugin but dev", which brings back anthropic-skills' docx and
pptx. Worth it only if (a) leaves a gap that shows up in a run.

**(f) A pointer in the project's `CLAUDE.md`, or a path written into the plan.** A CLAUDE.md
pointer is the per-file pointer the operator's rule replaces with a skill. A path written at plan
time pins a cache version, and the old directory stays on disk, so it silently goes stale after
the next plugin update. The unversioned marketplace clone
(`~/.claude/plugins/marketplaces/kubecoder-config/kubecoder/skills/…`) avoids the version, but it
puts a host path into a committed spec file. Neither is recommended.

## 3. The build, if (a) is taken

- `run_loop.py`: `resolve_skills(text) -> [(name, path | None)]`, reading `installed_plugins.json`
  (the user-scope entry for `<plugin>@*`) and matching only the backticked `<plugin>:<skill>` form,
  `dev` excluded. A `SKILL_LINE` is rendered into the executor, fix-round and reviewer prompts
  beside `CLOSE_OUT_LINE` when the phase names any skill. `plan_loop.py` uses the same function
  over `slice.md` and `plan.md`. A missing `installed_plugins.json` means no line and one log line.
- `agent-dispatch.md` § Spawning: one sentence after the trim saying how a named skill still
  reaches a role. Plan template and `/dev:plan-slice`: the sentence from (d).
- Unchanged: `SPAWN_FLAGS`, `SPAWN_ENV`, the agents, and every role's prefix.
- First readout: the next Jenkinsfile phase. Look for no "locate the skill" turn in `log.txt`,
  and for the reviewer citing guide rule ids.

## 4. For the operator to rule

- **D1 — the mechanism.** (a) the driver points at the file (recommended) · (a′) the driver
  inlines it · (b) the Skill tool back, where named or everywhere.
- **D2 — who gets it.** The named phase's executor, fix rounds and reviewer, plus the plan-writer
  and the plan-reviewer (recommended) · executors only.
- **D3 — how a plan names a skill.** A backticked `<plugin>:<skill>` in the phase text, as
  today, plus the one sentence in `/dev:plan-slice` and the template (recommended) · a `Skills:`
  line beside `Target:` (d).
- **D4 — the unnamed case.** Leave it to `/dev:plan-slice`, which sees the listing (recommended)
  · a catalog in every dispatch (e), from a list in `.aiworkflowrc` or from every installed
  plugin but dev.
