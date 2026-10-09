# Committing into the spec tree

The spec repo is one working tree that every session in every environment commits into: the
loops and the sessions they dispatch, the operator's triage, plan-slice, run-slice and close-out
sessions, and the operator by hand. This page is the rule for a commit there. The lease and the
pre-commit guard, which keep a running phase's branch apart from everyone else's commits, are
[run-loop.md](run-loop.md) § The plan is the queue.

## Stage by name

Stage what you commit by name and commit by pathspec:
`git add -- <paths> && git commit -m "<message>" -- <paths>`. Never use `git add -A`, `git add .`
or `git commit -a`, which take every other session's work along. Files you create and the files of
the slice folder your session works for are committed this way. An uncommitted edit inside that
folder belongs to the same slice: a running slice's `plan.md` edits ride the driver's next stamp
by design.

## Another writer's edit in the same file

Staging by name keeps other files out of a commit. It does not keep out another writer's
uncommitted edit in a file you also commit. The operator ticks the lanes of `slices/DAG.md` by hand
and leaves them uncommitted, and a running slice's `plan.md` holds its agents' edits until the
driver's next stamp. So **a file outside the slice folder your session works for is snapshotted
before your first edit and committed through `tools/spec_commit.py`**. That covers
`slices/DAG.md`, the spec README, another slice's folder and a page of the spec repo:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/tools/spec_commit.py snap <path>...
# edit the files in place, then:
python3 ${CLAUDE_PLUGIN_ROOT}/tools/spec_commit.py commit -m "<message>" <path>@<snapshot>... [<path>...]
```

`snap` prints a `<path>@<snapshot>` token for each file and says which files already hold an edit
that is not yours. `commit` takes the tokens, plus plain paths for the files that are yours. It
commits your change since each snapshot, and each plain path whole. Every other uncommitted edit
stays where it was, in the working tree. The helper runs the spec repo's guard as `git commit`
does, and holds the tree's lease while it commits. An edit you made before the snapshot is part
of the snapshot and counts as not yours, so snapshot first.

**If your change touches the lines of the other edit, or the lines next to them, the helper
commits nothing** and shows both edits. Take your change back out of the file, so the file is as
you found it. Then defer the change the way your role defers what it cannot finish, and say why.

Two writers keep staging by name:

- `/dev:slice-dag` rewrites `slices/DAG.md` whole and carries the operator's ticks forward on
  purpose, so the ticks ride its commit.
- A phase whose `Target:` is the spec repo commits its work on its own branch. There, an edit left
  uncommitted in a file the branch changed blocks the driver's checkout back to the base.
