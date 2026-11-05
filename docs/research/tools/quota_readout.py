#!/usr/bin/env python3
"""The subscription-quota read — what every transcript cost, priced the way the plugin prices a
slice, summed per quota week and held against the weekly limit (quota-read-2026-11-05.md).

  scan     walk ~/.claude/projects (shared across every environment on this host), price each
           assistant message once (deduplicated by message id across all files, the largest
           count of a streamed message kept) with slice_cost.cost_for, and write the data file:
           cost per UTC hour and model family, tokens per quota week and model id, and every
           limit message ("You've hit your weekly limit · resets …", the 5-hour "session
           limit", the older bare "limit")
  weeks    per quota week: $ by family, the weekly hits in it, the free reset in it
  hits     every limit message, deduplicated to the minute
  compare  the weeks that ran out (week start to the weekly hit), the near-full weeks before
           and after the 2026-09-14 quota change, the same-model split, and each week re-priced
           with the 5.5 models at their 5.1 rates

A quota week starts Thursday 10:00 UTC: the limit messages say "resets 12pm" Amsterdam time in
summer and "resets 11am" after 2026-10-25, so the boundary is fixed in UTC. Fable is counted
with the rest: it draws from the main quota and its own at once (the operator, 2026-11-05).

Research tooling, not plugin. Usage:

  python3 docs/research/tools/quota_readout.py scan --since 2026-01-01
  python3 docs/research/tools/quota_readout.py compare
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import statistics as st
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[3] / "plugins" / "dev" / "tools"
DATA = Path(__file__).resolve().parents[1] / "data" / "quota-2026-11-05.json"
PROJECTS = Path.home() / ".claude" / "projects"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sc = _load("slice_cost")

FAMILIES = ("opus", "sonnet", "haiku", "fable")
LIMIT_RE = re.compile(r"You've hit your (?:(\w+) )?limit · resets ([^·\n]+)")
# The 5.5 models at the rates of the model each replaced (compare's re-pricing).
AT_51 = {"claude-opus-5-5": "claude-opus-5", "claude-sonnet-5-5": "claude-sonnet-5"}

# Free resets Anthropic granted (the operator's list, 2026-11-05). A week holding one is left out
# of every comparison; one on the week's first Thursday counts the week as a range, since the
# day's spend before the reset (time not known) may not have counted.
FREE_RESETS = [date(2026, 2, 27), date(2026, 4, 17), date(2026, 4, 23), date(2026, 5, 15),
               date(2026, 6, 1), date(2026, 6, 9), date(2026, 6, 13), date(2026, 6, 19),
               date(2026, 6, 20), date(2026, 7, 1), date(2026, 7, 9), date(2026, 7, 16),
               date(2026, 9, 1), date(2026, 9, 4)]
# The banked Opus 5.5 reset, used on hitting the limit 2026-10-12 ~10:10 UTC — and that week
# held a lot of claude.ai work, which no transcript shows, so it is out of the near-full set.
LEFT_OUT = {date(2026, 10, 8): "banked reset used Oct 12; heavy claude.ai that week",
            date(2026, 9, 10): "straddles the 2026-09-14 quota change"}
CHANGE = date(2026, 9, 14)          # +50 % over the original quota became +25 %
NEAR_FULL = (date(2026, 7, 2), date(2026, 10, 29))   # the operator targets 98-99 % a week


def family(model: str) -> str:
    return next((f for f in FAMILIES if f in model), "other")


def week_of(t: datetime) -> date:
    t = t.astimezone(UTC) - timedelta(hours=10)
    return t.date() - timedelta(days=(t.weekday() - 3) % 7)


def _ts(s) -> datetime | None:
    """A transcript timestamp, or a hit's minute as stored (UTC, no offset), as aware UTC."""
    try:
        t = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)


def _scan_file(path: Path):
    msgs, hits = {}, set()
    try:
        fh = path.open(errors="replace", newline="\n")
    except OSError:
        return msgs, hits
    with fh:
        for line in fh:
            if '"assistant"' not in line or ('"usage"' not in line and "hit your" not in line):
                continue
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            if o.get("type") != "assistant":
                continue
            msg = o.get("message") or {}
            model = msg.get("model") or "?"
            if model == "<synthetic>":
                text = "".join(b.get("text", "") for b in msg.get("content") or []
                               if isinstance(b, dict))
                m = LIMIT_RE.match(text)
                if m:
                    hits.add((str(o.get("timestamp", ""))[:16], m.group(1) or "",
                              m.group(2).strip()))
                continue
            u = msg.get("usage") or {}
            if not u:
                continue
            cw5, cw1h = sc.cache_write_split(u.get("cache_creation_input_tokens", 0) or 0,
                                             u.get("cache_creation"))
            rec = [o.get("timestamp"), model, u.get("input_tokens", 0) or 0,
                   u.get("cache_read_input_tokens", 0) or 0, cw5, cw1h,
                   u.get("output_tokens", 0) or 0]
            mid = msg.get("id") or o.get("requestId") or o.get("uuid")
            prev = msgs.get(mid)
            msgs[mid] = rec if prev is None else \
                [prev[0] or rec[0], prev[1], *map(max, prev[2:], rec[2:])]
    return msgs, hits


def scan(args) -> None:
    since = datetime.fromisoformat(args.since).replace(tzinfo=UTC)
    files = [p for p in PROJECTS.rglob("*.jsonl")
             if datetime.fromtimestamp(p.stat().st_mtime, UTC) >= since]
    msgs, hits = {}, set()
    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        for m, h in ex.map(_scan_file, files, chunksize=20):
            for k, v in m.items():
                msgs.setdefault(k, v)
            hits |= h
    hourly = defaultdict(lambda: defaultdict(float))
    weekly = defaultdict(lambda: defaultdict(int))
    for ts, model, inp, cr, cw5, cw1h, out in msgs.values():
        t = _ts(ts)
        if t is None or t < since:
            continue
        tok = {"input": inp, "cache_read": cr, "cache_write": cw5, "cache_write_1h": cw1h,
               "output": out}
        hourly[t.strftime("%Y-%m-%dT%H")][family(model)] += sc.cost_for(
            model, tok, inp + cr + cw5 + cw1h)
        w = weekly[f"{week_of(t)}|{model}"]
        for k, v in tok.items():
            w[k] += v
    data = {
        "note": "Data behind docs/research/quota-read-2026-11-05.md, written by "
                "quota_readout.py scan: $ per UTC hour and model family (slice_cost prices), "
                "tokens per quota week (Thursday 10:00 UTC) and model, and the limit messages.",
        "scanned": {"since": args.since, "files": len(files), "messages": len(msgs)},
        "hourly": {h: {f: round(c, 4) for f, c in d.items()} for h, d in sorted(hourly.items())},
        "weekly_tokens": {k: dict(v) for k, v in sorted(weekly.items())},
        "hits": sorted(hits),
    }
    args.data.write_text(json.dumps(data, indent=0) + "\n")
    print(f"{len(files)} files, {len(msgs)} messages, {len(hits)} limit messages -> {args.data}")


def _read(args) -> dict:
    return json.loads(args.data.read_text())


def _weekly_hits(data) -> dict[date, datetime]:
    """The first weekly-limit message of each quota week."""
    out = {}
    for ts, kind, _ in data["hits"]:
        t = _ts(ts)
        if kind == "weekly" and t:
            out.setdefault(week_of(t), t)
    return out


def _spend(data, start: datetime, end: datetime) -> dict[str, float]:
    a, b = start.strftime("%Y-%m-%dT%H"), end.strftime("%Y-%m-%dT%H")
    out = defaultdict(float)
    for h, d in data["hourly"].items():
        if a <= h < b:
            for f, c in d.items():
                out[f] += c
    return out


def _start(w: date) -> datetime:
    return datetime(w.year, w.month, w.day, 10, tzinfo=UTC)


def _resets_in(w: date) -> list[date]:
    return [r for r in FREE_RESETS if w <= r < w + timedelta(days=7)]


def _week_values(data):
    """Per week: (low, high) $ for the quota it shows, cut at its weekly hit; and why it is left
    out, if it is."""
    hits = _weekly_hits(data)
    weeks = sorted({week_of(_ts(h + ":00:00+00:00")) for h in data["hourly"]})
    for w in weeks:
        s = _start(w)
        end = hits[w] + timedelta(hours=1) if w in hits else s + timedelta(days=7)
        total = sum(_spend(data, s, end).values())
        low, why = total, LEFT_OUT.get(w)
        resets = _resets_in(w)
        if resets == [w]:
            low = total - sum(_spend(data, s, s + timedelta(hours=14)).values())
        elif resets:
            why = why or "free reset " + ", ".join(r.strftime("%b %d") for r in resets)
        yield w, low, total, w in hits, why


def weeks(args) -> None:
    data = _read(args)
    hits = _weekly_hits(data)
    print(f"{'week (Thu 10:00 UTC)':<22}{'total $':>9}" + "".join(f"{f:>9}" for f in FAMILIES)
          + "  weekly hit / free reset")
    by_week = defaultdict(lambda: defaultdict(float))
    for h, d in data["hourly"].items():
        w = week_of(_ts(h + ":00:00+00:00"))
        for f, c in d.items():
            by_week[w][f] += c
    for w in sorted(by_week):
        d = by_week[w]
        note = []
        if w in hits:
            note.append("hit " + hits[w].strftime("%a %b %d %H:%M"))
        note += ["reset " + r.strftime("%b %d") for r in _resets_in(w)]
        print(f"{w!s:<22}{sum(d.values()):>9.0f}" + "".join(f"{d[f]:>9.0f}" for f in FAMILIES)
              + "  " + ", ".join(note))


def hits(args) -> None:
    for ts, kind, resets in _read(args)["hits"]:
        print(f"{ts}  {kind or '-':<8}{resets}")


def _stats(vals: list[float]) -> str:
    m = st.mean(vals)
    return (f"n={len(vals)}  mean ${m:,.0f}  median ${st.median(vals):,.0f}  "
            f"${min(vals):,.0f}-{max(vals):,.0f}  ±{st.pstdev(vals) / m * 100:.0f} %")


def compare(args) -> None:
    data = _read(args)
    rows = list(_week_values(data))
    print("Weeks that ran out (week start -> weekly hit):")
    for w, low, high, hit, why in rows:
        if hit:
            rng = f"${low:,.0f}-{high:,.0f}" if low != high else f"${high:,.0f}"
            print(f"  {w}  {rng:<14}{'(' + why + ')' if why else ''}")
    pre, post = [], []
    print("\nNear-full weeks (the operator targets 98-99 %); a range uses its midpoint:")
    for w, low, high, _, why in rows:
        if not NEAR_FULL[0] <= w <= NEAR_FULL[1]:
            continue
        if why:
            print(f"  {w}  left out: {why}")
            continue
        (pre if w + timedelta(days=7) <= CHANGE else post).append((low + high) / 2)
    print(f"  before {CHANGE}: {_stats(pre)}")
    print(f"  after:            {_stats(post)}")
    print(f"  change: mean {st.mean(post) / st.mean(pre) - 1:+.1%}, "
          f"median {st.median(post) / st.median(pre) - 1:+.1%} (announced -16.7 %)")

    cost, alt = defaultdict(float), defaultdict(float)
    opus = defaultdict(lambda: defaultdict(float))
    for key, tok in data["weekly_tokens"].items():
        w, model = key.split("|")
        c = sc.cost_for(model, tok)
        cost[w] += c
        alt[w] += sc.cost_for(AT_51.get(model, model), tok)
        if family(model) == "opus":
            opus[w][model] += c
    lead = {w: max(d, key=d.get) for w, d in opus.items()}
    vals = {str(w): (low + high) / 2 for w, low, high, _, why in rows if not why}
    for label, model, after in (("Opus 5.1 weeks before the change", "claude-opus-5", False),
                                ("Opus 5.1 weeks after it", "claude-opus-5", True),
                                ("Opus 5.5 weeks after it", "claude-opus-5-5", True)):
        v = [x for w, x in vals.items() if lead.get(w) == model
             and NEAR_FULL[0] <= date.fromisoformat(w) <= NEAR_FULL[1]
             and (date.fromisoformat(w) >= CHANGE) == after]
        print(f"\n{label}: {_stats(v)}" if v else f"\n{label}: none", end="")
    print("\n\nRe-priced with the 5.5 models at their 5.1 rates (whole weeks):")
    for w in sorted(cost):
        if cost[w] >= 100 and alt[w] != cost[w]:
            print(f"  {w}  as priced ${cost[w]:,.0f}   at 5.1 rates ${alt[w]:,.0f}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", type=Path, default=DATA)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan")
    s.add_argument("--since", default="2026-01-01")
    s.add_argument("--workers", type=int, default=6)
    for name in ("weeks", "hits", "compare"):
        sub.add_parser(name)
    args = ap.parse_args()
    {"scan": scan, "weeks": weeks, "hits": hits, "compare": compare}[args.cmd](args)


if __name__ == "__main__":
    main()
