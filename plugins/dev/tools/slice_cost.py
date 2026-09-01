#!/usr/bin/env python3
"""Price one loop-run slice from its own run records — no hand-editing.

The run loop (state.json) and the plan loop (plan_state.json) record every
session they drive: role, phase, and the Claude Code transcript path. This
tool reads those records, scans each transcript (plus its sub-agent
transcripts), and prices the whole slice: totals, per-role and per-phase
breakdowns, a per-session table. Attribution is mechanical — the state files
*are* the session list — rather than inferred from what a transcript happens
to mention, which is what the measurement it replaces had to do.

Counted per transcript, deduplicated by message id (the stream-json format
logs each assistant message several times with identical usage):

  * the interactive orchestrator sessions that launched the loops (recorded
    from CLAUDE_CODE_SESSION_ID at loop start)
  * every driven session in the two histories (writer/reviewer/consult/
    test/doc rounds; a resumed or nudged session appears once)
  * their sub-agents (<transcript-dir>/<session>/subagents/agent-*.jsonl)

Missing transcript files (cleaned ~/.claude, another machine) and unknown
model ids are reported as warnings, never silently priced at zero without
notice.

The report also carries a `turns` block: every transcript is replayed a
second time by turn_profile.py, which puts each turn in one class (what it
did) and counts the read ops chained inside one Bash command, and the block
aggregates that per role — sessions, turns, tools and reads per turn,
orientation turns, context, the retry/fumble and batchable turns, prefix
breaks. The bill is charged per turn, so this is the readout a change to the
loop is measured on, run by run.

The report carries a `derived` block — the close-out ratios read across
slices as trend lines: planner share (the plan loop's own sessions),
research share (the plan loop's sub-agents), consult share (the completion
consult — the one fixed step every run makes past its phases, priced apart
so the rework line reads clean), rework share (run-loop spend past first
delivery: any session's round ≥2 other than the operator-answered
continuation of a `question`/`blocked` round, every further consult, and
every round of a phase the run appended — state.json's `appended_phases`,
0.5.0+). `--write-state` appends that block to the run loop's state.json as
`cost`, so the committed run record prices itself; a `cost` block written
before 0.9.15 carries the completion consult inside its rework share.

Usage:
    slice_cost.py <slice-dir> [--json] [--write-state]

Exit codes: 0 report printed · 2 no state file found in the slice dir.
"""

import argparse
import json
import statistics
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import turn_profile  # noqa: E402

# USD per 1,000,000 tokens — public Anthropic sticker prices. The loop's
# dispatches force the 5-minute cache TTL (SPAWN_ENV in run_loop.py), so the
# 5-minute write multiplier is the right one.
PRICES: dict[str, dict[str, float]] = {
    "claude-fable-5":            {"input": 10.0, "output": 50.0},
    "claude-opus-5":             {"input": 5.0,  "output": 25.0},
    "claude-opus-4-8":           {"input": 5.0,  "output": 25.0},
    "claude-opus-4-7":           {"input": 5.0,  "output": 25.0},
    "claude-opus-4-6":           {"input": 5.0,  "output": 25.0},
    "claude-sonnet-5":           {"input": 3.0,  "output": 15.0},
    "claude-sonnet-4-6":         {"input": 3.0,  "output": 15.0},
    "claude-haiku-4-5":          {"input": 1.0,  "output": 5.0},
    "claude-haiku-4-5-20251001": {"input": 1.0,  "output": 5.0},
}
CACHE_WRITE_MULT = 1.25
CACHE_READ_MULT = 0.10
USAGE_KEYS = {
    "input": "input_tokens",
    "output": "output_tokens",
    "cache_write": "cache_creation_input_tokens",
    "cache_read": "cache_read_input_tokens",
}

STATE_FILES = (("state.json", "run"), ("plan_state.json", "plan"))


def cost_for(model: str, tok: dict[str, int]) -> float:
    base = PRICES.get(model)
    if base is None:
        return 0.0
    rates = {
        "input": base["input"],
        "output": base["output"],
        "cache_write": base["input"] * CACHE_WRITE_MULT,
        "cache_read": base["input"] * CACHE_READ_MULT,
    }
    return sum(tok.get(k, 0) / 1_000_000 * rates[k] for k in USAGE_KEYS)


def _parse_ts(ts) -> datetime | None:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(UTC)
    except (ValueError, AttributeError, TypeError):
        return None


class Conv:
    """One priced conversation: a recorded session, one of its sub-agents,
    or an orchestrator."""

    def __init__(self, session: str, role: str, phase: str | None,
                 kind: str, transcript: Path, loop: str | None = None,
                 round_: int | None = None, parent: "Conv | None" = None,
                 appended: bool = False, continuation: bool = False):
        self.session = session
        self.role = role          # code-writer / subagent:<type> / orchestrator:<loop>
        self.phase = phase        # phase id, or None for phaseless roles
        self.kind = kind          # "session" | "subagent" | "orchestrator"
        self.transcript = transcript
        self.loop = loop          # "run" | "plan" — the state file that recorded it
        self.round = round_       # the history entry's round; None for orchestrators
        self.parent = parent      # the recorded session a sub-agent rides under
        self.appended = appended  # the phase was appended by the run (a consult / test round)
        # A round ≥2 that resumes its own role's question/blocked round —
        # the operator answered and the first delivery went on, so not
        # spend past it.
        self.continuation = continuation
        self.tok_by_model: dict[str, dict[str, int]] = defaultdict(
            lambda: dict.fromkeys(USAGE_KEYS, 0))
        self.turns = 0            # deduplicated billed assistant messages
        self.start: datetime | None = None
        self.end: datetime | None = None

    def total_tokens(self) -> int:
        return sum(t[k] for t in self.tok_by_model.values() for k in USAGE_KEYS)

    def tokens_by_class(self) -> dict[str, int]:
        out = dict.fromkeys(USAGE_KEYS, 0)
        for t in self.tok_by_model.values():
            for k in USAGE_KEYS:
                out[k] += t[k]
        return out

    def cost(self) -> float:
        return sum(cost_for(m, t) for m, t in self.tok_by_model.items())

    def duration_s(self) -> float:
        if self.start and self.end:
            return (self.end - self.start).total_seconds()
        return 0.0


def scan_transcript(path: Path, conv: Conv) -> None:
    """Accumulate usage from one stream-json transcript, one record per
    message id (the file logs each assistant message multiple times)."""
    seen: set[str] = set()
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") not in ("assistant", "user"):
            continue
        ts = _parse_ts(obj.get("timestamp"))
        if ts:
            conv.start = ts if conv.start is None else min(conv.start, ts)
            conv.end = ts if conv.end is None else max(conv.end, ts)
        if obj.get("type") != "assistant":
            continue
        msg = obj.get("message") or {}
        usage = msg.get("usage")
        if not usage:
            continue
        mid = msg.get("id")
        if mid and mid in seen:
            continue
        if mid:
            seen.add(mid)
        conv.turns += 1
        bucket = conv.tok_by_model[msg.get("model", "unknown")]
        for k, uk in USAGE_KEYS.items():
            bucket[k] += usage.get(uk, 0) or 0


def _subagent_convs(parent: Conv) -> list[Conv]:
    """Sub-agent transcripts live next to the parent's:
    <dir>/<session>/subagents/agent-*.jsonl (+ agent-*.meta.json)."""
    subdir = parent.transcript.with_suffix("") / "subagents"
    convs = []
    for f in sorted(subdir.glob("agent-*.jsonl")):
        agent_type = "unknown"
        meta = f.with_suffix(".meta.json")
        if meta.is_file():
            try:
                agent_type = (json.loads(meta.read_text())
                              .get("agentType") or "unknown")
            except (json.JSONDecodeError, OSError):
                pass
        c = Conv(f.stem, f"subagent:{agent_type}", parent.phase,
                 "subagent", f, loop=parent.loop, parent=parent)
        scan_transcript(f, c)
        if c.turns:
            convs.append(c)
    return convs


def collect(slice_dir: Path) -> tuple[list[Conv], list[str]]:
    """(conversations, warnings). Sessions come from the state files'
    orchestrator records and histories; a session recorded several times
    (nudges, resumes, session-limit redispatches) is scanned once."""
    convs: list[Conv] = []
    warnings: list[str] = []
    seen_sessions: set[str] = set()
    found_state = False

    def add(session: str | None, role: str, phase: str | None,
            kind: str, transcript: str | None, loop: str,
            round_: int | None = None, appended: bool = False,
            continuation: bool = False) -> None:
        if not session or not transcript or session in seen_sessions:
            return
        seen_sessions.add(session)
        path = Path(transcript)
        conv = Conv(session, role, phase, kind, path, loop=loop,
                    round_=round_, appended=appended,
                    continuation=continuation)
        if not path.is_file():
            warnings.append(f"transcript missing for {role} "
                            f"session {session}: {path}")
            return
        scan_transcript(path, conv)
        convs.append(conv)
        convs.extend(_subagent_convs(conv))

    for name, loop in STATE_FILES:
        path = slice_dir / name
        try:
            state = json.loads(path.read_text())
        except OSError:
            continue
        except json.JSONDecodeError as e:
            warnings.append(f"{name} is not valid JSON ({e}) — skipped")
            continue
        found_state = True
        orch = state.get("orchestrator") or {}
        add(orch.get("session"), f"orchestrator:{loop}", None,
            "orchestrator", orch.get("transcript"), loop)
        # Phases the run itself appended (0.5.0+ state; absent before —
        # then nothing is marked, and the share reads as it always did).
        appended = {str(p) for p in state.get("appended_phases") or []}
        # Each phase's last recorded row, in history order: a row whose
        # predecessor is its own role's `question` / `blocked` round is
        # that round continued after the operator's answer.
        last: dict[str | None, tuple[str, str | None]] = {}
        for entry in state.get("history", []):
            phase = entry.get("phase")
            role = entry.get("role", "unknown")
            prev = last.get(phase)
            add(entry.get("session"), role,
                phase, "session", entry.get("transcript"),
                loop, entry.get("round"),
                appended=phase is not None and str(phase) in appended,
                continuation=prev is not None and prev[0] == role
                and prev[1] in ("question", "blocked"))
            last[phase] = (role, entry.get("outcome"))

    if not found_state:
        raise FileNotFoundError(
            f"no state.json or plan_state.json in {slice_dir} — "
            "the loops have not run this slice")
    return convs, warnings


def derive(convs: list[Conv], total_cost: float) -> dict:
    """The close-out ratios. Planner = the plan loop's own sessions (the
    interactive orchestrator, plan-writer, plan-reviewer); research = the
    plan loop's sub-agents; consult = the completion consult, the one
    phaseless consult every run dispatches once its phases are merged (a
    fixed step, so it is priced apart from rework — the first such row;
    a second one only follows appended work and is rework); rework =
    run-loop spend past first delivery — any session's round ≥2 (writer
    gate and review fixes, re-reviews, second test or doc rounds) except a
    round that resumes its own role's question/blocked round, every other
    consult (a fix-round consult, a later completion consult), and every
    round of a phase the run appended (its round 1 is work the first
    delivery did not include), sub-agents riding their dispatcher's
    bucket."""

    completion = next((c for c in convs
                       if c.loop == "run" and c.kind == "session"
                       and c.role == "consult" and c.phase is None), None)

    def is_rework(c: Conv) -> bool:
        o = c.parent or c
        if o.loop != "run" or o is completion:
            return False
        if o.role == "consult" or o.appended:
            return True
        return (o.kind == "session" and (o.round or 0) >= 2
                and not o.continuation)

    planner = sum(c.cost() for c in convs
                  if c.loop == "plan" and c.kind != "subagent")
    research = sum(c.cost() for c in convs
                   if c.loop == "plan" and c.kind == "subagent")
    consult = sum(c.cost() for c in convs
                  if completion is not None and (c.parent or c) is completion)
    rework = sum(c.cost() for c in convs if is_rework(c))

    def share(cost: float) -> float:
        return round(cost / total_cost, 3) if total_cost else 0.0

    return {
        "cost_usd": round(total_cost, 2),
        "planner_cost_usd": round(planner, 2),
        "planner_share": share(planner),
        "research_cost_usd": round(research, 2),
        "research_share": share(research),
        "consult_cost_usd": round(consult, 2),
        "consult_share": share(consult),
        "rework_cost_usd": round(rework, 2),
        "rework_share": share(rework),
    }


def turn_stats(convs: list[Conv]) -> dict:
    """The turn profile of the whole slice, per role.

    Every conversation's transcript is replayed a second time (turn_profile.py)
    and its turns classified by what they did. Per role: sessions, turns, tool
    calls and read ops per turn (reads count the ones chained inside one Bash
    command, which is where the batching actually happens), the median
    orientation span — turns before the session's first edit — the median first
    and mean context and the largest one reached, the retry-and-fumble turns,
    the turns a batched read would have folded away, and the prefix breaks.

    `avoidable` is `retry + fumble + batchable(strict)` priced at the slice's
    own cost per turn: the turns a fix to the tooling or a batched read would
    remove. It is a floor — it counts no orientation turn a better dispatch
    would remove, and no session a split would bound.
    """
    per_role: dict[str, list[dict]] = defaultdict(list)
    for c in convs:
        try:
            rep = turn_profile.replay(c.transcript)
        except OSError:
            continue
        analysis = turn_profile.analyse(rep, cost_for)
        if analysis:
            per_role[c.role].append(analysis["metrics"])

    def med(xs: list[int]) -> int:
        return round(statistics.median(xs)) if xs else 0

    roles: dict[str, dict] = {}
    for role, ms in per_role.items():
        turns = sum(m["turns"] for m in ms)
        roles[role] = {
            "n": len(ms),
            "turns": turns,
            "cost_usd": round(sum(m["cost"] for m in ms), 2),
            "tools_per_turn": round(sum(m["tool_calls"] for m in ms) / turns, 2),
            "reads_per_turn": round(sum(m["read_ops"] for m in ms) / turns, 2),
            "orient_turns": med([m["orient_turns_edit"] for m in ms]),
            "ctx_first": med([m["ctx_first"] for m in ms]),
            "ctx_mean": med([m["ctx_mean"] for m in ms]),
            "ctx_max": max(m["ctx_max"] for m in ms),
            "retry_fumble_turns": sum(m["retry_turns"] + m["fumble_turns"] for m in ms),
            "batchable_strict_turns": sum(m["batchable_strict_turns"] for m in ms),
            "breaks": sum(m["breaks"] for m in ms),
        }

    turns = sum(r["turns"] for r in roles.values())
    cost = sum(r["cost_usd"] for r in roles.values())
    retry_fumble = sum(r["retry_fumble_turns"] for r in roles.values())
    batchable = sum(r["batchable_strict_turns"] for r in roles.values())
    avoidable = retry_fumble + batchable
    per_turn = cost / turns if turns else 0.0
    return {
        "sessions": sum(r["n"] for r in roles.values()),
        "turns": turns,
        "cost_per_turn_usd": round(per_turn, 4),
        "retry_fumble_turns": retry_fumble,
        "batchable_strict_turns": batchable,
        "avoidable_turns": avoidable,
        "avoidable_share": round(avoidable / turns, 3) if turns else 0.0,
        "avoidable_cost_usd": round(avoidable * per_turn, 2),
        "by_role": dict(sorted(roles.items(), key=lambda kv: -kv[1]["cost_usd"])),
    }


def build_report(slice_dir: Path, convs: list[Conv],
                 warnings: list[str]) -> dict:
    totals = dict.fromkeys(USAGE_KEYS, 0)
    cost = 0.0
    active_s = 0.0
    start = end = None
    roles: dict[str, dict] = defaultdict(
        lambda: {"n": 0, "turns": 0, "tokens": 0, "cost": 0.0})
    phases: dict[str, dict] = defaultdict(
        lambda: {"n": 0, "tokens": 0, "cost": 0.0})
    unpriced: dict[str, int] = defaultdict(int)

    for c in convs:
        for k, v in c.tokens_by_class().items():
            totals[k] += v
        cost += c.cost()
        active_s += c.duration_s()
        if c.start:
            start = c.start if start is None else min(start, c.start)
        if c.end:
            end = c.end if end is None else max(end, c.end)
        r = roles[c.role]
        r["n"] += 1
        r["turns"] += c.turns
        r["tokens"] += c.total_tokens()
        r["cost"] += c.cost()
        p = phases[f"P{c.phase}" if c.phase else c.role]
        p["n"] += 1
        p["tokens"] += c.total_tokens()
        p["cost"] += c.cost()
        for model, tok in c.tok_by_model.items():
            if model not in PRICES:
                unpriced[model] += sum(tok[k] for k in USAGE_KEYS)

    for model, tokens in sorted(unpriced.items()):
        warnings.append(f"unknown model '{model}': {tokens:,} tokens "
                        "unpriced — extend PRICES in slice_cost.py")

    return {
        "slice": slice_dir.name,
        "totals": {
            "cost_usd": round(cost, 2),
            "tokens": sum(totals.values()),
            **totals,
            "conversations": len(convs),
            "turns": sum(c.turns for c in convs),
            "wall_s": (end - start).total_seconds() if start and end else 0.0,
            "active_s": active_s,
        },
        "derived": derive(convs, cost),
        "turns": turn_stats(convs),
        "roles": {r: {**v, "cost": round(v["cost"], 2)}
                  for r, v in sorted(roles.items(),
                                     key=lambda kv: -kv[1]["cost"])},
        "phases": {p: {**v, "cost": round(v["cost"], 2)}
                   for p, v in sorted(phases.items(),
                                      key=lambda kv: -kv[1]["cost"])},
        "sessions": [
            {"session": c.session, "role": c.role, "phase": c.phase,
             "round": c.round,
             "kind": c.kind, "turns": c.turns, "tokens": c.total_tokens(),
             "cost_usd": round(c.cost(), 2),
             "duration_s": round(c.duration_s())}
            for c in sorted(convs, key=lambda c: -c.cost())
        ],
        "warnings": warnings,
    }


def print_report(report: dict) -> None:
    t = report["totals"]
    print(f"slice {report['slice']} — cost report")
    print(f"  ${t['cost_usd']:,.2f}  ·  {t['tokens']:,} tokens "
          f"(in {t['input']:,} / out {t['output']:,} / "
          f"cache-write {t['cache_write']:,} / cache-read {t['cache_read']:,})")
    print(f"  {t['conversations']} conversations, {t['turns']:,} billed "
          f"messages  ·  wall {t['wall_s'] / 3600:.1f}h, "
          f"active {t['active_s'] / 3600:.1f}h")
    d = report["derived"]
    print(f"  planner ${d['planner_cost_usd']:,.2f} "
          f"({d['planner_share']:.0%})  ·  "
          f"research ${d['research_cost_usd']:,.2f} "
          f"({d['research_share']:.0%})  ·  "
          f"consult ${d['consult_cost_usd']:,.2f} "
          f"({d['consult_share']:.0%})  ·  "
          f"rework ${d['rework_cost_usd']:,.2f} ({d['rework_share']:.0%})")

    print(f"\n{'role':26} {'n':>3} {'turns':>6} {'tokens':>13} {'cost':>9}")
    for role, v in report["roles"].items():
        print(f"{role:26} {v['n']:>3} {v['turns']:>6} {v['tokens']:>13,} "
              f"${v['cost']:>8,.2f}")

    tp = report["turns"]
    print(f"\n{tp['turns']:,} turns at ${tp['cost_per_turn_usd']:.3f}  ·  "
          f"avoidable {tp['avoidable_turns']:,} "
          f"({tp['avoidable_share']:.1%}, ${tp['avoidable_cost_usd']:,.2f}) = "
          f"retry+fumble {tp['retry_fumble_turns']:,} + "
          f"batchable {tp['batchable_strict_turns']:,}")
    print(f"{'role':26} {'n':>3} {'turns':>6} {'tool/t':>7} {'read/t':>7} "
          f"{'orient':>7} {'ctx1':>8} {'ctxmean':>8} {'ctxmax':>8} {'r+f':>5} "
          f"{'batch':>6} {'brks':>5}")
    for role, v in tp["by_role"].items():
        print(f"{role:26} {v['n']:>3} {v['turns']:>6} {v['tools_per_turn']:>7.2f} "
              f"{v['reads_per_turn']:>7.2f} {v['orient_turns']:>7} "
              f"{v['ctx_first']:>8,} {v['ctx_mean']:>8,} {v['ctx_max']:>8,} "
              f"{v['retry_fumble_turns']:>5} {v['batchable_strict_turns']:>6} "
              f"{v['breaks']:>5}")

    print(f"\n{'phase':26} {'n':>3} {'tokens':>13} {'cost':>9}")
    for phase, v in report["phases"].items():
        print(f"{phase:26} {v['n']:>3} {v['tokens']:>13,} ${v['cost']:>8,.2f}")

    print(f"\n{'session (by cost)':44} {'turns':>6} {'tokens':>13} "
          f"{'cost':>9} {'dur':>7}")
    for s in report["sessions"]:
        label = (f"{('P' + s['phase'] + ' ') if s['phase'] else ''}{s['role']}"
                 + (f" r{s['round']}" if s.get("round") else ""))
        print(f"{label:32} {s['session'][:10]:>11} {s['turns']:>6} "
              f"{s['tokens']:>13,} ${s['cost_usd']:>8,.2f} "
              f"{s['duration_s'] / 60:>6.0f}m")

    if report["warnings"]:
        print("\nwarnings:")
        for w in report["warnings"]:
            print(f"  - {w}")


def write_state(slice_dir: Path, report: dict) -> None:
    """Append the derived and turn blocks to state.json as `cost` —
    the one write anything but the driver makes there, at close-out, after
    the run is done. Warnings ride along: a share computed over missing
    transcripts must say so where the number is read."""
    state_path = slice_dir / "state.json"
    state = json.loads(state_path.read_text())
    state["cost"] = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        **report["derived"],
        "turns": report["turns"],
        "warnings": report["warnings"],
    }
    tmp = state_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    tmp.replace(state_path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slice_dir", help="path to slices/NNN_slug/")
    ap.add_argument("--json", action="store_true",
                    help="emit the report as JSON instead of a table")
    ap.add_argument("--write-state", action="store_true",
                    help="append the derived ratios to state.json as `cost`")
    args = ap.parse_args(argv)

    slice_dir = Path(args.slice_dir).resolve()
    if not slice_dir.is_dir():
        print(f"Error: slice directory not found: {slice_dir}",
              file=sys.stderr)
        return 2
    try:
        convs, warnings = collect(slice_dir)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    report = build_report(slice_dir, convs, warnings)
    if args.write_state:
        try:
            write_state(slice_dir, report)
        except (OSError, json.JSONDecodeError) as e:
            print(f"Error: cannot write cost into state.json: {e}",
                  file=sys.stderr)
            return 2
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
