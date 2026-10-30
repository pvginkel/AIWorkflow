#!/usr/bin/env python3
"""An action's checks — the facts about the tree or the environment that show
it done, in a fixed vocabulary (AIWF-88; the close-out's § The entry).

An action's `check` is one check, or several joined by `; `, each one of:

  env <NAME>                                     the variable is set and not
                                                 empty in the driver's
                                                 environment, the pod that
                                                 runs the slice
  file <repo>:<path>                             the path exists in that
                                                 repo's working tree
  origin <repo> <branch>:<path> contains <text>  after a fetch,
                                                 `origin/<branch>:<path>`
                                                 holds the text
  slice <NNN> completed                          a `NNN_*` folder is under the
                                                 spec repo's slices/completed/
  manual                                         no check captures it: a
                                                 person strikes the action

`<repo>` is a repo as a `Target:` names a sibling (`../PilotApp`), or `.`,
the repo the run starts from; a relative one resolves against that repo.

Refused, each named: a check outside the vocabulary; `manual` beside another
check; a commit hash, which a push can rebase away (slice 018's 45a9ab3 became
e91fc82); an environment id, which names a pod other than the one that runs
the slice (slice 007). No check runs a command it was handed. Stdlib only:
close_out.py holds an action's check to the vocabulary, the run loop
evaluates the checks of the actions owed before a run.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

SEPARATOR = ";"
MANUAL = "manual"
FETCH_TIMEOUT = 60

VOCABULARY = ("env <NAME>", "file <repo>:<path>",
              "origin <repo> <branch>:<path> contains <text>",
              "slice <NNN> completed", MANUAL)

_ENV = re.compile(r"env\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)")
_FILE = re.compile(r"file\s+(?P<repo>[^\s:]+):(?P<path>\S.*)")
_ORIGIN = re.compile(r"origin\s+(?P<repo>\S+)\s+(?P<branch>[^\s:]+):(?P<path>\S+)"
                     r"\s+contains\s+(?P<text>\S.*)")
_SLICE = re.compile(r"slice\s+(?P<num>\d{1,4})\s+completed")
# A commit: seven to forty hex digits holding both a digit and a letter, so
# that a number or a word such as `decade` is not one.
_COMMIT = re.compile(r"(?<![0-9A-Za-z])(?=[0-9a-f]*[0-9])(?=[0-9a-f]*[a-f])"
                     r"[0-9a-f]{7,40}(?![0-9A-Za-z])")
# A KubeCoder environment id: `<owner>-<repo>-<six hex>`, the last part
# holding a digit (`pvginkel-pilotapp-addac6`).
_ENV_ID = re.compile(r"(?<![0-9A-Za-z-])[a-z0-9]+(?:-[a-z0-9]+)+-"
                     r"(?=[0-9a-f]*[0-9])[0-9a-f]{6}(?![0-9A-Za-z-])")


class CheckError(ValueError):
    """A check text that is not the vocabulary's, every fault named."""


class Check(NamedTuple):
    kind: str                  # env, file, origin, slice, manual
    text: str                  # as written
    fields: tuple = ()

    def __str__(self) -> str:
        return self.text


def _unquote(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "`\"'":
        return text[1:-1]
    return text


def _one(text: str) -> tuple[Check | None, list[str]]:
    found: list[str] = []
    for m in _COMMIT.finditer(text):
        found.append(f"`{text}` names {m.group(0)}, a commit: a push can rebase it "
                     "away — state the fact the commit brings instead, such as a "
                     "file's content on origin (`origin … contains …`)")
    for m in _ENV_ID.finditer(text):
        found.append(f"`{text}` names {m.group(0)}, an environment: the slice may "
                     "run in another — state the fact it should have, such as a "
                     "variable (`env <NAME>`)")
    if found:
        return None, found
    if text == MANUAL:
        return Check("manual", text), []
    if m := _ENV.fullmatch(text):
        return Check("env", text, (m["name"],)), []
    if m := _FILE.fullmatch(text):
        return Check("file", text, (m["repo"], m["path"].strip())), []
    if m := _ORIGIN.fullmatch(text):
        return Check("origin", text, (m["repo"], m["branch"], m["path"],
                                      _unquote(m["text"]))), []
    if m := _SLICE.fullmatch(text):
        return Check("slice", text, (m["num"],)), []
    return None, [f"`{text}` is no check: one of " + ", ".join(
        f"`{v}`" for v in VOCABULARY)]


def problems(text: str | None) -> list[str]:
    """Every fault of a check text; none for one the vocabulary reads."""
    return _parse(text)[1]


def _parse(text: str | None) -> tuple[list[Check], list[str]]:
    parts = [p.strip() for p in (text or "").split(SEPARATOR)]
    if not any(parts):
        return [], ["the check is empty"]
    checks: list[Check] = []
    found: list[str] = []
    for part in parts:
        if not part:
            found.append(f"`{text}` holds an empty check between two `{SEPARATOR}`")
            continue
        check, faults = _one(part)
        found += faults
        if check is not None:
            checks.append(check)
    if any(c.kind == "manual" for c in checks) and len(parts) > 1:
        found.append(f"`{MANUAL}` stands alone: an action no check captures has no "
                     "other check")
    return checks, found


def parse(text: str | None) -> list[Check]:
    """The checks a text holds; CheckError naming every fault."""
    checks, found = _parse(text)
    if found:
        raise CheckError("\n".join(found))
    return checks


def join(texts: list[str]) -> str:
    """Several checks as one `check` value, as `--check` repeated gives them."""
    return f"{SEPARATOR} ".join(t.strip() for t in texts if t and t.strip())


def is_manual(checks: list[Check]) -> bool:
    return any(c.kind == "manual" for c in checks)


def _repo(repo: str, repo_root: Path) -> Path:
    path = Path(repo)
    return path if path.is_absolute() else (Path(repo_root) / path).resolve()


def _git(root: Path, *args: str, timeout: int = FETCH_TIMEOUT) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True, timeout=timeout, check=False)


def evaluate(check: Check, *, repo_root: Path, spec_root: Path,
             env: Mapping[str, str] | None = None) -> tuple[bool | None, str]:
    """Whether the check holds, and in a line why — None for `manual`, which
    no program can tell."""
    env = os.environ if env is None else env
    if check.kind == "manual":
        return None, "no check captures it: a person strikes the action once it is done"
    if check.kind == "env":
        (name,) = check.fields
        if (env.get(name) or "").strip():
            return True, f"{name} is set in this pod"
        return False, f"{name} is not set in this pod"
    if check.kind == "file":
        repo, path = check.fields
        root = _repo(repo, repo_root)
        if (root / path).exists():
            return True, f"{path} is in {root}"
        return False, f"{path} is not in {root}"
    if check.kind == "slice":
        (num,) = check.fields
        done = Path(spec_root) / "slices" / "completed"
        names = {num, f"{int(num):03d}"}
        hits = [d for d in (done.iterdir() if done.is_dir() else ())
                if d.is_dir() and d.name.split("_", 1)[0] in names]
        if hits:
            return True, f"slice {num} is in {done}"
        return False, f"slice {num} is not under {done}"
    repo, branch, path, text = check.fields
    root = _repo(repo, repo_root)
    if not (root / ".git").exists():
        return False, f"{root} is not a git checkout"
    try:
        fetched = _git(root, "fetch", "--quiet", "origin", branch)
        if fetched.returncode != 0:
            why = (fetched.stderr or fetched.stdout).strip().splitlines()
            return False, (f"`git fetch origin {branch}` failed in {root}"
                           + (f": {why[-1]}" if why else ""))
        shown = _git(root, "show", f"origin/{branch}:{path}")
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"git could not read origin/{branch}:{path} in {root} ({e})"
    if shown.returncode != 0:
        return False, f"origin/{branch} has no {path} in {root}"
    if text in shown.stdout:
        return True, f"origin/{branch}:{path} holds `{text}`"
    return False, f"origin/{branch}:{path} does not hold `{text}`"
