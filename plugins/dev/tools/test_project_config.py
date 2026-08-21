"""Tests for the project config — `.aiworkflowrc`, the one file a repo uses to
describe itself to the pipeline.

The subject is `project_config.load`: what it defaults, what it rejects, and
where each path resolves from. Whether a pointer's target exists is preflight's
question, not this module's, so nothing here touches the targets.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_project_config.py` or via pytest.
"""

import importlib.util
import sys
import tempfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "project_config", Path(__file__).resolve().parent / "project_config.py"
)
project_config = importlib.util.module_from_spec(_spec)
# Registered before exec: @dataclass resolves its annotations through
# sys.modules[cls.__module__], which a bare spec-load leaves unset.
sys.modules["project_config"] = project_config
_spec.loader.exec_module(project_config)


def write(tmp, text):
    root = Path(tmp)
    (root / project_config.CONFIG_NAME).write_text(text)
    return root


def load(tmp, text):
    return project_config.load(write(tmp, text))


def refuses(tmp, text, *fragments):
    try:
        project_config.load(write(tmp, text))
    except project_config.ConfigError as e:
        for fragment in fragments:
            assert fragment in str(e), f"{fragment!r} not in {e}"
        return str(e)
    raise AssertionError(f"accepted a config it should refuse:\n{text}")


# -- defaults ----------------------------------------------------------------

def test_a_config_naming_only_its_pointers_runs_every_phase():
    """The defaults are the pipeline's full behaviour, so the switches are
    what a project opts *out* with — nobody loses a phase by omission."""
    with tempfile.TemporaryDirectory() as tmp:
        cfg = load(tmp, 'spec_repo = "../specs"\n'
                        '[test_phase]\nstrategy = "t.md"\n'
                        '[doc_phase]\nplan = "d.md"\n')
        assert cfg.test_phase and cfg.doc_phase and cfg.push


def test_an_unnamed_lease_is_a_devlock_that_never_engages():
    """One dev instance is a fact about a deployed project, not about every
    repo — so unlike the phases, the devlock defaults off."""
    with tempfile.TemporaryDirectory() as tmp:
        assert load(tmp, 'spec_repo = "../specs"\n').devlock_lease is None


def test_switches_read_back_as_written():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = load(tmp, 'spec_repo = "../specs"\n'
                        '[test_phase]\nenabled = false\n'
                        '[doc_phase]\nenabled = false\n'
                        '[push]\nenabled = false\n')
        assert not cfg.test_phase and not cfg.doc_phase and not cfg.push
        assert cfg.test_strategy is None and cfg.doc_plan is None


# -- path resolution ---------------------------------------------------------

def test_pointers_resolve_against_the_repo_root_and_the_lease_against_specs():
    """Every path is the repo's except the lease: it names a file in the spec
    repo, the shared mount each contending code repo can see."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cfg = load(tmp, 'spec_repo = "../specs"\n'
                        'design_philosophy = "docs/discipline.md"\n'
                        '[test_phase]\nstrategy = "docs/t.md"\n'
                        '[devlock]\nlease = "scripts/.devlock.lock"\n')
        assert cfg.design_philosophy == root / "docs" / "discipline.md"
        assert cfg.test_strategy == root / "docs" / "t.md"
        assert cfg.spec_repo == root / ".." / "specs"
        assert cfg.devlock_lease == root / ".." / "specs" / "scripts" / ".devlock.lock"


def test_an_absolute_path_is_taken_as_given():
    with tempfile.TemporaryDirectory() as tmp:
        cfg = load(tmp, f'spec_repo = "{tmp}/specs"\n')
        assert cfg.spec_repo == Path(tmp) / "specs"


# -- what it refuses ---------------------------------------------------------

def test_a_missing_config_prints_the_whole_schema():
    """The error text is how a repo self-onboards, so it carries the file
    rather than a pointer to documentation the reader has to go find."""
    with tempfile.TemporaryDirectory() as tmp:
        try:
            project_config.load(Path(tmp))
        except project_config.ConfigError as e:
            assert "spec_repo" in str(e) and "[test_phase]" in str(e)
        else:
            raise AssertionError("a missing config loaded")


def test_broken_toml_says_so():
    with tempfile.TemporaryDirectory() as tmp:
        refuses(tmp, 'spec_repo = ../specs\n', "not valid TOML")


def test_an_unknown_key_is_a_typo_not_a_key_to_ignore():
    """`enable = false` silently running the phase the project meant to switch
    off is exactly the failure the file exists to prevent."""
    with tempfile.TemporaryDirectory() as tmp:
        refuses(tmp, 'spec_repo = "../s"\n[test_phase]\nenable = false\n',
                "unknown key", "`enable`", "enabled")
        refuses(tmp, 'spec_repo = "../s"\nspecs_repo = "../s"\n',
                "unknown top-level key", "`specs_repo`")


def test_a_switched_off_phase_may_not_still_name_a_procedure_doc():
    """Reading the file, the pointer says the project has a testing strategy
    and the switch says it never runs. One of them is wrong."""
    with tempfile.TemporaryDirectory() as tmp:
        refuses(tmp, 'spec_repo = "../s"\n'
                     '[doc_phase]\nenabled = false\nplan = "d.md"\n',
                "disabled but still names", "`plan`")


def test_a_lease_with_no_spec_repo_to_resolve_it_against_is_refused():
    """Silently getting no devlock would look identical to a project that
    wanted none — and this one asked for one."""
    with tempfile.TemporaryDirectory() as tmp:
        refuses(tmp, '[devlock]\nlease = "scripts/.devlock.lock"\n',
                "relative to the spec repo", "`spec_repo` is not set")


def test_a_switch_must_be_a_boolean_and_a_pointer_a_path():
    with tempfile.TemporaryDirectory() as tmp:
        refuses(tmp, '[push]\nenabled = "yes"\n', "must be true or false")
        refuses(tmp, 'spec_repo = ""\n', "non-empty string")
        refuses(tmp, 'test_phase = "on"\n', "must be a table")


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    for _fn in _tests:
        _fn()
        print(f"ok  {_fn.__name__}")
    print(f"\n{len(_tests)} passed")
