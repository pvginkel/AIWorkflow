#!/usr/bin/env python3
"""Risk-based review readout — what the review record says about a path-based risk map.

Research tooling for Trello #715 (risk-based review). Reads the completed slices of a spec
repo and, per phase, recovers what the phase touched (git), what the reviewer found (state.json
telemetry where present, the review markdown otherwise), what the fix round refuted, and what the
operator did with every close-out entry — then scores each phase and each finding against a
candidate risk map so the question "which reviews could have been skipped, and what would that
have cost" is answered from the record rather than from intuition.

    risk_readout.py extract [--since 063] [--out risk-corpus.json]
    risk_readout.py report  [--in risk-corpus.json] [--tests low|medium]

Not part of the plugin; stdlib-only anyway so it runs in the pod.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

SPEC = Path("/work/KubeCoderSpecs/slices/completed")
WORK = Path("/work")

# ---------------------------------------------------------------- candidate risk map

# Per repo: base level, then (path prefix, level) rules; longest matching prefix wins.
# `test` is its own bucket so the report can price both assignments (low vs medium).
RISK_MAP: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "KubeCoder": ("medium", [
        ("docs/", "low"), ("manual/", "low"), ("README.md", "low"), ("CLAUDE.md", "low"),
        ("controller/docs/", "low"), ("worker/docs/", "low"), ("bot/docs/", "low"),
        ("vscode-extension/docs/", "low"), ("mcp-server/docs/", "low"),
        ("controller/CLAUDE.md", "low"), ("worker/CLAUDE.md", "low"), ("bot/CLAUDE.md", "low"),
        ("vscode-extension/CLAUDE.md", "low"), ("vscode-extension/README.md", "low"),
        ("manual/README.md", "low"), ("mcp-server/CLAUDE.md", "low"),
        ("tools/", "low"), ("scripts/", "low"), ("worker/tools/", "low"),
        ("controller/tools/", "low"),
        ("controller/tests/", "test"), ("bot/tests/", "test"), ("mcp-server/tests/", "test"),
        ("vscode-extension/test/", "test"),
        (".claude/", "high"), (".kubecoder/", "high"), (".aiworkflowrc", "high"),
        ("Jenkinsfile", "high"), (".gitignore", "high"), (".dockerignore", "high"),
        ("worker/.claude/", "high"), ("controller/.claude/", "high"), ("bot/.claude/", "high"),
        ("vscode-extension/.claude/", "high"),
        ("controller/ingress/", "high"), ("worker/Dockerfile", "high"),
    ]),
    "HelmCharts": ("high", [
        ("docs/", "low"), ("tests/", "test"), ("tools/", "medium"), ("CLAUDE.md", "low"),
    ]),
    "DockerImages": ("medium", [("docs/", "low"), ("CLAUDE.md", "low")]),
    "KubeCoderConfig": ("high", [("CLAUDE.md", "low")]),
    "KubeCoderSpecs": ("low", []),
    "Ansible": ("high", [("docs/", "low")]),
    "AnsibleSpecs": ("low", []),
}


def classify(repo: str, path: str) -> str:
    base, rules = RISK_MAP.get(repo, ("medium", []))
    best, level = -1, base
    if os.path.basename(path).startswith("."):
        best, level = 0, "high"  # dotfiles anywhere: config, high
    if re.search(r"(_test\.go|\.test\.ts|\.test\.js|/test_[^/]*\.py|/tests?/)$|/tests?/", path):
        best, level = 0, "test"
    for prefix, lvl in rules:
        if path.startswith(prefix) and len(prefix) > best:
            best, level = len(prefix), lvl
    return level


LEVELS = {"low": 0, "test": 1, "medium": 2, "high": 3}

# ---------------------------------------------------------------- git helpers


def repo_for_target(target: str) -> Path:
    if target.startswith("../"):
        return (WORK / target[3:]).resolve()
    return WORK / "KubeCoder"


def git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


_AUTHOR_LOG: dict[Path, list[tuple[str, datetime]]] = {}


def commit_exists(repo: Path, sha: str | None) -> bool:
    if not sha:
        return False
    return subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"],
                          capture_output=True).returncode == 0


def phase_files_by_author_window(repo: Path, window: tuple[datetime, datetime],
                                 cited: set[str], cwd: str | None) -> tuple[list[str], int]:
    """Commits on the repo's current branch whose AUTHOR date falls in the window — the way to
    find a phase's commits after the test phase's rebase rewrote their shas. Parallel lanes commit
    in the same window, so a commit is kept only if it touches a file the round-1 review cites
    (full path or basename) — the reviewer names what it read — or, for a component target, a
    file under that component's directory; a window with no cited match keeps everything."""
    if repo not in _AUTHOR_LOG:
        rows = []
        for line in git(repo, "log", "--since=2026-06-01", "--format=%H %aI").splitlines():
            sha, ai = line.split(" ", 1)
            rows.append((sha, datetime.fromisoformat(ai)))
        _AUTHOR_LOG[repo] = rows
    cands = [sha for sha, t in _AUTHOR_LOG[repo] if window[0] <= t <= window[1]]
    per_commit = {}
    for sha in cands:
        per_commit[sha] = [
            f.strip()
            for f in git(repo, "show", "--name-only", "--format=", sha).splitlines()
            if f.strip()
        ]
    if cwd:
        per_commit = {s: fs for s, fs in per_commit.items()
                      if any(f.startswith(cwd + "/") for f in fs)} or per_commit
    bases = {os.path.basename(c) for c in cited}
    matched = {s: fs for s, fs in per_commit.items()
               if any(f in cited or os.path.basename(f) in bases for f in fs)}
    if matched:
        per_commit = matched
    files: set[str] = set()
    for fs in per_commit.values():
        files.update(fs)
    return sorted(files), len(per_commit)


def phase_files(repo: Path, base: str, head: str, window: tuple[datetime, datetime] | None
                ) -> tuple[list[str], int, int]:
    """Files touched by commits in base..head, restricted to the phase's time window when one
    is known. Returns (files, commits kept, commits dropped by the window)."""
    log = git(repo, "log", "--format=%H %cI", f"{base}..{head}")
    kept, dropped = [], 0
    for line in log.splitlines():
        sha, ci = line.split(" ", 1)
        if window:
            t = datetime.fromisoformat(ci)
            if not (window[0] <= t <= window[1]):
                dropped += 1
                continue
        kept.append(sha)
    files: set[str] = set()
    for sha in kept:
        for f in git(repo, "show", "--name-only", "--format=", sha).splitlines():
            if f.strip():
                files.add(f.strip())
    return sorted(files), len(kept), dropped


# ---------------------------------------------------------------- review markdown

HEAD_RE = re.compile(r"^(#{2,4})\s+(?:F|Finding\s+)?(\d+)(?:[.)]|\s*[—·:-])\s*(.*)$")
SEV_RE = re.compile(r"\b(Blocker|Major|Minor)\b")
IMP_RE = re.compile(r"\b(blocking|advisory)\b", re.I)
ANCHOR_RE = re.compile(r"anchor[:\s`]+([a-z-]+)", re.I)
PATH_RE = re.compile(r"(?<![\w/@])((?:[\w.-]+/)+[\w.-]+\.[A-Za-z]{1,5})(?::\d+)?")
BARE_RE = re.compile(
    r"(?<![\w/.-])([\w-]+\.(?:py|go|ts|js|md|yaml|yml|json|toml|sh|tsx|lua|html|css))(?::\d+)?"
)
RANGE_RE = re.compile(r"diff\s+`?([0-9a-f]{7,40})\.\.")


def parse_review_md(text: str) -> tuple[list[dict], str | None]:
    lines = text.splitlines()
    heads = [(i, m) for i, m in ((i, HEAD_RE.match(line)) for i, line in enumerate(lines)) if m]
    # only count headings under a "Findings"-like section, or F-prefixed ones
    findings = []
    for i, m in heads:
        level = len(m.group(1))
        end = len(lines)
        for j in range(i + 1, len(lines)):
            hm = re.match(r"^(#{1,3})\s", lines[j])
            if hm and len(hm.group(1)) <= level:
                end = j
                break
        body = "\n".join(lines[i:end])
        headline = m.group(3)
        first = "\n".join(lines[i:i + 3])
        sev = SEV_RE.search(first)
        imp = IMP_RE.search(first)
        anc = ANCHOR_RE.search(first)
        paths = sorted(set(PATH_RE.findall(body)))
        bare = sorted(set(BARE_RE.findall(body)))
        findings.append({
            "id": f"F{m.group(2)}", "headline": headline.strip("* "),
            "severity": sev.group(1) if sev else None,
            "impact": imp.group(1).lower() if imp else None,
            "anchor": anc.group(1) if anc else None,
            "paths": paths, "bare": bare, "lines": end - i,
        })
    rng = RANGE_RE.search(text[:600])
    return findings, (rng.group(1) if rng else None)


# ---------------------------------------------------------------- close-out markdown

LIVE_RE = re.compile(
    r"^### (?P<id>[ANBQS]\d+) — (?P<head>.*?)"
    r"(?: · (?P<sev>major|minor|nit|cosmetic))?\s*$"
)
STRUCK_RE = re.compile(
    r"^### ~~(?P<id>[ANBQS]\d+) — (?P<head>.*?)"
    r"(?: · (?P<sev>major|minor|nit|cosmetic))?~~\s*[—–-]\s*(?P<reason>.*)$"
)


def role_of(prov: str) -> str:
    p = prov.lower()
    if "refut" in p or "driver" in p:
        return "driver"
    if ("code-review" in p or "code review" in p or "reviewer, p" in p
            or "reviewer" in p and "plan" not in p):
        return "code-reviewer"
    if "test-agent" in p or "test phase" in p or "test agent" in p or "live_verification" in p:
        return "test-agent"
    if "consult" in p:
        return "consult"
    if "plan-writer" in p or "plan-reviewer" in p or "planning" in p or "plan review" in p:
        return "plan"
    if "doc-writer" in p or "doc phase" in p or "doc-phase" in p:
        return "doc-writer"
    if "code-writer" in p or "executor" in p or "writer" in p:
        return "code-writer"
    return "unknown"


def disposition_class(text: str, struck_reason: str | None) -> str:
    t = (text or "").lower().strip()
    r = (struck_reason or "").lower()
    if r:
        if "closed by the operator" in r or r.startswith("closed") or "not progressing" in r:
            return "closed"
        if "consult" in r or "mechanical residue" in r or "doc phase" in r or "duplicate" in r \
                or "resolved by p" in r or "resolved in p" in r or "superseded" in r:
            return "in-run"
        if "operator" in r or "close-out" in r or "inline" in r or "fix-now" in r or "card" in r \
                or "fixed" in r or "resolved" in r or "filed" in r:
            return "actioned"
        return "struck-other"
    if not t:
        return "blank"
    if re.search(r"\b(card|file|filed|triage)\b", t) \
            and not re.search(r"\bclose\b.*\bcard\b|\bcard\b.*\bclose\b", t):
        return "actioned"
    if re.search(r"\b(fix|apply|inline|make the change|complete|done|fold|progress it"
                 r"|do something)\b", t) \
            and not re.search(r"\b(won't|not|don't|isn't)\b.*\b(progress|fix)", t):
        return "actioned"
    if re.search(r"\b(close|closed|leave|won't progress|not progressing|don't want|ok\.?$)\b", t):
        return "closed"
    return "other"


def parse_closeout(text: str) -> list[dict]:
    lines = text.splitlines()
    entries, i = [], 0
    while i < len(lines):
        m = LIVE_RE.match(lines[i]) or STRUCK_RE.match(lines[i])
        if not m:
            i += 1
            continue
        struck = "reason" in m.groupdict() and m.group("reason") is not None
        j = i + 1
        while j < len(lines) and not re.match(r"^##", lines[j]):
            j += 1
        body = lines[i + 1:j]
        prov = next((line for line in body if "Provenance:" in line), "")
        disp = next((line for line in body if "Disposition:" in line), "")
        disp_text = re.sub(r"^.*Disposition:\*?\*?\s*", "", disp).strip()
        cons = next((line for line in body if "Consequence:" in line), "")
        cons_text = re.sub(r"^.*Consequence:\*?\*?\s*", "", cons).strip()
        pm = re.search(r"\bP(\d+)\b", prov)
        fm = re.search(r"\bF(\d+)\b|finding (\d+)", prov)
        entries.append({
            "id": m.group("id"), "section": m.group("id")[0], "headline": m.group("head"),
            "severity": m.group("sev"), "struck": struck,
            "struck_reason": m.group("reason") if struck else None,
            "provenance": prov.strip(), "role": role_of(prov),
            "phase": pm.group(1) if pm else None,
            "finding": (fm.group(1) or fm.group(2)) if fm else None,
            "evidence": ("witnessed" if "witnessed" in prov.lower()
                         else ("read" if "read" in prov.lower() else None)),
            "disposition": disp_text, "consequence": cons_text,
            "class": disposition_class(disp_text, m.group("reason") if struck else None),
            "paths": sorted(set(PATH_RE.findall("\n".join(body)))),
        })
        i = j
    return entries


# ---------------------------------------------------------------- extract


def extract(since: str) -> dict:
    out = {"slices": []}
    for sd in sorted(SPEC.iterdir()):
        if not sd.is_dir() or sd.name < since:
            continue
        sp = sd / "state.json"
        if not sp.exists():
            continue
        s = json.loads(sp.read_text())
        if not s.get("phases"):
            continue
        hist = s.get("history", [])
        rec = {
            "slice": sd.name, "plugin_version": s.get("plugin_version"),
            "created_at": s.get("created_at"), "test_rounds": s.get("test_rounds"),
            "appended_phases": s.get("appended_phases", []),
            "bailouts": s.get("bailouts", []), "generation": s.get("generation"),
            "consults": [{"phase": h.get("phase"), "outcome": h.get("outcome"),
                          "summary": h.get("summary", "")[:400]}
                         for h in hist if h["role"] == "consult"],
            "test_agent": [{"round": h.get("round"), "outcome": h.get("outcome"),
                            "summary": h.get("summary", "")[:400]}
                           for h in hist if h["role"] == "test-agent"],
            "phases": [], "closeout": None,
        }
        last_head: dict[str, str] = {}
        for pid in s.get("known_phases", list(s["phases"].keys())):
            ps = s["phases"].get(pid)
            if not ps or not ps.get("reviewed_head"):
                continue
            repo = repo_for_target(ps.get("target") or "root")
            rname = repo.name
            rows = [h for h in hist if h.get("phase") == pid]
            reviews = [h for h in rows if h["role"] == "code-reviewer"]
            execs = [h for h in rows if h["role"] == "code-writer"]
            base = last_head.get(str(repo)) or (s.get("slice_base") or {}).get(str(repo))
            # window: from the first row's ts minus its duration, to the last row's ts plus its
            # duration, padded — ts semantics differ across versions, so be generous.
            ts = [datetime.fromisoformat(h["ts"]) for h in rows if h.get("ts")]
            dur = max((h.get("duration_s") or 0) for h in rows) if rows else 0
            window = None
            if ts:
                window = (min(ts) - timedelta(seconds=dur + 600),
                          max(ts) + timedelta(seconds=dur + 600))
            pdir = sd / "phases" / f"P{pid}"
            md_reviews = {}
            rng_base = None
            for k in range(1, 8):
                f = pdir / f"code_review_r{k}.md"
                if f.exists():
                    fl, rb = parse_review_md(f.read_text())
                    md_reviews[k] = fl
                    if k == 1 and rb:
                        rng_base = rb
            use_base = rng_base or base
            files, kept, dropped = ([], 0, 0)
            method = "range"
            # ts is the row's END time (rows are appended when the agent returns), so a writer
            # session spans [ts - duration_s, ts] and its commit's author date lies inside it.
            wrows = [(datetime.fromisoformat(h["ts"]), h.get("duration_s") or 0)
                     for h in execs if h.get("ts")]
            wwindow = None
            if wrows:
                wwindow = (min(t - timedelta(seconds=d) for t, d in wrows) - timedelta(seconds=120),
                           max(t for t, _ in wrows) + timedelta(seconds=120))
            if commit_exists(repo, ps["reviewed_head"]) and commit_exists(repo, use_base):
                files, kept, dropped = phase_files(repo, use_base, ps["reviewed_head"], window)
                if not files and window:  # window too tight — fall back to the raw range
                    files, kept, dropped = phase_files(repo, use_base, ps["reviewed_head"], None)
            elif wwindow:
                method = "author-window"
                r1md = pdir / "code_review_r1.md"
                cited_r1: set[str] = set()
                if r1md.exists():
                    txt = r1md.read_text()
                    cited_r1 = set(PATH_RE.findall(txt)) | set(BARE_RE.findall(txt))
                tgt = ps.get("target") or "root"
                cwd = tgt if tgt in ("worker", "vscode-extension", "manual") else None
                files, kept = phase_files_by_author_window(repo, wwindow, cited_r1, cwd)
            else:
                method = "none"
            last_head[str(repo)] = ps["reviewed_head"]
            buckets = Counter(classify(rname, f) for f in files)
            # per-round findings: telemetry when present, markdown otherwise; join on id
            rounds = []
            for h in reviews:
                r = h.get("round", 1)
                md = {f["id"]: f for f in md_reviews.get(r, [])}
                tele = h.get("findings")
                merged = []
                if tele:
                    for f in tele:
                        m = md.get(f["id"], {})
                        merged.append({**f, "paths": m.get("paths", []), "bare": m.get("bare", []),
                                       "source": "telemetry"})
                else:
                    for f in md.values():
                        merged.append({"id": f["id"], "severity": f["severity"],
                                       "impact": f["impact"],
                                       "category": None, "anchor": f["anchor"],
                                       "summary": f["headline"], "paths": f["paths"],
                                       "bare": f["bare"], "source": "markdown"})
                # resolve cited files to risk levels: full paths first, bare names against the
                # phase's own files, then the repo tree
                tree = None
                for f in merged:
                    cited = set()
                    for p in f["paths"]:
                        cited.add(p)
                    for b in f["bare"]:
                        hits = [x for x in files if x.endswith("/" + b) or x == b]
                        if not hits:
                            if tree is None:
                                tree = git(repo, "ls-files").splitlines()
                            hits = [x for x in tree if x.endswith("/" + b) or x == b]
                            if len(hits) > 3:
                                hits = []
                        cited.update(hits)
                    cited_in_phase = sorted(c for c in cited if c in files)
                    f["cited"] = sorted(cited)
                    f["cited_in_phase"] = cited_in_phase
                    f["cited_levels"] = sorted(
                        {classify(rname, c) for c in (cited_in_phase or cited)})
                    f["late_cite"] = bool(cited) and not cited_in_phase
                refuted = []
                for e in execs:
                    if e.get("round") == r + 1 and e.get("refuted"):
                        refuted = e["refuted"]
                rounds.append({"round": r, "outcome": h.get("outcome"), "findings": merged,
                               "refuted": refuted, "summary": h.get("summary", "")[:300]})
            rec["phases"].append({
                "id": pid, "target": ps.get("target"), "repo": rname,
                "review_rounds": ps.get("review_rounds"),
                "executor_rounds": ps.get("executor_rounds"),
                "base": use_base, "head": ps["reviewed_head"], "commits": kept, "dropped": dropped,
                "method": method,
                "files": files, "buckets": dict(buckets),
                "level": max((LEVELS[b] for b in buckets), default=-1),
                "rounds": rounds,
            })
        co = sd / "close-out.md"
        if co.exists():
            rec["closeout"] = parse_closeout(co.read_text())
        out["slices"].append(rec)
        print(f"{sd.name}: {len(rec['phases'])} phases", file=sys.stderr)
    return out


# ---------------------------------------------------------------- report

LEVEL_NAME = {-1: "empty", 0: "low", 1: "test", 2: "medium", 3: "high"}


def phase_level(ph: dict, tests: str) -> str:
    lv = set(ph["buckets"])
    if tests == "low":
        lv = {("low" if b == "test" else b) for b in lv}
    else:
        lv = {("medium" if b == "test" else b) for b in lv}
    if not lv:
        return "empty"
    return max(lv, key=lambda b: LEVELS[b])


def is_blocking(f: dict, round_outcome: str) -> bool:
    if f.get("impact"):
        return f["impact"] == "blocking"
    # pre-telemetry: an `issues` round fixed every finding; count Blocker/Major as the fix work
    return round_outcome == "issues" and f.get("severity") in ("Blocker", "Major")


def report(corpus: dict, tests: str) -> None:
    slices = corpus["slices"]
    print(f"# Risk readout — {len(slices)} slices, tests={tests}\n")
    # 1. phases by level, with review outcomes
    tab = defaultdict(lambda: Counter())
    for s in slices:
        for ph in s["phases"]:
            lv = phase_level(ph, tests)
            tab[lv]["phases"] += 1
            r1 = next((r for r in ph["rounds"] if r["round"] == 1), None)
            if r1 and r1["outcome"] == "issues":
                tab[lv]["r1_issues"] += 1
            if r1 and r1["outcome"] == "critical":
                tab[lv]["r1_critical"] += 1
            if (ph.get("review_rounds") or 1) >= 2:
                tab[lv]["second_round"] += 1
            blk = sum(1 for r in ph["rounds"] for f in r["findings"]
                      if is_blocking(f, r["outcome"]))
            ref = sum(len(r["refuted"]) for r in ph["rounds"])
            tab[lv]["blocking_findings"] += blk
            tab[lv]["refuted"] += ref
            tab[lv]["files"] += len(ph["files"])
    print("## Phases by risk level (level = max over touched files)\n")
    print("| level | phases | files | r1 issues | r1 critical | 2nd round "
          "| blocking findings | refuted |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|")
    for lv in ("low", "medium", "high", "empty"):
        c = tab[lv]
        print(f"| {lv} | {c['phases']} | {c['files']} | {c['r1_issues']} | {c['r1_critical']} | "
              f"{c['second_round']} | {c['blocking_findings']} | {c['refuted']} |")
    # 2. pure-bucket phases (all files in one bucket)
    print("\n## Phases whose files all sit in one bucket\n")
    print("| bucket | phases | r1 issues | 2nd round | blocking findings |")
    print("|---|---:|---:|---:|---:|")
    pure = defaultdict(Counter)
    for s in slices:
        for ph in s["phases"]:
            if len(ph["buckets"]) == 1:
                b = next(iter(ph["buckets"]))
                pure[b]["phases"] += 1
                r1 = next((r for r in ph["rounds"] if r["round"] == 1), None)
                if r1 and r1["outcome"] == "issues":
                    pure[b]["r1_issues"] += 1
                if (ph.get("review_rounds") or 1) >= 2:
                    pure[b]["second_round"] += 1
                pure[b]["blocking"] += sum(1 for r in ph["rounds"] for f in r["findings"]
                                           if is_blocking(f, r["outcome"]))
    for b in ("low", "test", "medium", "high"):
        c = pure[b]
        print(f"| {b} | {c['phases']} | {c['r1_issues']} | {c['second_round']} | {c['blocking']} |")
    # 3. blocking findings by the level of the files they cite
    print("\n## Blocking findings by the level of the files they cite\n")
    cite = Counter()
    cat = defaultdict(Counter)
    for s in slices:
        for ph in s["phases"]:
            for r in ph["rounds"]:
                for f in r["findings"]:
                    if not is_blocking(f, r["outcome"]):
                        continue
                    lv = f.get("cited_levels") or ["uncited"]
                    if tests == "low":
                        lv = [("low" if b == "test" else b) for b in lv]
                    key = (max(lv, key=lambda b: LEVELS.get(b, -1))
                           if lv != ["uncited"] else "uncited")
                    cite[key] += 1
                    cat[key][f.get("category") or "?"] += 1
    for k, v in sorted(cite.items(), key=lambda kv: -kv[1]):
        print(f"- {k}: {v}  ({dict(cat[k])})")
    # 4. low-level phases that had blocking findings — the exposure list
    print("\n## Exposure: phases at level `low` with an `issues` round or a blocking finding\n")
    for s in slices:
        for ph in s["phases"]:
            if phase_level(ph, tests) != "low":
                continue
            blk = [(r["round"], f) for r in ph["rounds"] for f in r["findings"]
                   if is_blocking(f, r["outcome"])]
            iss = [r for r in ph["rounds"] if r["outcome"] in ("issues", "critical")]
            if not blk and not iss:
                continue
            print(f"### {s['slice']} P{ph['id']} — {ph['target']} · {len(ph['files'])} files "
                  f"{dict(ph['buckets'])} · rounds {ph['review_rounds']}")
            for rnd, f in blk:
                refd = "REFUTED" if f["id"] in next(
                    (r["refuted"] for r in ph["rounds"] if r["round"] == rnd), []) else ""
                print(f"- r{rnd} {f['id']} {f.get('severity')} · {f.get('anchor')} {refd}: "
                      f"{(f.get('summary') or '')[:160]}  "
                      f"cites={f.get('cited_in_phase') or f.get('cited')}")
            print()
    # 5. close-out: operator-actioned entries by role and by the level of the cited files
    print("\n## Close-out entries — what the operator did, by provenance role\n")
    tab2 = defaultdict(Counter)
    for s in slices:
        for e in s.get("closeout") or []:
            tab2[e["role"]][e["class"]] += 1
    classes = ["actioned", "closed", "in-run", "blank", "other", "struck-other"]
    print("| role | " + " | ".join(classes) + " |")
    print("|---|" + "---:|" * len(classes))
    for role, c in sorted(tab2.items(), key=lambda kv: -sum(kv[1].values())):
        print(f"| {role} | " + " | ".join(str(c[k]) for k in classes) + " |")
    print("\n### Operator-actioned entries (card / fix / fold) with a code-reviewer "
          "or test-agent provenance\n")
    for s in slices:
        for e in s.get("closeout") or []:
            if e["class"] != "actioned" or e["role"] not in ("code-reviewer", "test-agent"):
                continue
            ph = next((p for p in s["phases"] if p["id"] == e["phase"]), None)
            lv = phase_level(ph, tests) if ph else "?"
            repo = ph["repo"] if ph else "KubeCoder"
            cl = sorted({classify(repo, p) for p in e["paths"]}) or ["-"]
            print(
                f"- {s['slice']} {e['id']} [{e['role']} P{e['phase']} F{e['finding']}] "
                f"phase={lv} cites={cl} · {e['severity']} · {e['headline'][:110]}\n"
                f"    → {e['disposition'][:120]}"
                if not e['struck'] else
                f"- {s['slice']} {e['id']} [{e['role']} P{e['phase']} F{e['finding']}] "
                f"phase={lv} cites={cl} · {e['severity']} · {e['headline'][:110]}\n"
                f"    → struck: {e['struck_reason'][:120]}")
    print("\n### Entries the classifier could not place (read by hand)\n")
    for s in slices:
        for e in s.get("closeout") or []:
            if e["class"] in ("other", "struck-other"):
                print(f"- {s['slice']} {e['id']} [{e['role']}] {e['headline'][:90]}\n    → "
                      f"{(e['disposition'] or e['struck_reason'] or '')[:140]}")
    # 6. late findings
    print("\n## Late findings — appended phases, test rounds, consult outcomes, "
          "cross-phase cites\n")
    for s in slices:
        late = []
        if s["appended_phases"]:
            late.append(f"appended={s['appended_phases']}")
        if (s.get("test_rounds") or 0) > 1:
            late.append(f"test_rounds={s['test_rounds']}")
        for c in s["consults"]:
            if c["outcome"] not in ("complete", "merge", "continue", "proceed", None):
                late.append(f"consult:{c['outcome']}")
        for ph in s["phases"]:
            for r in ph["rounds"]:
                for f in r["findings"]:
                    if is_blocking(f, r["outcome"]) and f.get("late_cite"):
                        late.append(f"P{ph['id']} r{r['round']} {f['id']} cites outside "
                                    f"the phase diff: {f['cited'][:3]}")
        if late:
            print(f"- {s['slice']}: " + "; ".join(late))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("--since", default="063")
    e.add_argument("--out", default="risk-corpus.json")
    r = sub.add_parser("report")
    r.add_argument("--in", dest="inp", default="risk-corpus.json")
    r.add_argument("--tests", choices=["low", "medium"], default="medium")
    a = ap.parse_args()
    if a.cmd == "extract":
        Path(a.out).write_text(json.dumps(extract(a.since), indent=1))
    else:
        report(json.loads(Path(a.inp).read_text()), a.tests)


if __name__ == "__main__":
    main()
