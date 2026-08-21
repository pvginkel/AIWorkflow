#!/usr/bin/env python3
"""File a residual-sweep slice from Solution Known tracker cards — mechanically.

/dev:triage marks a card **Solution Known** — change fully decided, impact plain,
its acceptance criteria writable from the card text alone — by recording those
criteria on the card. This script turns a batch of such cards into a run-ready
slice — the planned artifacts /dev:plan-slice would otherwise produce — so the
batch skips planning entirely and goes straight to /dev:run-slice
(${CLAUDE_PLUGIN_ROOT}/docs/residual-sweep.md):

    slices/NNN_<slug>/
      slice.md            the record: every card, quoted verbatim
      plan.md             one phase per payload item
      verification.json   one item per acceptance criterion

The payload is JSON the triage session assembles — the session has the tracker
access; this script touches no network:

    {
      "slug": "residual_sweep",            // optional (this is the default)
      "items": [
        {
          "card": 449,                      // tracker card number
          "card_name": "<card title>",
          "card_url": "<link to the card>",
          "title": "<phase title, imperative>",
          "target": "root",                 // kc component or ../SiblingRepo
          "body": "<card description, verbatim markdown>",
          "acceptance_criteria": ["<outcome-level criterion>", ...]
        }
      ]
    }

One item per card normally; a multi-item card whose bullets need different
targets becomes several items citing the same card number.

Guard rails:

  * Fewer than MIN_CARDS distinct cards is refused without --force — a sweep
    amortises the run loop's fixed overhead (consult, test phase, doc phase),
    and a tiny batch wastes it. Labelled cards simply accumulate.
  * More than MAX_PHASES items is refused without --force — a sweep is a slice
    and is sized like one, so a larger batch splits by target into several
    sweeps. The floor counts cards, the ceiling counts phases.
  * The spec repo must be on main/master: the tree is shared, and a parallel
    run's test/doc phase may be holding it on a phase branch.
  * The generated plan is validated twice — parse_plan() in-process, then the
    documented `run_loop.py run <dir> --dry-run` (target resolution needs the
    invoking repo's manifest). A dry-run failure leaves the folder on disk,
    unstaged, for inspection; the burned slice number is a harmless gap.

Like close_slice.py this stages by name and does not commit — the triage
session commits, archives the swept cards, and files the slice card.

Usage:
    sweep_slice.py <payload.json> [--force]

Exit codes: 0 filed · 2 usage/precondition/validation error · 1 unexpected.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import project_config  # noqa: E402
from run_loop import parse_plan  # noqa: E402

MIN_CARDS = 5
MAX_PHASES = 10
DEFAULT_SLUG = "residual_sweep"
SLUG_RE = re.compile(r"^[a-z0-9_]+$")
README_WIDTH = 98


class Precondition(Exception):
    """A precondition failure — exit 2."""


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------

def load_payload(path: Path) -> tuple[str, list[dict]]:
    """Parse and validate the payload; returns (slug, items)."""
    try:
        data = json.loads(path.read_text())
    except OSError as e:
        raise Precondition(f"cannot read payload: {e}") from e
    except json.JSONDecodeError as e:
        raise Precondition(f"payload is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise Precondition("payload must be a JSON object with an `items` list")

    slug = data.get("slug", DEFAULT_SLUG)
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        raise Precondition(f"slug must match {SLUG_RE.pattern}: {slug!r}")

    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise Precondition("payload `items` must be a non-empty list")

    for n, item in enumerate(items, 1):
        where = f"items[{n - 1}]"
        if not isinstance(item, dict):
            raise Precondition(f"{where} is not an object")
        card = item.get("card")
        if not isinstance(card, int) or card <= 0:
            raise Precondition(f"{where}.card must be a positive card number")
        for key in ("card_name", "card_url", "title", "target", "body"):
            value = item.get(key)
            if not isinstance(value, str) or not value.strip():
                raise Precondition(f"{where}.{key} must be a non-empty string")
        for key in ("card_name", "title", "target"):
            if "\n" in item[key].strip():
                raise Precondition(f"{where}.{key} must be a single line")
        acs = item.get("acceptance_criteria")
        if (not isinstance(acs, list) or not acs
                or not all(isinstance(a, str) and a.strip() for a in acs)):
            raise Precondition(
                f"{where}.acceptance_criteria must be a non-empty list of "
                "non-empty strings — a card whose criteria cannot be written "
                "is not Solution Known")
    return slug, items


# ---------------------------------------------------------------------------
# Artifact generation
# ---------------------------------------------------------------------------

def blockquote(text: str) -> str:
    """Markdown-blockquote verbatim card text. This is also what neutralises
    it for the plan parser: `> ###` is not a phase heading and `> Target:` is
    not a Target line."""
    lines = text.replace("\r\n", "\n").strip().splitlines()
    return "\n".join("> " + line if line.strip() else ">" for line in lines)


def _criteria_ids(items: list[dict]) -> list[list[str]]:
    """Per item, its verification ids — V01.. sequential across the payload."""
    out, n = [], 0
    for item in items:
        ids = [f"V{n + k + 1:02d}" for k in range(len(item["acceptance_criteria"]))]
        out.append(ids)
        n += len(ids)
    return out


def _id_range(ids: list[str]) -> str:
    return ids[0] if len(ids) == 1 else f"{ids[0]}–{ids[-1]}"


def build_artifacts(num: str, items: list[dict]) -> dict[str, str]:
    """The three slice files, keyed by filename."""
    cards = sorted({item["card"] for item in items})
    card_list = " ".join(f"#{c}" for c in cards)
    title = f"Residual sweep: {len(cards)} Solution Known card(s)"
    vids = _criteria_ids(items)

    plan = [f"# Slice {num} — {title}", "", "## Requirements / rulings", ""]
    plan.append(
        "- Filed mechanically by /dev:triage's residual sweep "
        "(${CLAUDE_PLUGIN_ROOT}/tools/sweep_slice.py) from the Solution Known cards "
        "quoted verbatim in slice.md. Acceptance criteria were authored at "
        "triage from the card text alone; verification.json holds them.")
    for k, item in enumerate(items):
        plan.append(
            f"- R{k + 1}. **(#{item['card']}) {item['card_name'].strip()}** — "
            f"P{k + 1}, criteria {_id_range(vids[k])}.")
    plan.append(
        "- A phase's scope is exactly what its card records. If the fix turns "
        "out to touch concurrency, storage, a wire contract, or anything the "
        "card does not describe, the card was mislabelled — bail with a "
        "question rather than improvise.")
    plan += ["", "## Ordering constraints", "",
             "None — cards are selected for independence; document order is "
             "arbitrary.", ""]
    for k, item in enumerate(items):
        plan += [f"### P{k + 1} — {item['title'].strip()}", "",
                 f"Target: {item['target'].strip()}", "",
                 f"Card #{item['card']} — {item['card_name'].strip()} "
                 f"({item['card_url'].strip()}). Criteria: {_id_range(vids[k])}.",
                 "", blockquote(item["body"]), ""]
    plan += ["## Not in scope", "",
             "- Anything not recorded on a swept card — neighbourhood cleanups "
             "ride their own cards.", ""]

    record = [f"# Slice {num} — {title}", ""]
    record.append(
        "Filed mechanically at triage by ${CLAUDE_PLUGIN_ROOT}/tools/sweep_slice.py — "
        "small, low-risk residuals whose fix is fully described by their "
        "cards. Acceptance criteria were authored at triage from the card "
        "text alone and live in verification.json; plan.md was generated, one "
        "phase per item, and /dev:plan-slice is deliberately skipped "
        "(the dev plugin's residual-sweep.md).")
    record += ["", "## Requirements", ""]
    for k, item in enumerate(items):
        record += [f"{k + 1}. **(#{item['card']}) {item['card_name'].strip()}** "
                   f"({item['card_url'].strip()})", "",
                   blockquote(item["body"]), "",
                   f"   Acceptance criteria ({_id_range(vids[k])}):"]
        record += [f"   - {a.strip()}" for a in item["acceptance_criteria"]]
        record.append("")
    record += ["## Cards subsumed", "", card_list, ""]

    verification = {"items": []}
    for k, item in enumerate(items):
        for vid, criterion in zip(vids[k], item["acceptance_criteria"],
                                  strict=True):
            verification["items"].append({
                "id": vid,
                "area": f"card #{item['card']} (P{k + 1})",
                "description": criterion.strip(),
                "verdict": None,
                "rationale": "",
                "evidence": [],
            })

    return {
        "slice.md": "\n".join(record),
        "plan.md": "\n".join(plan),
        "verification.json": json.dumps(verification, indent=2) + "\n",
    }


def pending_bullet(num: str, items: list[dict]) -> list[str]:
    """The README `## Pending` entry, wrapped like its neighbours."""
    cards = sorted({item["card"] for item in items})
    text = (f"- **{num}** — Residual sweep: {len(cards)} Solution Known "
            f"card(s) ({' '.join(f'#{c}' for c in cards)}).")
    lines, line = [], ""
    for word in text.split(" "):
        if line and len(line) + 1 + len(word) > README_WIDTH:
            lines.append(line)
            line = "  " + word
        else:
            line = word if not line else f"{line} {word}"
    lines.append(line)
    return lines


def insert_pending(readme: str, bullet: list[str]) -> str:
    """Append the bullet at the end of the `## Pending` section's list."""
    lines = readme.splitlines()
    try:
        start = lines.index("## Pending")
    except ValueError:
        raise Precondition("README has no `## Pending` section") from None
    end = len(lines)
    for k in range(start + 1, len(lines)):
        if lines[k].startswith("## "):
            end = k
            break
    last = end - 1
    while last > start and not lines[last].strip():
        last -= 1
    return "\n".join(lines[:last + 1] + bullet + lines[last + 1:]) + "\n"


# ---------------------------------------------------------------------------
# Filing
# ---------------------------------------------------------------------------

def _git(spec: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(spec), *args],
                          capture_output=True, text=True)


def spec_repo_for(code_root: Path) -> Path:
    try:
        cfg = project_config.load(code_root)
    except project_config.ConfigError as e:
        raise Precondition(str(e)) from None
    if cfg.spec_repo is None:
        raise Precondition(f"no `spec_repo` in {cfg.path}")
    if not (cfg.spec_repo / "slices").is_dir():
        raise Precondition(f"`spec_repo` in {cfg.path} resolves to "
                           f"{cfg.spec_repo}, which has no slices/ tree")
    return cfg.spec_repo


def assert_on_main(spec: Path) -> None:
    result = _git(spec, "symbolic-ref", "--quiet", "--short", "HEAD")
    branch = result.stdout.strip()
    if branch not in ("main", "master"):
        raise Precondition(
            f"the spec repo is on {branch or 'a detached HEAD'!s}, not main — "
            "a parallel run's test/doc phase may be holding the shared tree "
            "on its phase branch. Retry after it lands; never switch the "
            "branch out from under it.")


def allocate(spec: Path) -> str:
    script = Path(__file__).resolve().parent / "allocate-next-slice.sh"
    result = subprocess.run([str(script), str(spec)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise Precondition("allocate-next-slice.sh failed: "
                           + (result.stderr or result.stdout).strip())
    return result.stdout.strip()


def dry_run(slice_dir: Path, code_root: Path) -> None:
    """The documented drivability check — parse + target resolution, nothing
    touched. Module-level so tests can stub it (a real run needs `kc`)."""
    loop = Path(__file__).resolve().parent / "run_loop.py"
    result = subprocess.run(
        [sys.executable, str(loop), "run", str(slice_dir), "--dry-run"],
        cwd=str(code_root), capture_output=True, text=True)
    if result.returncode != 0:
        raise Precondition(
            f"run_loop.py --dry-run rejected the generated plan:\n"
            f"{(result.stdout + result.stderr).strip()}\n"
            f"The folder is left at {slice_dir} (unstaged) for inspection — "
            "fix the payload and re-run, then delete the folder; the burned "
            "number is a harmless gap.")


def file_sweep(payload_path: Path, code_root: Path, force: bool = False) -> Path:
    slug, items = load_payload(payload_path)
    cards = sorted({item["card"] for item in items})
    if len(cards) < MIN_CARDS and not force:
        raise Precondition(
            f"only {len(cards)} distinct card(s) — a sweep amortises the run "
            f"loop's fixed overhead, so fewer than {MIN_CARDS} accumulate for "
            "the next triage pass instead (--force overrides).")
    if len(items) > MAX_PHASES and not force:
        raise Precondition(
            f"{len(items)} phases — a sweep is a slice and sized like one; "
            f"more than {MAX_PHASES} split by target into several sweeps of "
            "five to ten (--force overrides).")

    spec = spec_repo_for(code_root)
    assert_on_main(spec)
    readme_path = spec / "README.md"
    if not readme_path.is_file():
        raise Precondition(f"{readme_path} does not exist")

    num = allocate(spec)
    slice_dir = spec / "slices" / f"{num}_{slug}"
    if slice_dir.exists():
        raise Precondition(f"{slice_dir} already exists")

    artifacts = build_artifacts(num, items)
    phases, errors = parse_plan(artifacts["plan.md"])
    if errors or len(phases) != len(items):
        raise RuntimeError("generated plan does not parse — generator bug:\n"
                           + "\n".join(errors))

    slice_dir.mkdir(parents=True)
    for name, text in artifacts.items():
        (slice_dir / name).write_text(text)

    dry_run(slice_dir, code_root)

    readme_path.write_text(insert_pending(readme_path.read_text(),
                                          pending_bullet(num, items)))
    to_stage = ["README.md"] + [
        str((slice_dir / name).relative_to(spec)) for name in artifacts]
    result = _git(spec, "add", "--", *to_stage)
    if result.returncode != 0:
        raise Precondition(f"git add failed: {result.stderr.strip()}")

    print(f"filed slice {num}_{slug}: {len(phases)} phase(s), "
          f"{len(cards)} card(s) ({' '.join(f'#{c}' for c in cards)})")
    print(f"  {slice_dir}")
    print("  staged by name: " + " ".join(to_stage))
    print()
    print("the session's half, now:")
    print("  1. commit the staged spec-repo files (never `git add -A` there)")
    print(f"  2. tracker: one triaged slice card `[{num}] Residual sweep`")
    print("  3. intake queue: archive each swept card with a comment naming "
          "the slice folder")
    print(f"  4. the run stays the operator's move: /dev:run-slice on "
          f"slices/{num}_{slug} when they choose")
    return slice_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("payload", help="path to the payload JSON")
    parser.add_argument("--force", action="store_true",
                        help=f"file below {MIN_CARDS} distinct cards or above "
                             f"{MAX_PHASES} phases")
    args = parser.parse_args(argv)

    result = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        print("not inside a git repository — run from the code repo",
              file=sys.stderr)
        return 2
    code_root = Path(result.stdout.strip())

    try:
        file_sweep(Path(args.payload), code_root, force=args.force)
    except Precondition as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
