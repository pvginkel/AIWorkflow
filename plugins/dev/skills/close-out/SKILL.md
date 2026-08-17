---
name: close-out
description: Work through a slice's close-out report (close-out.md) with the operator — present it, take the operator's dispositions in their own words, and execute them (card / fix now / fold into a slice / close / defer). Invoke it yourself whenever the operator opens, discusses, pastes from, or wants to process a slice's close-out.md — the operator will not necessarily name this skill.
argument-hint: "[slice number or slice dir]"
---

# Close-out

Execute the operator's dispositions on one slice's `close-out.md` — the report every plan and
run agent wrote its out-of-scope observations to (`${CLAUDE_PLUGIN_ROOT}/docs/close-out.md` is
what the report is; `${CLAUDE_PLUGIN_ROOT}/docs/close-out-template.md` its shape). The operator
reads and decides; this session presents, records, files, and edits. `<spec-repo>` is the path
in your `CLAUDE.md`'s `Spec repo:` line; boards, lists, owner tags, and notification wiring come
from your host convention (`~/.claude/CLAUDE.md`).

## Procedure

1. **Locate the report.** The argument names it (a slice number or a slice dir); without one,
   the newest `slices/**/close-out.md` under `<spec-repo>` that still has an entry with a blank
   `Disposition:` line (the file's head comment shows one as the shape — that is not an entry).
   Say which report you opened.
2. **Present it — ask nothing yet.** Read the whole file. Show the `Run:` header, the Summary,
   every `Focus:` line, and every live entry as `id — headline` with its `Consequence:` line
   under it — that line is what the operator triages on; struck entries as their headline only,
   marked as such. The operator reads; you wait.
3. **Take dispositions.** The operator writes them into the file under the entries, or says them
   in chat ("card B1, close B6, fold S1 into 009"). Chat dispositions you write into the file on
   the entry's `Disposition:` line **in the operator's words** — never paraphrased, never
   completed. Free form; the usual vocabulary is `card [board]` · `fix now` ·
   `fold into <slice>` · `close` · `defer`. A blanket ruling ("close the rest", "I'm not
   progressing anything else") is a `close` on every entry still blank, each carrying those
   words. What you then did goes after the operator's words on the same line, after ` — `: the
   card id and URL, the commit, the slice folded into.
4. **Execute each disposition:**
   - `card [board]` — one tracker card per entry (the named board, else the intake queue per
     the host convention): title = the entry's headline, body = the entry verbatim + its
     `Provenance:` line + the report's path.
   - `fix now` — do it here only if the project's `CLAUDE.md` classes the change as ad hoc
     work; otherwise say so and offer `fold into`.
   - `fold into <slice>` — append the entry verbatim as an ask to that slice's `slice.md` under
     `slices/backlog/`; a slice that does not exist yet becomes a `/dev:triage` item instead.
   - `close` — strike the entry's heading (`### ~~B6 — …~~ — closed by the operator, <date>`;
     the operator's reason, if given, stays on the `Disposition:` line, not in the heading).
   - `defer` — leave it; it is `/dev:triage`'s.
5. **Commit and finish.** Commit the report (staged by name — the spec repo is a shared tree).
   When no blank `Disposition:` remains, archive the slice's close-out card
   (`[NNN] close-out: …`). Report short: dispositions by kind, cards filed, anything owed.

## Bounds

- Never edit an operator's words, and never re-derive an entry's claim — the run's records are
  in the slice folder if the operator wants to look, and `/dev:triage` grounds what it takes on.
- When a disposition asks about the claim ("this says we built the wrong thing, right?"), answer
  from the entry's own body and `Provenance:` — quote what supports or fails to support the
  operator's reading, and say plainly when the entry does not settle it. Agreeing is not an
  answer; neither is re-deriving.
- Present, record, file, edit — no planning, no design here; that is `/dev:triage` →
  `/dev:plan-slice`.
- Steps that do not apply are skipped silently: an operator who wrote every disposition into
  the file gets step 4 straight away.
