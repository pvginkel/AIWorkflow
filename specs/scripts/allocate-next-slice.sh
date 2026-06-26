#!/usr/bin/env bash
#
# Allocate the next {{ project_short }} slice number — concurrency-safe.
#
# Lives in the SPECS repo ({{ specs_repo_path }}/scripts/), because the slice
# numbering space it guards lives there too (slices/). /write-slice calls it as
# {{ specs_repo_path }}/scripts/allocate-next-slice.sh.
#
# Prints a zero-padded 3-digit slice number (e.g. 043) to stdout and nothing else,
# so callers can capture it directly:
#
#     N=$(scripts/allocate-next-slice.sh)
#
# Why a counter and not "scan slices/ for the max": several /write-slice sessions
# run concurrently against this one working tree. flock serializes them, and the
# reservation is persisted to slices/.next-slice *before* the slice directory
# exists, so a parallel session sees the bump immediately (a dir scan can't — the
# other session's folder isn't created yet).
#
# slices/.next-slice and slices/.slice-alloc.lock are host-local coordination
# (git-ignored, not spec artifacts). .next-slice self-seeds from the highest NNN_
# on disk if missing, and the disk-max floor below self-heals any drift — so
# deleting it is safe. A burned number (allocate, then abandon the slice) leaves a
# harmless gap; that is the accepted cost of collision-safety.
#
# Follow-up work to an existing slice does NOT use this helper — pick a letter
# suffix tied to that slice (e.g. 087b) instead.
set -euo pipefail

slices_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../slices" && pwd)"

# Critical section: held until the script exits (fd 9 closes on exit).
exec 9>"$slices_dir/.slice-alloc.lock"
flock 9

n=$(( 10#$(cat "$slices_dir/.next-slice" 2>/dev/null || echo 0) ))

# Floor at one past the highest NNN_ directory anywhere under slices/ (active,
# completed/, deferred/, cancelled/). Self-heals if the counter ever drifts low.
hi=$(find "$slices_dir" -maxdepth 2 -type d -printf '%f\n' 2>/dev/null \
      | sed -nE 's/^([0-9]{3})_.*/\1/p' | sort -n | tail -1)
hi=$(( 10#${hi:-0} + 1 ))
(( n >= hi )) || n=$hi

# Never hand out a number already taken on disk.
while find "$slices_dir" -maxdepth 2 -type d -name "$(printf '%03d' "$n")_*" | grep -q .; do
  n=$((n + 1))
done

printf '%03d\n' "$((n + 1))" > "$slices_dir/.next-slice"   # persist the reservation
printf '%03d\n' "$n"
