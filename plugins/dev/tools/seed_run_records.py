#!/usr/bin/env python3
"""Seed the plugin's run records with the slices run before the records were kept.

The run loop and the plan loop keep each slice's run records in the installed
plugin's data folder, `<data>/runs/<SpecRepo>/<NNN_slug>/` (run_loop's
`run_records_dir`): `state.json` and `plan_state.json`, whole copies of the
slice's state files. A slice that ran before the loops kept them has its state
files only in its spec repo. This script copies them into the place a live run
keeps them, so the labeller reads the history as it reads a live run's
records; and with them the history's groups, the prototype's `adopted/*.toml`
(each group a name, a summary and its slices), into `<data>/groups/`.

Beside each slice's state files it writes the slice's `slice.json`, the facts
the loops keep of a live run, read from the slice folder: its card and title
(`slice.md`), its plan's size (`plan.md` less the phases the run appended, and
`verification.json`), the plan review's findings per round and the code
review's per phase and round where the history rows carry none, the
close-out's fates (`close-out.json`), and the commit that filed the slice:
the spec repo's first commit that added its `slice.md` (`filing_commit`, its
hash, subject and author time; t17-labeller-2.md D8), which the labeller
finds the slice's triage session by. A fact the folder does not hold, or
holds in a shape that does not read, is left out, never guessed.

    seed_run_records.py [--groups DIR] [--data-dir DIR] [--dry-run] SPEC_REPO...

  SPEC_REPO     a spec repo's root, holding `slices/<status>/<NNN_slug>/`; every
                status folder there is read (`completed` first).
  --groups DIR  copy every `*.toml` in DIR, checked first, to `<data>/groups/`.
  --data-dir    the data folder; the installed plugin's (`plugin_data_dir`)
                when not given.
  --dry-run     write nothing; report what would be written.

Run it once in an environment that holds the spec repos — a checkout or a
fresh clone: a completed slice's state files are committed in its spec repo.
It never replaces a record that is there: a record the driver keeps of a live
run, or an earlier seed's, wins, and is counted as kept. So it can be re-run,
and a re-run adds only what the first could not see (a slice that finished on
the old plugin since), and the filing commit to a slice.json an earlier seed
wrote without one: that key alone, the rest of the file as it is. The groups
are hand-edited, so their copies are replaced on every run.

Exit 0 when everything given was read, 1 when anything was reported failed or
skipped for a fault, 2 when no data folder can be told (before anything is
read).
"""

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import close_out  # noqa: E402
import plan_loop  # noqa: E402
import run_loop  # noqa: E402
from run_loop import run_records_dir, spec_repo_name  # noqa: E402

# The state files a live run keeps in its records, under the same names.
STATE_FILES = ("state.json", "plan_state.json")
# The status folder whose copy of a slice found twice wins: a completed
# slice's state is its last. The others follow by name.
FIRST_STATUS = "completed"


def place_new(path: Path, data: bytes) -> bool:
    """`data` whole at `path` unless a file is there: written to a temp file
    beside it, then linked into place, which never replaces a file — a driver
    writing the same record meanwhile wins. True when written, False when a
    file was there. Where the filesystem has no hard links, renamed in where
    the name is free."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        try:
            os.link(tmp, path)
            return True
        except FileExistsError:
            return False
        except OSError:
            if path.exists():
                return False
            os.replace(tmp, path)
            return True
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp)


def place_over(path: Path, data: bytes) -> None:
    """`data` whole at `path`, over what is there, renamed into place."""
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp)


def status_order(slices: Path) -> list[Path]:
    """The status folders under `slices/`, `completed` first, then by name."""
    folders = sorted(p for p in slices.iterdir() if p.is_dir())
    return sorted(folders, key=lambda p: p.name != FIRST_STATUS)


def read_state(path: Path) -> tuple[bytes | None, str | None]:
    """(the file's bytes, None) when it is a JSON object, else (None, why)."""
    try:
        raw = path.read_bytes()
    except OSError as e:
        return None, f"unreadable ({e.strerror or e})"
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return None, f"not JSON ({e})"
    if not isinstance(data, dict):
        return None, f"not a JSON object (a {type(data).__name__})"
    return raw, None


REVIEW_RE = re.compile(r"^review_result_r(\d+)\.json$")
PLAN_REVIEW_RE = re.compile(r"^plan_review_r(\d+)\.json$")


def _rows(slice_dir: Path, name: str) -> list[dict]:
    """The history rows of a state file, none where it does not read."""
    state = run_loop._read_json(slice_dir / name)
    rows = state.get("history") if isinstance(state, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _by_round(found: dict) -> dict:
    return dict(sorted(found.items(), key=lambda kv: int(kv[0])))


def plan_review_findings(slice_dir: Path) -> dict:
    """round → the findings its plan_review_rN.json holds
    (`plan_loop.review_findings`), each round whose plan-reviewer row in
    plan_state.json carries none; a round with no file, or none in it,
    is left out."""
    kept = {str(r.get("round")) for r in _rows(slice_dir, "plan_state.json")
            if r.get("role") == "plan-reviewer" and r.get("findings")}
    found = {}
    for path in slice_dir.iterdir():
        m = PLAN_REVIEW_RE.match(path.name)
        if m and str(int(m.group(1))) not in kept:
            findings = plan_loop.review_findings(path)
            if findings:
                found[str(int(m.group(1)))] = findings
    return _by_round(found)


def code_review_findings(slice_dir: Path) -> dict:
    """phase id → round → the `findings` of
    `phases/P<id>/review_result_rN.json`, as the reviewer gave them, each
    round whose code-reviewer row in state.json carries none; a round whose
    file holds none is left out."""
    kept = {(str(r.get("phase")), str(r.get("round")))
            for r in _rows(slice_dir, "state.json")
            if r.get("role") == "code-reviewer" and r.get("findings")}
    phases = slice_dir / "phases"
    found: dict[str, dict] = {}
    if not phases.is_dir():
        return found
    for folder in sorted(p for p in phases.iterdir() if p.is_dir()):
        if not folder.name.startswith("P"):
            continue
        pid = folder.name[1:]
        for path in folder.iterdir():
            m = REVIEW_RE.match(path.name)
            if not m or (pid, str(int(m.group(1)))) in kept:
                continue
            verdict = run_loop._read_json(path)
            findings = verdict.get("findings") if isinstance(verdict, dict) else None
            if isinstance(findings, list) and findings:
                found.setdefault(pid, {})[str(int(m.group(1)))] = findings
    return {pid: _by_round(rounds) for pid, rounds in found.items()}


FILING_KEY = "filing_commit"


def slice_md_adds(repo: Path) -> dict[str, dict]:
    """slice folder → the first commit that added a `slice.md` under it in
    the spec repo's history: `{"hash", "subject", "authored_at"}`, as the
    prototype's `_slice_md_adds` reads it — without rename detection, which
    a partial clone would fetch blobs for, so a moved folder's first add is
    its filing. None where git cannot read the history."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "log", "--no-renames", "--diff-filter=A",
             "--format=@@%H%x09%aI%x09%s", "--name-only", "--", "slices"],
            capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    found: dict[str, dict] = {}
    commit = None
    for line in out.stdout.splitlines():
        if line.startswith("@@"):
            sha, _, rest = line[2:].partition("\t")
            when, _, subject = rest.partition("\t")
            commit = {"hash": sha, "subject": subject, "authored_at": when}
        elif line.endswith("/slice.md") and commit is not None:
            # git log is newest first: the oldest add stays
            found[line.split("/")[-2]] = commit
    return found


def slice_facts(slice_dir: Path, filing: dict | None = None) -> dict:
    """The facts a live run's slice.json holds, as far as the slice folder
    tells them: `slice`, `card` and `title`, `plan`, the two findings keys
    and `close_out`, and the write's stamp; and `filing_commit`, the commit that
    filed it, where its spec repo's history names one."""
    facts: dict = {"slice": slice_dir.name, **run_loop.slice_card_and_title(slice_dir)}
    state = run_loop._read_json(slice_dir / "state.json")
    appended = state.get("appended_phases") if isinstance(state, dict) else None
    size = run_loop.plan_size(slice_dir, appended if isinstance(appended, list) else ())
    if size:
        facts["plan"] = size
    for key, found in (("plan_review_findings", plan_review_findings(slice_dir)),
                       ("code_review_findings", code_review_findings(slice_dir))):
        if found:
            facts[key] = found
    store = run_loop._read_json(slice_dir / close_out.STORE_NAME)
    if isinstance(store, dict) and isinstance(store.get("entries"), list):
        counts = close_out.fates(store)
        if counts is not None:
            facts["close_out"] = counts
    if filing:
        facts[FILING_KEY] = dict(filing)
    return run_loop.stamped(facts)


def add_filing(dest: Path, filing: dict | None, dry_run: bool) -> bool:
    """The filing commit into a slice.json that is there and has none, that
    key alone: whether it was added (or, on a dry run, would be)."""
    if not filing:
        return False
    try:
        doc = json.loads(dest.read_bytes())
    except (OSError, ValueError):
        return False
    if not isinstance(doc, dict) or doc.get(FILING_KEY):
        return False
    if not dry_run:
        doc[FILING_KEY] = dict(filing)
        try:
            place_over(dest, (json.dumps(doc, indent=2) + "\n").encode())
        except OSError:
            return False
    return True


def seed_facts(slice_dir: Path, records: Path, dry_run: bool,
               filing: dict | None = None) -> tuple[str, str | None]:
    """The slice's slice.json into its records unless one is there:
    (`written`, `kept`, `filed` — kept, its filing commit added — or
    `failed`, the card it names or why it failed)."""
    try:
        facts = slice_facts(slice_dir, filing)
    except Exception as e:
        return "failed", f"not read ({type(e).__name__}: {e})"
    dest = records / run_loop.SLICE_FACTS
    if dest.exists():
        return ("filed" if add_filing(dest, filing, dry_run) else "kept"), None
    if not dry_run:
        try:
            records.mkdir(parents=True, exist_ok=True)
            if not place_new(dest, (json.dumps(facts, indent=2) + "\n").encode()):
                return "kept", None
        except OSError as e:
            return "failed", f"not written to {dest} ({e})"
    return "written", facts.get("card")


def seed_repo(repo: Path, data_dir: Path, dry_run: bool) -> tuple[list[str], bool]:
    """Copy one spec repo's state files into the records: (the lines to print,
    whether anything failed)."""
    slices = repo / "slices"
    if not slices.is_dir():
        return [f"{repo}: not a spec repo (no slices/ folder) — skipped"], True
    root = repo.resolve()
    name = spec_repo_name(root)
    seen: dict[str, str] = {}       # slice folder name → its status folder
    folders = copied = kept = skipped = 0
    facts_written = facts_kept = cards = filed = added = 0
    notes: list[str] = []
    failed = False
    adds = slice_md_adds(repo)
    if adds is None:
        adds = {}
        notes.append(f"  {name}: git cannot read its history — no filing commits")
    for status in status_order(slices):
        for slice_dir in sorted(p for p in status.iterdir() if p.is_dir()):
            files = [slice_dir / f for f in STATE_FILES if (slice_dir / f).is_file()]
            if not files:
                continue
            folders += 1
            if slice_dir.name in seen:
                notes.append(f"  {slice_dir.name} is in both {seen[slice_dir.name]}/ "
                             f"and {status.name}/: copied {seen[slice_dir.name]}/'s, "
                             f"not {status.name}/'s")
                continue
            seen[slice_dir.name] = status.name
            records = run_records_dir(slice_dir, data_dir)
            if records is None:
                skipped += len(files)
                failed = True
                notes.append(f"  {status.name}/{slice_dir.name}: its records folder "
                             "cannot be told — skipped")
                continue
            filing = adds.get(slice_dir.name)
            outcome, said = seed_facts(slice_dir, records, dry_run, filing)
            if outcome == "failed":
                failed = True
                notes.append(f"  {status.name}/{slice_dir.name}/{run_loop.SLICE_FACTS}: "
                             f"{said} — skipped")
            elif outcome in ("kept", "filed"):
                facts_kept += 1
                added += outcome == "filed"
            else:
                facts_written += 1
                cards += said is not None
                filed += filing is not None
            for src in files:
                rel = f"{status.name}/{slice_dir.name}/{src.name}"
                raw, why = read_state(src)
                if raw is None:
                    skipped += 1
                    failed = True
                    notes.append(f"  {rel}: {why} — skipped")
                    continue
                dest = records / src.name
                if dry_run:
                    if dest.exists():
                        kept += 1
                    else:
                        copied += 1
                    continue
                try:
                    records.mkdir(parents=True, exist_ok=True)
                    if place_new(dest, raw):
                        copied += 1
                    else:
                        kept += 1
                except OSError as e:
                    skipped += 1
                    failed = True
                    notes.append(f"  {rel}: not written to {dest} ({e}) — skipped")
    verb = "to copy" if dry_run else "copied"
    adding = "to add" if dry_run else "added"
    head = (f"{name} ({repo}): {folders} slices seen, {copied} files {verb}, "
            f"{kept} kept (already there), {skipped} skipped; {facts_written} "
            f"{run_loop.SLICE_FACTS} {verb} ({cards} naming a card, {filed} its filing "
            f"commit), {facts_kept} kept ({added} its filing commit {adding})")
    return [head, *notes], failed


def check_groups(raw: bytes) -> str | None:
    """None when `raw` is a groups file the labeller can read, else why not:
    a string `spec_repo` and `project` a list of tables, each with a string
    `name`, a string `summary` and `slices` a list of strings."""
    try:
        doc = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        return f"not TOML ({e})"
    if not isinstance(doc.get("spec_repo"), str):
        return "no string `spec_repo`"
    projects = doc.get("project")
    if not isinstance(projects, list):
        return "no `[[project]]` list"
    for n, project in enumerate(projects, 1):
        if not isinstance(project, dict):
            return f"project {n} is not a table"
        for key in ("name", "summary"):
            if not isinstance(project.get(key), str):
                return f"project {n} has no string `{key}`"
        members = project.get("slices")
        if not isinstance(members, list) or not all(isinstance(s, str) for s in members):
            return f"project {n} ({project['name']}) has no `slices` list of strings"
    return None


def seed_groups(groups: Path, data_dir: Path, dry_run: bool) -> tuple[list[str], bool]:
    """Copy the groups files, checked, to `<data>/groups/`, over earlier
    copies: (the lines to print, whether anything failed)."""
    if not groups.is_dir():
        return [f"groups ({groups}): not a directory — skipped"], True
    files = sorted(p for p in groups.glob("*.toml") if p.is_file())
    if not files:
        return [f"groups ({groups}): no *.toml files — nothing copied"], True
    target = data_dir / "groups"
    copied = refused = 0
    notes: list[str] = []
    for src in files:
        try:
            raw = src.read_bytes()
        except OSError as e:
            refused += 1
            notes.append(f"  {src.name}: unreadable ({e}) — not copied")
            continue
        why = check_groups(raw)
        if why is not None:
            refused += 1
            notes.append(f"  {src.name}: {why} — not copied")
            continue
        if not dry_run:
            try:
                target.mkdir(parents=True, exist_ok=True)
                place_over(target / src.name, raw)
            except OSError as e:
                refused += 1
                notes.append(f"  {src.name}: not written ({e}) — not copied")
                continue
        copied += 1
    verb = "to copy" if dry_run else "copied"
    head = (f"groups ({groups}): {len(files)} files, {copied} {verb}, "
            f"{refused} refused")
    return [head, *notes], refused > 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Copy old slices' state files, and the history's groups, "
                    "into the plugin's run records. Never replaces a record.")
    parser.add_argument("spec_repos", nargs="+", type=Path, metavar="SPEC_REPO")
    parser.add_argument("--groups", type=Path, metavar="DIR",
                        help="a folder of groups *.toml files to copy")
    parser.add_argument("--data-dir", type=Path, metavar="DIR",
                        help="the data folder (default: the installed plugin's)")
    parser.add_argument("--dry-run", action="store_true",
                        help="write nothing; report what would be written")
    args = parser.parse_args(argv)

    data_dir = args.data_dir or run_loop.plugin_data_dir()
    if data_dir is None:
        print("seed_run_records: the installed plugin's data folder cannot be told "
              "(no install of it in installed_plugins.json); pass --data-dir",
              file=sys.stderr)
        return 2
    data_dir = Path(data_dir)

    failed = False
    for repo in args.spec_repos:
        lines, bad = seed_repo(repo, data_dir, args.dry_run)
        print("\n".join(lines))
        failed = failed or bad
    if args.groups is not None:
        lines, bad = seed_groups(args.groups, data_dir, args.dry_run)
        print("\n".join(lines))
        failed = failed or bad
    where = "would be" if args.dry_run else "are"
    print(f"records {where} in {data_dir / 'runs'}"
          + (f", groups in {data_dir / 'groups'}" if args.groups is not None else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
