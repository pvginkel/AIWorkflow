#!/bin/sh
# aiworkflow spec-tree guard v1
#
# The spec repo's pre-commit hook, installed by the AIWorkflow dev plugin's
# preflight from plugins/dev/tools/spec-tree-guard.sh. Don't edit it in place:
# preflight replaces an older guard with its own by the version above, and
# leaves a same-or-newer one alone.
#
# The spec tree is one working tree that every session in every environment
# commits into. A run whose phase targets the spec repo checks its phase branch
# out there, and a commit anyone else makes meanwhile lands in that phase's
# work. So a commit on a `phase/*` branch is refused unless DEV_PHASE_BRANCH
# names that branch: the run loop sets it on the sessions it dispatches onto a
# branch of its own and on its own commits there. To commit on a phase branch
# by hand while recovering a stopped run, set it yourself:
# DEV_PHASE_BRANCH=<branch> git commit ...
#
# The hook never waits. A commit holds the index lock while its hooks run, so
# a hook that blocked would block the driver's own checkout back to the base.
# The refused session waits outside the hook instead, on the spec tree's lease.

branch=$(git symbolic-ref --quiet --short HEAD 2>/dev/null) || exit 0
case $branch in
    phase/*) ;;
    *) exit 0 ;;
esac
[ "${DEV_PHASE_BRANCH:-}" = "$branch" ] && exit 0

git_dir=$(git rev-parse --absolute-git-dir) || exit 1
lease=$git_dir/dev-spec-tree.lock
holder=$git_dir/dev-spec-tree.holder

# A running phase holds the lease exclusively. flock(1) says whether one does;
# where flock is missing or can't open the lease, the holder note says it.
held=
rc=1
if command -v flock >/dev/null 2>&1; then
    flock -n -E 75 -s "$lease" true 2>/dev/null
    rc=$?
fi
if [ "$rc" -eq 75 ]; then
    held=1
elif [ "$rc" -ne 0 ] && [ -s "$holder" ]; then
    held=1
fi

if [ -n "$held" ]; then
    note=$(sed 's/^/    /' "$holder" 2>/dev/null)
    cat >&2 <<EOF
spec-tree guard: commit refused. The spec tree is on $branch, the branch of
a running phase:
${note:-    (no holder note)}
A commit here lands in that phase's work. Don't commit on another branch,
check one out, or pass --no-verify.

Leave your edits where they are: when the phase merges, the run checks the
base back out and they go with it. Unstage anything you staged
(git restore --staged -- <paths>), because the phase's own commits would
take it. Then commit again under the spec tree's lease, as a background
command. It waits until the phase gives the tree back, which can take hours:

    flock -s '$lease' sh -c 'git add -- <paths> && git commit -m "<message>" -- <paths>'
EOF
    exit 1
fi

cat >&2 <<EOF
spec-tree guard: commit refused. The spec tree is on $branch, a slice run's
phase branch, and no run holds the tree: a run that stopped left it there.
Don't wait for it, don't commit on another branch, don't check one out, and
don't pass --no-verify. Tell the operator: putting the tree back on its base
is theirs.
EOF
exit 1
