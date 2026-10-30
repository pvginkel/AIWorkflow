# Committing into the spec tree

The spec repo is one working tree that every session in every environment commits into: the
loops and the sessions they dispatch, the operator's triage, the plan-slice and run-slice
sessions, and the operator by hand. This page is the rule for a commit there. A phase whose
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
