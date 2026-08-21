#!/usr/bin/env python3
"""The project config — `.aiworkflowrc` at the target repo root.

One file per repo carries every fact the pipeline reads about a project: where
its spec repo is, which procedure docs its phases execute, and which phases it
runs at all. It replaced four machine-read `CLAUDE.md` lines, which put the same
facts in a file every agent loads every turn and left the pipeline with two
config surfaces once phases became optional.

TOML, parsed with `tomllib` (read-only, stdlib). Nothing writes this file —
`/dev:onboard` scaffolds it and the operator maintains it by hand.

    spec_repo = "../KestrelSpecs"
    design_philosophy = "docs/conventions/change-discipline.md"

    [test_phase]
    enabled = true
    strategy = "docs/operations/slice-test-plan.md"

    [doc_phase]
    enabled = true
    plan = "docs/operations/slice-doc-plan.md"

    [devlock]
    lease = "scripts/.devlock.lock"

    [push]
    enabled = true

Paths are absolute or relative to the repo root, except `devlock.lease`, which
is relative to the **spec repo** — the lease is the one key whose subject is
that repo, and it is shared by every code repo contending for the one dev
instance.

Defaults are the pipeline's full behaviour, so a repo that names only its
pointers runs every phase: `test_phase.enabled`, `doc_phase.enabled` and
`push.enabled` are all true when unstated. The devlock is the exception — a
lease that is not named cannot be taken, so an absent `[devlock]` is off.

Unknown keys and tables are rejected rather than ignored, so a typo
(`enable = false`) fails loudly instead of silently running a phase the project
meant to switch off.

This module validates **shape** and resolves paths. Whether a pointer's target
has to exist is per-command and belongs to preflight (see `preflight.md`).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_NAME = ".aiworkflowrc"

# The full key set, table by table. Anything outside it is a typo or a key from
# a newer plugin — either way the project hears about it.
_ROOT_KEYS = {"spec_repo", "design_philosophy"}
_TABLES = {
    "test_phase": {"enabled", "strategy"},
    "doc_phase": {"enabled", "plan"},
    "devlock": {"lease"},
    "push": {"enabled"},
}


class ConfigError(Exception):
    """The config is missing, unparseable, or names something unknown. Its
    message is operator-facing: what is wrong and the exact line that fixes
    it."""


@dataclass(frozen=True)
class ProjectConfig:
    """One repo's pipeline contract, paths resolved against the repo root."""

    root: Path
    path: Path
    spec_repo: Path | None
    design_philosophy: Path | None
    test_phase: bool
    test_strategy: Path | None
    doc_phase: bool
    doc_plan: Path | None
    devlock_lease: Path | None
    push: bool


def config_path(root: Path) -> Path:
    return root / CONFIG_NAME


def _resolve(base: Path, value: str) -> Path:
    p = Path(value).expanduser()
    return p if p.is_absolute() else (base / p)


def _string(table: dict, key: str, where: str, path: Path) -> str | None:
    value = table.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(
            f"`{where}` in {path} must be a non-empty string (got "
            f"{value!r}).")
    return value.strip()


def _bool(table: dict, key: str, where: str, path: Path, default: bool) -> bool:
    value = table.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ConfigError(
            f"`{where}` in {path} must be true or false (got {value!r}).")
    return value


def _table(data: dict, name: str, path: Path) -> dict:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(
            f"`{name}` in {path} must be a table — write it as `[{name}]` "
            f"with its keys beneath.")
    unknown = sorted(set(value) - _TABLES[name])
    if unknown:
        raise ConfigError(
            f"`[{name}]` in {path} has unknown key(s): "
            + ", ".join(f"`{k}`" for k in unknown)
            + ". Known keys: " + ", ".join(f"`{k}`" for k in sorted(_TABLES[name]))
            + ".")
    return value


def load(root: Path) -> ProjectConfig:
    """Parse and validate the repo's `.aiworkflowrc`. Raises ConfigError with
    an operator-facing message; never returns a partially-valid config."""
    path = config_path(root)
    if not path.is_file():
        raise ConfigError(
            f"No {CONFIG_NAME} at {root}. Every repo the pipeline drives "
            f"describes itself in one, at the repo root:\n\n"
            f"    spec_repo = \"<path to the spec/planning repo>\"\n"
            f"    design_philosophy = \"<path to the change-discipline doc>\"\n\n"
            f"    [test_phase]\n"
            f"    strategy = \"<path to the slice-testing-strategy doc>\"\n\n"
            f"    [doc_phase]\n"
            f"    plan = \"<path to the slice-doc-plan doc>\"\n")
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path} is not valid TOML: {e}") from None
    except OSError as e:
        raise ConfigError(f"{path} could not be read: {e}") from None

    unknown = sorted(set(data) - _ROOT_KEYS - set(_TABLES))
    if unknown:
        raise ConfigError(
            f"{path} has unknown top-level key(s): "
            + ", ".join(f"`{k}`" for k in unknown)
            + ". Known: " + ", ".join(f"`{k}`" for k in sorted(_ROOT_KEYS))
            + " and the tables "
            + ", ".join(f"`[{t}]`" for t in sorted(_TABLES)) + ".")

    spec_value = _string(data, "spec_repo", "spec_repo", path)
    philosophy = _string(data, "design_philosophy", "design_philosophy", path)

    test_tbl = _table(data, "test_phase", path)
    doc_tbl = _table(data, "doc_phase", path)
    lock_tbl = _table(data, "devlock", path)
    push_tbl = _table(data, "push", path)

    test_on = _bool(test_tbl, "enabled", "test_phase.enabled", path, True)
    doc_on = _bool(doc_tbl, "enabled", "doc_phase.enabled", path, True)
    push_on = _bool(push_tbl, "enabled", "push.enabled", path, True)
    strategy = _string(test_tbl, "strategy", "test_phase.strategy", path)
    doc_plan = _string(doc_tbl, "plan", "doc_phase.plan", path)
    lease = _string(lock_tbl, "lease", "devlock.lease", path)

    # A pointer under a switched-off phase is not ignored: it reads as "this
    # project has a testing strategy" to whoever opens the file next, and the
    # phase silently never runs. One of the two is wrong — say which.
    for table, key, on, pointer in (("test_phase", "strategy", test_on, strategy),
                                    ("doc_phase", "plan", doc_on, doc_plan)):
        if pointer and not on:
            raise ConfigError(
                f"`[{table}]` in {path} is disabled but still names "
                f"`{key}`. Delete the pointer, or set `enabled = true` — a "
                f"phase cannot be off and have a procedure doc.")

    # The lease lives in the spec repo — the shared mount every contending repo
    # can see — so a lease named with nowhere to resolve it against is broken,
    # not a devlock that quietly never engages.
    if lease and not spec_value:
        raise ConfigError(
            f"`devlock.lease` in {path} is relative to the spec repo, but "
            f"`spec_repo` is not set. Add it, or make the lease an absolute "
            f"path.")

    spec_repo = _resolve(root, spec_value) if spec_value else None
    return ProjectConfig(
        root=root,
        path=path,
        spec_repo=spec_repo,
        design_philosophy=_resolve(root, philosophy) if philosophy else None,
        test_phase=test_on,
        test_strategy=_resolve(root, strategy) if strategy else None,
        doc_phase=doc_on,
        doc_plan=_resolve(root, doc_plan) if doc_plan else None,
        devlock_lease=_resolve(spec_repo, lease) if lease else None,
        push=push_on,
    )
