# The spec tree: committing into it, citing from it

The spec repo is one working tree that every session in every environment commits into: the
loops and the sessions they dispatch, the operator's triage, the plan-slice and run-slice
sessions, and the operator by hand. This page is the rule for a commit there, and for a
citation in what is committed. A phase whose
`Target:` is the spec repo — or any repo kc marks shared — never commits into that tree: it works
in a worktree of its own, and the driver merges it ([run-loop.md](run-loop.md) § The plan is the
queue).

## Stage by name

Stage what you commit by name and commit by pathspec:
`git add -- <paths> && git commit -m "<message>" -- <paths>`. Never use `git add -A`, `git add .`
or `git commit -a`, which take every other session's work along — every running slice's folder,
the operator's edits. Files you create and the files of the slice folder your session works for
are committed this way. An uncommitted edit inside that folder belongs to the same slice: a
running slice's `plan.md` edits ride the driver's next stamp by design.

## Another writer's edit in the same file

Staging by name keeps other files out of a commit, not another writer's uncommitted hunk in a
file you also commit — the README's Pending list as another session files a slice, a page
someone is still editing. That hunk rides your commit, and that is accepted: the shared tree's commits are not
pristine, and an edit committed by someone else is not lost. Commit your change; do not defer it
for that, and do not take the other edit back out.

## Citing a line

What you write into the spec tree is read later by another session: the next round, the wrap-up,
the run a week after the plan. By then other phases, other slices and the doc phase have moved the
lines you saw. A line number is stale on arrival, and the reader spends a search re-finding it or
acts on the wrong line (AIWF-82: a design doc that had drifted 170 lines under a criterion, a
close-out entry the doc phase had shifted, a ruling citing lines 257–279 of a 200-line file).

So a citation is the path and the line quoted, never its number:

- the path, then the line itself, enough of it to be unique in its file: a function's signature,
  a heading, the sentence that is wrong. `grep -n` finds it wherever it has moved;
- never `path:12` or `path:12-30`, nor "line 12 of";
- a command's output, quoted as evidence, keeps its numbers inside a fenced block: it is a
  record of what ran, not a pointer.

The CLIs of `close_out.py` and `asks.py` refuse a line cited by its number outside a fenced block
in an author's text. Every artifact another session reads is held to the rule, the plan and its
criteria, a review, a done-record and a design among them.
