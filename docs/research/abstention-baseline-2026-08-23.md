# Abstention baseline — code reviews, slices 144–170 (KubeCoderSpecs) + 006/007/008/009/013/015 (AnsibleSpecs)

Read-only measurement. Corpus: 32 slice directories, 179 `phases/P<id>/code_review_r<n>.md` files
(141 KubeCoderSpecs + 38 AnsibleSpecs). 29 root-level `plan_review_r*.md` files exist alongside them
but were excluded, as instructed (plan reviews, not code reviews).

## 1. The specified grep pattern and its raw count

Exact pattern (as given, run as one `grep -rniE` over all 179 `code_review_r*.md` files):

```
cannot (determine|verify|confirm|tell|check|assess|establish)
can.?t (determine|verify|confirm|tell)
could not (determine|verify|confirm|tell|check|assess|establish|run)
unable to (determine|verify|confirm|check|assess|run)
not (able|possible) to (verify|determine|confirm|check)
unverifiable
not verifiable
no way to (tell|verify|know|check)
insufficient (information|evidence|context)
did not verify
not verified
beyond (what|the scope) .*(can|could) (verify|check)
out of my reach
without (access|running)
```

**Raw match count: 10 lines**, all from two sub-patterns: `cannot (…|tell|check|…)` (9 hits) and
`no way to (…|know|…)` (1 hit). Every other sub-pattern (`can't`, `could not verify/run`, `unable
to`, `not able/possible to`, `unverifiable`, `insufficient …`, `did not verify`, `not verified`,
`beyond … can/could verify`, `out of my reach`, `without access/running`) returned **zero** hits
anywhere in the corpus.

That is a strikingly low count for 179 review files, so I broadened the sweep past the literal
pattern to sanity-check whether "abstention" language was simply phrased with different verbs.
`cannot X` alone appears 155 times in this corpus and `could not X` 27 times, but the verb that
follows is overwhelmingly **not** an epistemic one — `cannot be`, `cannot fail`, `cannot happen`,
`cannot catch`, `cannot work`, `cannot start`, `could not construct`, `could not compile`, etc. I
pulled every `cannot see / distinguish / answer / find / validate / test / know / reproduce` and
`could not construct / prove / turn / catch` occurrence (44 more candidates) and classified those
too, reported separately in §4 below — they are *not* part of the specified pattern's raw count,
but they change the read of the baseline meaningfully (three more soft abstentions turned up this
way; still zero hard ones).

## 2. Per-slice table (official pattern only)

| Slice | Review files | Raw matches | Abstention | Soft | Not-abstention |
|---|---:|---:|---:|---:|---:|
| 144_controller_lifecycle_correctness | 4 | 1 | 0 | 0 | 1 |
| 145_vscode_extension_attach_robustness | 4 | 1 | 0 | 1 | 0 |
| 146_worker_daemon_env_setup_robustness | 4 | 0 | 0 | 0 | 0 |
| 148_doc_accuracy_and_test_reliability | 8 | 0 | 0 | 0 | 0 |
| 149_contracts_package_and_drift_gate | 6 | 0 | 0 | 0 | 0 |
| 150_worker_tui_bubbletea_v2 | 3 | 0 | 0 | 0 | 0 |
| 151_recovery_mode_replaces_degrade_marker | 6 | 0 | 0 | 0 | 0 |
| 152_restart_replaces_sync | 10 | 3 | 0 | 0 | 3 |
| 153_config_faults_refuse_uniformly | 4 | 0 | 0 | 0 | 0 |
| 154_residual_sweep | 11 | 0 | 0 | 0 | 0 |
| 155_environment_state_visibility | 6 | 0 | 0 | 0 | 0 |
| 156_cexec_behaviour_manual_page | 2 | 0 | 0 | 0 | 0 |
| 157_kc_session_selector_ux | 3 | 0 | 0 | 0 | 0 |
| 158_problem_documents_and_refusal_rendering | 7 | 0 | 0 | 0 | 0 |
| 159_compose_time_config_faults | 6 | 1 | 0 | 0 | 1 |
| 160_daemon_lifecycle_and_timing | 5 | 0 | 0 | 0 | 0 |
| 161_cexec_diagnosability | 2 | 0 | 0 | 0 | 0 |
| 162_residual_sweep | 7 | 1 | 0 | 0 | 1 |
| 163_planned_eviction_recovery | 1 | 0 | 0 | 0 | 0 |
| 164_pushed_environment_state | 6 | 0 | 0 | 0 | 0 |
| 165_cross_repo_sidecar_and_ssh_prereqs | 7 | 0 | 0 | 0 | 0 |
| 166_home_overlay_mountpoints | 1 | 0 | 0 | 0 | 0 |
| 167_doc_scope_mechanism_only | 6 | 0 | 0 | 0 | 0 |
| 168_env_issue_detail_budget | 4 | 0 | 0 | 0 | 0 |
| 169_in_pod_surface | 5 | 0 | 0 | 0 | 0 |
| 170_ssh_transport | 13 | 0 | 0 | 0 | 0 |
| 006_charts_repo_and_charts_home (Ansible) | 6 | 1 | 0 | 0 | 1 |
| 007_argocd_tools_presync_hook (Ansible) | 13 | 1 | 0 | 0 | 1 |
| 008_helmcharts_argo_coexistence (Ansible) | 4 | 0 | 0 | 0 | 0 |
| 009_argocd_standup (Ansible) | 8 | 0 | 0 | 0 | 0 |
| 013_iac_pipeline_restructure (Ansible) | 5 | 0 | 0 | 0 | 0 |
| 015_webhook_relay (Ansible) | 2 | 1 | 0 | 0 | 1 |
| **Total** | **179** | **10** | **0** | **1** | **9** |

**Slices with ≥1 abstention (hard): 0 / 32.**
**Slices with ≥1 soft abstention: 1 / 32** (145_vscode_extension_attach_robustness).

## 3. Findings count (mechanical, approximate)

Not cleanly countable — heading style is not standardized across slices/rounds. Three different
mechanical proxies, all over the same 179 files:

- `## Findings` section headers: **162** (roughly one per file, but not exactly — some rounds fold
  findings under `## Round-1 findings` / `## Checked and clear` instead, some readiness-only rounds
  have none).
- Finding-level headings matching `F<n>` or `<n>. <title>` under `###`/`####`: **278**.
- Lines carrying an explicit `Severity:`/`impact:` + `Major|Minor|Critical|Blocking|Advisory` marker
  (the review's own per-finding metadata idiom): **120**.

These three disagree because reviews mix a `### F1 — title` style, a `### 1. Minor — title` style,
inline bold-sentence findings with no heading at all, and severity metadata expressed both as a
heading suffix and as a separate bullet line. Treat 120–280 as the honest range for "number of
distinct findings across the corpus," not a single number.

## 4. Supplementary broadened sweep (outside the specified pattern)

Verbs that showed up attached to `cannot`/`could not` but weren't in the specified verb list:
`see` (13×), `distinguish` (3×), `answer` (2×), `find` (2×), `validate` (1×), `test` (1×), `know`
(1×), `reproduce` (1×); `could not construct` (3×), `could not prove` (1×), `could not turn` (1×),
`could not catch` (1×), `could not see` (2×), `could not read` (1×), `could not provide` (1×, a
quote), `could not go` (1×), `could not compile` (1×). I read context for all 44 of these too.
Verdict: **41 of 44 are not-abstention** — overwhelmingly the reviewer stating what a *gate*, a
*test*, an *assertion*, or *a reader* cannot see/distinguish/find, as evidence inside a confident,
well-anchored finding (often backed by an executed mutation or a live repro) — not the reviewer's
own inability to judge. **3 are soft abstentions**, all following the same shape as the one found
in the official pattern: the reviewer tries to construct/reproduce something, fails, says so
plainly, and then reasons past it to a graded verdict rather than leaving the question open:

- 150_worker_tui_bubbletea_v2, P1 r1 — "I could not construct a failing input" → Minor/advisory,
  "confidence high on the mechanism, low on product impact."
- 156_cexec_behaviour_manual_page, P1 r1, finding F6 — "reports a measurement I cannot reproduce"
  → reviewer reproduces the qualitative claim a different way and concludes "the design doc's
  framing is accurate."
- 006_charts_repo_and_charts_home, P4 r3 — "I could not construct a realistic abort inside the
  window — a git that cannot answer, or a chart helm cannot read, both fail … before the snapshot
  is taken" → recorded as a residual-risk advisory note, not left open.

Adding these: **4 soft abstentions total, 0 hard, across 4/32 slices** (145, 150, 156, 006). No
instance anywhere in the corpus — official pattern or broadened sweep — was a bare "I cannot
determine/verify this" left without reasoning or a rendered verdict.

## 5. Examples

### Soft abstentions (4 of 4 found — fewer than the requested up to 10 exist in this corpus)

1. **145_vscode_extension_attach_robustness, P4, round 1** (official pattern, `cannot check`):
   > "…both kinds are `shellPath`/`shellArgs` process terminals … not pty terminals, so I have no
   > grounded path by which their pid read rejects or answers `undefined`. That is why this is
   > advisory rather than a defect — but it is now an invariant the extension depends on and
   > cannot check, and the rewritten test comment … quietly drops the old … claim that used to
   > cover it. Worth a live-verification line rather than a code change."

2. **006_charts_repo_and_charts_home, P4, round 3** (broadened sweep, `could not construct` /
   `cannot answer`):
   > "I could not construct a realistic abort inside the window — a git that cannot answer, or a
   > chart `helm` cannot read, both fail at `:42` or `:45`, before the snapshot is taken."

3. **156_cexec_behaviour_manual_page, P1, round 1, finding F6** (broadened sweep, `cannot
   reproduce`):
   > "F6 — close-out B4's first bullet reports a measurement I cannot reproduce, and the doc it
   > calls stale is right … With a descendant that really does ignore the hangup and hold the
   > slave, the bound is reached in full … The design doc's framing is accurate."

4. **150_worker_tui_bubbletea_v2, P1, round 1** (broadened sweep, `could not construct`):
   > "**Why Minor and advisory rather than Major.** I could not construct a failing input. The
   > module contains no `runtime.GOMAXPROCS`/`runtime.NumCPU` call (grep clean), the daemons are
   > IO-bound socket servers, and Go's position is that the new default is the correction. …
   > Confidence: high on the mechanism, low on product impact."

### Not-abstention (boundary examples)

1. **006_charts_repo_and_charts_home, P4, round 2** — reviewer *verifies* by demonstration, then
   states a gate's blind spot as the finding itself, not as their own uncertainty:
   > "Demonstrated, not argued. I deleted the five-line skip block, restoring the round-1 behaviour
   > verbatim, and ran the full test verb — … The gate cannot tell the fixed script from the
   > broken one."

2. **152_restart_replaces_sync, P1, round 1** — "cannot tell" describes what a *reader* of the
   shipped comments would conclude, i.e. it is the finding (a clarity defect), not the reviewer
   reporting their own inability to judge:
   > "V20's bar is that a reader cannot tell the modes or the fingerprint ever existed."

3. **168_env_issue_detail_budget, P1, round 1, finding F1 (Major, blocking, confidence high)** —
   "cannot see" describes the *tests'* blind spot, offered as evidence for a confidently-rendered
   verdict, not a hedge:
   > "The phase's own tests cannot see it because both of them pin the split on non-escaping
   > payloads. One blocking finding, one advisory."

## 6. Read of the baseline

Abstention is essentially not a thing in this corpus, on either count. Zero true abstentions ("I
cannot determine/verify this" left standing with no verdict) turned up anywhere in 179 reviews
across two very different projects — not on the literal 13-pattern regex, and not on a hand-broadened
sweep of every `cannot X` / `could not X` construction in the corpus (68 total occurrences of the bare
words, only ~54 of which were even epistemic-shaped enough to warrant reading in context). What the
grep mostly surfaces instead is a stock reviewer idiom: "the gate/assertion/test/reader cannot
see/tell/distinguish/find X" — which is the reviewer stating a *finding* (a coverage gap, a doc that
misleads a reader, a test that can't catch a mutation) with high confidence, frequently backed by an
executed mutation, repro, or live check right in the same paragraph. That idiom is the opposite of
abstention: it is how this reviewer role expresses "I checked, and here specifically is where the
system's own checking breaks down." The handful of genuine soft-abstentions that do exist (4, out of
179 files, spread over 4 slices) share one shape: the reviewer attempts a concrete falsification —
construct a failing input, reproduce a measurement, build a realistic abort scenario — reports failing
to do so, and then still renders a graded verdict (Minor/advisory, confidence explicitly split between
"mechanism" and "product impact," or a recommendation for live verification) rather than stopping at
"I don't know." There's no visible clustering by phase kind or project: the four soft instances land on
a VS Code extension host-behavior question (145), a Go runtime/scheduler question (150), a bash
snapshot-window race (006, Ansible), and a timing measurement in a doc-page phase (156) — i.e.
wherever the honest answer requires either live production behavior or a specific runtime/environment
the reviewer doesn't have on hand, rather than clustering on any one role or repo. Given the review
role's default posture (mutate, repro, quote the exact line, verify independently rather than trust
the done-record) is visibly dominant across almost all 179 files, this reads less like reviewers
avoiding hard calls and more like a role that is simply well-evidenced enough that it rarely needs to
hedge.
