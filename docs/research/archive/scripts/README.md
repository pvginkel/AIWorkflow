# Working scripts of the reads

The throwaway scripts behind reads that never got a readout tool in `docs/research/tools/`.
They are kept as they ran, together with the small data they collected, and they are not
maintained. They ran in the AIWorkflow KubeCoder environment, so their paths point at spec-repo
and project clones under `/work/scratch/` (clone them again to re-run; the paths name each
repo), at `/work/AIWorkflow/plugins/dev/tools` for `slice_cost.py` and `turn_profile.py`, and at
transcripts under `~/.claude/projects/`.

| Folder | Read |
|---|---|
| `model-effort-2026-10-03/` | `docs/research/model-effort-read-2026-10-03.md` |
| `gate-timing-2026-10-24/` | Where PilotApp slice 008's time went: gate and test runs, gaps and phase sizes. `hits.py` asks whether the writer's own green run would have answered each phase gate, which is AIWF-93's reuse. |
| `session-size-2026-10-27/` | `docs/research/session-size-read-2026-10-27.md` |
| `phase-count-2026-10-27/` | `docs/research/phase-count-read-2026-10-27.md` |
| `triage-answers-2026-10-30/` | `docs/research/triage-answers-read-2026-10-30.md`. `extract.py` pulls the `/dev:triage` runs since 0.9.60 from the transcripts into `runs.json` and per-run timelines (not kept: the operator's turns verbatim), `classify.py` holds the hand classification (`classification.json`), `stats.py` the message counts and latencies, `complaints.py` the fleet-wide scan for remarks about triage. |
