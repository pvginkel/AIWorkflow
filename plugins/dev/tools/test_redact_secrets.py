"""Tests for redact_secrets — `kind: Secret` data stubbed out of a diff.

The diffs are git's own: a throwaway repo per test (real `git init`, the
user's and the system's git config held out), commits of the manifest shapes
the redactor must read, and `git diff` over them — so hunk headers, context,
quoting and `\\ No newline at end of file` are what the driver and the agents
will hand it. The blobs come from the same repo, through a reader that
records what it was asked for.

Stdlib only, like the workflow's other suites.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/tools/test_redact_secrets.py` or via pytest.
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TOOL = Path(__file__).resolve().parent / "redact_secrets.py"
_spec = importlib.util.spec_from_file_location("redact_secrets", TOOL)
redact_secrets = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(redact_secrets)
RedactionError = redact_secrets.RedactionError
redact = redact_secrets.redact
secret_data_lines = redact_secrets.secret_data_lines

# git as the suite runs it: none of the machine's own config (a `noprefix`,
# an external diff, a pager) reaches the diffs under test.
GIT_ENV = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull,
           "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t",
           "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}


class Repo:
    """A throwaway git repo: commit file states, diff ranges, read blobs."""

    def __init__(self, root):
        self.root = Path(root)
        self.git("init", "-q", "-b", "main")
        self.reads = []          # (side, path) the blob reader was asked

    def git(self, *args):
        result = subprocess.run(["git", *args], cwd=self.root, env=GIT_ENV,
                                capture_output=True, check=True)
        return result.stdout.decode("utf-8", "surrogateescape")

    def commit(self, files):
        """Write (or, for None, delete) each path; commit; the new sha."""
        for path, text in files.items():
            target = self.root / path
            if text is None:
                target.unlink()
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", "c")
        return self.git("rev-parse", "HEAD").strip()

    def diff(self, a, b, *extra):
        return self.git("diff", *extra, f"{a}..{b}")

    def reader(self, a, b):
        def blob(side, path):
            self.reads.append((side, path))
            return self.git("show", f"{a if side == 'old' else b}:{path}")
        return blob

    def redact(self, a, b, *extra):
        return redact(self.diff(a, b, *extra), self.reader(a, b))


def repo_with(*states):
    """A repo in a fresh tmp dir with `states` committed in order: the repo,
    the tmp dir's handle (keep it alive), and the shas."""
    tmp = tempfile.TemporaryDirectory()
    repo = Repo(tmp.name)
    shas = [repo.commit(state) for state in states]
    return repo, tmp, shas


def hunk_lines(text):
    """The diff's hunk lines: everything from the first `@@` on."""
    lines = text.splitlines()
    first = next(i for i, line in enumerate(lines) if line.startswith("@@"))
    return lines[first:]


def manifest(*docs):
    return "---\n".join(docs)


CONFIGMAP = """\
apiVersion: v1
kind: ConfigMap
metadata:
  name: settings
data:
  log_level: visible-setting
"""

SECRET = """\
apiVersion: v1
kind: Secret
metadata:
  name: ca-key
type: Opaque
data:
  ca.key: S3CRETKEYVALUE
  password: aHVudGVyMg==
"""


def long_secret(changed=None):
    rows = [f"  k{i:02}: {('NEWVALUE' if i == changed else f'value{i:02}')}"
            for i in range(1, 21)]
    return ("apiVersion: v1\nkind: Secret\nmetadata:\n  name: big\n"
            "type: Opaque\ndata:\n" + "\n".join(rows) + "\n")


# -- the data lines -----------------------------------------------------------

def test_a_removed_secret_beside_a_configmap_is_stubbed_and_the_configmap_kept():
    repo, tmp, (a, b) = repo_with(
        {"deploy/pki.yaml": manifest(CONFIGMAP, SECRET)},
        {"deploy/pki.yaml": None})
    with tmp:
        text, n = repo.redact(a, b)
        assert n == 2
        assert "-[Secret ca-key: 2 data lines]" in text.splitlines()
        assert "-  log_level: visible-setting" in text.splitlines()
        assert "-data:" in text.splitlines(), "the key line is structure"
        assert "S3CRETKEYVALUE" not in text and "aHVudGVyMg" not in text
        assert repo.reads == [("old", "deploy/pki.yaml")], "no new side"


def test_a_changed_value_deep_in_a_long_data_block_is_found_from_the_blobs():
    """The hunk's three lines of context hold no `kind: Secret` — only the
    whole file says these are a Secret's data."""
    repo, tmp, (a, b) = repo_with({"s.yaml": long_secret()},
                                  {"s.yaml": long_secret(changed=15)})
    with tmp:
        raw = repo.diff(a, b)
        assert "kind" not in "\n".join(hunk_lines(raw)[1:])
        text, n = repo.redact(a, b)
        body = hunk_lines(text)
        assert body[1:] == [" [Secret big: 3 data lines]",
                            "-[Secret big: 1 data line]",
                            "+[Secret big: 1 data line]",
                            " [Secret big: 3 data lines]"]
        assert n == 8
        assert "NEWVALUE" not in text and "value15" not in text
        # git's section heading quotes a file line: dropped in such a file
        assert raw.splitlines()[4].endswith("@@ data:")
        assert all(line.endswith("@@") for line in text.splitlines()
                   if line.startswith("@@"))


def test_string_data_added_and_context_lines_are_stubbed():
    first = ("kind: Secret\nmetadata:\n  name: tokens\nstringData:\n"
             "  a: one-token\n  b: two-token\n  c: three-token\n")
    second = first.replace("two-token", "TWO-TOKEN")
    repo, tmp, (a, b, c) = repo_with({"x.yml": first}, {"x.yml": second},
                                     {"x.yml": second, "new.yml": first})
    with tmp:
        text, n = repo.redact(a, b)
        assert hunk_lines(text)[1:] == [
            "   name: tokens", " stringData:",
            " [Secret tokens: 1 data line]", "-[Secret tokens: 1 data line]",
            "+[Secret tokens: 1 data line]", " [Secret tokens: 1 data line]"]
        assert n == 4
        text, n = repo.redact(b, c)
        assert "+[Secret tokens: 3 data lines]" in text.splitlines()
        assert repo.reads[-1] == ("new", "new.yml")
        assert ("old", "new.yml") not in repo.reads, "/dev/null is not read"
        assert "token" not in text.replace("name: tokens", "").replace(
            "Secret tokens", "")


def test_a_helm_template_keeps_its_if_lines_inside_the_data_block():
    chart = """\
{{- if .Values.ca.enabled }}
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "chart.fullname" . }}-ca
  labels:
    {{- include "chart.labels" . | nindent 4 }}
type: Opaque
data:
{{- if .Values.ca.key }}
  ca.key: {{ .Values.ca.key | b64enc | quote }}
{{- end }}
  static.key: c3RhdGljLWtleQ==
{{- end }}
"""
    repo, tmp, (a, b) = repo_with({"chart/templates/secret.yaml": chart},
                                  {"chart/templates/secret.yaml": None})
    with tmp:
        text, n = repo.redact(a, b)
        assert ('-[Secret {{ include "chart.fullname" . }}-ca: 5 data lines]'
                in text.splitlines())
        assert n == 5
        assert "c3RhdGlj" not in text
        assert "-type: Opaque" in text.splitlines()


def test_an_ansible_task_nesting_the_secret_under_definition():
    task = """\
- name: Install the CA secret
  kubernetes.core.k8s:
    state: present
    definition:
      apiVersion: v1
      kind: Secret
      metadata:
        name: ca-key
        namespace: pki
      type: Opaque
      data:
        ca.key: "{{ vault_ca_key | b64encode }}"
        ca.crt: Q0FDRVJUT0xE
- name: Something else
  ansible.builtin.debug:
    msg: data
"""
    repo, tmp, (a, b) = repo_with(
        {"roles/pki/tasks/main.yml": task},
        {"roles/pki/tasks/main.yml": task.replace("Q0FDRVJUT0xE",
                                                  "Q0FDRVJUTkVX")})
    with tmp:
        text, _ = repo.redact(a, b)
        body = hunk_lines(text)[1:]
        assert body == [
            "       type: Opaque", "       data:",
            " [Secret ca-key: 1 data line]", "-[Secret ca-key: 1 data line]",
            "+[Secret ca-key: 1 data line]", " - name: Something else",
            "   ansible.builtin.debug:", "     msg: data"]
        assert "Q0FDRVJU" not in text


def test_a_secret_inside_a_block_scalar_definition():
    task = """\
- name: Apply
  kubernetes.core.k8s:
    definition: |
      apiVersion: v1
      kind: Secret
      metadata:
        name: blockish
      stringData:
        token: abc123token
"""
    assert secret_data_lines(task) == {9: "blockish"}


def test_a_list_of_secrets_names_each_item():
    items = """\
apiVersion: v1
kind: List
items:
- apiVersion: v1
  kind: Secret
  metadata:
    name: first
  data:
    a: Rk9PRk9P
- kind: Secret
  data:
    b: QkFSQkFS
  metadata:
    name: second
"""
    assert secret_data_lines(items) == {9: "first", 12: "second"}
    repo, tmp, (a, b) = repo_with({"list.json.j2": items},
                                  {"list.json.j2": None})
    with tmp:
        text, n = repo.redact(a, b)
        assert "-[Secret first: 1 data line]" in text.splitlines()
        assert "-[Secret second: 1 data line]" in text.splitlines()
        assert "Rk9P" not in text and "QkFS" not in text and n == 2


def test_names_unnamed_quoted_and_commented():
    assert secret_data_lines("kind: Secret\ndata:\n  a: b\n") == {
        3: "<unnamed>"}
    doc = ('kind: "Secret"  # the CA\nmetadata:\n  labels:\n    name: no\n'
           "  name: 'quoted' # why\ndata: # below\n\n  # a comment\n  a: b\n"
           "type: Opaque\n")
    assert secret_data_lines(doc) == {7: "quoted", 8: "quoted", 9: "quoted"}
    assert secret_data_lines("kind: Secret\ndata: {}\ntype: Opaque\n") == {}


def test_secret_lookalikes_and_a_configmap_are_not_redacted():
    lookalikes = manifest(
        "apiVersion: external-secrets.io/v1beta1\nkind: SecretStore\n"
        "metadata:\n  name: store\nspec:\n  provider: {}\n",
        "kind: ExternalSecret\nmetadata:\n  name: ext\nspec:\n  data:\n"
        "  - secretKey: password\n",
        "kind: SealedSecret\nspec:\n  encryptedData:\n    password: AgBy\n"
        "data:\n  x: y\n",
        CONFIGMAP)
    assert secret_data_lines(lookalikes) == {}
    repo, tmp, (a, b) = repo_with({"ext.yaml": lookalikes},
                                  {"ext.yaml": None})
    with tmp:
        raw = repo.diff(a, b)
        assert repo.redact(a, b) == (raw, 0)


def test_a_file_that_is_not_a_manifest_passes_through_unread():
    code = 'KIND = "kind: Secret"\n# kind: Secret, data: password: x\n'

    def blob(side, path):
        raise AssertionError(f"read {side} {path}")

    repo, tmp, (a, b) = repo_with({"tool.py": code, "notes.md": code},
                                  {"tool.py": code + "x = 1\n",
                                   "notes.md": None})
    with tmp:
        raw = repo.diff(a, b)
        assert redact(raw, blob) == (raw, 0)


# -- the diff's shapes --------------------------------------------------------

def test_a_pure_rename_passes_through_and_a_changed_rename_reads_both_paths():
    repo, tmp, (a, b, c) = repo_with(
        {"old.yaml": SECRET},
        {"old.yaml": None, "moved.yaml": SECRET},
        {"moved.yaml": None,
         "again.yaml": SECRET.replace("S3CRETKEYVALUE", "N3WKEYVALUE0")})
    with tmp:
        raw = repo.diff(a, b)
        assert "rename from old.yaml" in raw and "@@" not in raw
        assert repo.redact(a, b) == (raw, 0)
        assert repo.reads == []
        text, n = repo.redact(b, c)
        assert "rename to again.yaml" in text
        assert repo.reads == [("old", "moved.yaml"), ("new", "again.yaml")]
        assert "-[Secret ca-key: 1 data line]" in text.splitlines()
        assert "N3WKEY" not in text and "S3CRET" not in text and n == 3


def test_no_newline_at_end_of_file_passes_through():
    first = SECRET.rstrip("\n")
    repo, tmp, (a, b) = repo_with(
        {"s.yaml": first},
        {"s.yaml": first.replace("aHVudGVyMg==", "Y2hhbmdlZA==")})
    with tmp:
        text, n = repo.redact(a, b)
        assert hunk_lines(text)[-5:] == [
            " [Secret ca-key: 1 data line]", "-[Secret ca-key: 1 data line]",
            "\\ No newline at end of file", "+[Secret ca-key: 1 data line]",
            "\\ No newline at end of file"]
        assert "aHVudGVy" not in text and "Y2hhbmdl" not in text and n == 3


def test_a_quoted_path_and_a_no_prefix_diff():
    repo, tmp, (a, b) = repo_with({"café.yaml": SECRET},
                                  {"café.yaml": None})
    with tmp:
        raw = repo.diff(a, b)
        assert '--- "a/caf\\303\\251.yaml"' in raw
        text, n = repo.redact(a, b)
        assert repo.reads == [("old", "café.yaml")] and n == 2
        repo.reads.clear()
        text, n = repo.redact(a, b, "--no-prefix")
        assert repo.reads == [("old", "café.yaml")] and n == 2
        assert "S3CRET" not in text


def test_an_unchanged_diff_and_a_mixed_one_keep_everything_else_byte_for_byte():
    repo, tmp, (a, b) = repo_with(
        {"s.yaml": SECRET, "app.py": "print(1)\n", "cm.yaml": CONFIGMAP},
        {"s.yaml": None, "app.py": "print(2)\n",
         "cm.yaml": CONFIGMAP.replace("visible", "shown")})
    with tmp:
        raw = repo.diff(a, b)
        text, _ = repo.redact(a, b)
        kept = [line for line in raw.splitlines()
                if "S3CRET" not in line and "aHVudGVy" not in line]
        assert [line for line in text.splitlines()
                if not line.startswith("-[Secret")] == kept
        assert text.endswith("\n")
        assert redact("", repo.reader(a, b)) == ("", 0)


# -- fail-closed --------------------------------------------------------------

def assert_refused(diff, blob, *named, absent=()):
    try:
        redact(diff, blob)
    except RedactionError as e:
        message = str(e)
    else:
        raise AssertionError("redacted what it should have refused")
    for part in named:
        assert part in message, (part, message)
    for value in absent:
        assert value not in message, (value, message)
    return message


def test_flow_style_data_and_a_json_secret_are_refused_by_line():
    flow = "kind: Secret\nmetadata:\n  name: f\ndata: {password: aHVudGVy}\n"
    templated = "kind: Secret\ndata: {{ toYaml .Values.d | nindent 2 }}\n"
    as_json = ('{\n  "apiVersion": "v1",\n  "kind": "Secret",\n'
               '  "data": {"password": "aHVudGVy"}\n}\n')
    flow_kind = "items:\n- {kind: Secret, data: {password: aHVudGVy}}\n"
    commented = "# kind: Secret\n# data:\n#   password: aHVudGVy\n"
    repo, tmp, (a, b) = repo_with(
        {"flow.yaml": flow, "tpl.tpl": templated, "s.json": as_json,
         "k.yaml": flow_kind, "c.yaml": commented},
        {"flow.yaml": None, "tpl.tpl": None, "s.json": None, "k.yaml": None,
         "c.yaml": None})
    with tmp:
        for path, line in (("flow.yaml", 4), ("tpl.tpl", 2), ("s.json", 3),
                           ("k.yaml", 2), ("c.yaml", 1)):
            raw = repo.git("diff", f"{a}..{b}", "--", path)
            assert_refused(raw, repo.reader(a, b), path, "old side",
                           f"line {line}",
                           absent=("aHVudGVy", "password", "toYaml"))


def test_a_diff_of_another_range_is_refused():
    repo, tmp, (a, b, c) = repo_with(
        {"s.yaml": long_secret()}, {"s.yaml": long_secret(changed=15)},
        {"s.yaml": long_secret(changed=3)})
    with tmp:
        raw = repo.diff(a, b)
        assert_refused(raw, repo.reader(a, c), "s.yaml (new side), line",
                       "does not match", absent=("value", "NEWVALUE"))
        # a whitespace-ignoring diff shows the new side as context
        repo2, tmp2, (x, y) = repo_with(
            {"t.yaml": SECRET},
            {"t.yaml": SECRET.replace("Opaque", "Opaque  ").replace(
                "aHVudGVyMg==", "Y2hhbmdlZA==")})
        with tmp2:
            raw = repo2.diff(x, y, "-w")
            assert_refused(raw, repo2.reader(x, y), "t.yaml (old side)",
                           absent=("Opaque", "aHVudGVy"))


def test_a_malformed_or_short_hunk_and_a_combined_diff_are_refused():
    repo, tmp, (a, b) = repo_with({"s.yaml": SECRET}, {"s.yaml": None})
    with tmp:
        raw = repo.diff(a, b)
        blob = repo.reader(a, b)
        assert_refused(raw.replace("@@ -1,8 +0,0 @@", "@@ -1,x +0,0 @@"),
                       blob, "s.yaml", "diff line 6", "hunk header",
                       absent=("S3CRET",))
        assert_refused(raw.replace("@@ -1,8 +0,0 @@", "@@ -1,9 +0,0 @@"),
                       blob, "s.yaml", "short of its header's line counts")
        assert_refused(raw.replace("@@ -1,8 +0,0 @@", "@@ -1,7 +0,0 @@"),
                       blob, "s.yaml", "hunk header", absent=("aHVudGVy",))
        assert_refused(raw.rstrip("\n") + "\n\n", blob, "s.yaml")
        assert_refused(raw.replace("diff --git", "diff --cc"), blob,
                       "combined")
        assert_refused("--- a/s.yaml\n+++ b/s.yaml\n@@ -1 +1 @@\n-x\n+y\n",
                       blob, "diff line 1", "not a `git diff`")


def test_a_blob_the_reader_cannot_give_is_refused():
    def blob(side, path):
        raise RedactionError(f"{path} ({side} side): cannot be read")

    repo, tmp, (a, b) = repo_with({"s.yaml": SECRET}, {"s.yaml": None})
    with tmp:
        assert_refused(repo.diff(a, b), blob, "s.yaml (old side)")


# -- the CLI ------------------------------------------------------------------

def run_cli(repo, *args, stdin=b""):
    result = subprocess.run([sys.executable, str(TOOL), *args],
                            input=stdin, capture_output=True, env=GIT_ENV,
                            cwd=repo.root)
    return result.returncode, result.stdout, result.stderr.decode()


def test_the_cli_redacts_a_real_range_and_reads_head():
    repo, tmp, (a, b) = repo_with({"pki.yaml": manifest(CONFIGMAP, SECRET)},
                                  {"pki.yaml": None})
    with tmp:
        raw = repo.diff(a, "HEAD").encode()
        code, out, err = run_cli(repo, "--root", str(repo.root), f"{a}..HEAD",
                                 stdin=raw)
        assert code == 0, err
        assert b"-[Secret ca-key: 2 data lines]" in out.splitlines()
        assert b"S3CRET" not in out and b"visible-setting" in out
        expected, _ = repo.redact(a, b)
        assert out.decode() == expected


def test_the_cli_prints_nothing_and_exits_3_when_it_cannot_redact():
    flow = "kind: Secret\ndata: {password: aHVudGVy}\n"
    repo, tmp, (a, b, c) = repo_with({"f.yaml": flow}, {"f.yaml": None},
                                     {"g.yaml": SECRET})
    with tmp:
        code, out, err = run_cli(repo, "--root", str(repo.root), f"{a}..{b}",
                                 stdin=repo.diff(a, b).encode())
        assert (code, out) == (3, b"")
        assert "f.yaml (old side), line 2" in err and f"{a}..{b}" in err
        assert "aHVudGVy" not in err
        # a range the diff was not taken over: the blob is not there
        code, out, err = run_cli(repo, "--root", str(repo.root), f"{a}..{b}",
                                 stdin=repo.diff(b, c).encode())
        assert (code, out) == (3, b"")
        assert f"git show {b}:g.yaml" in err and "S3CRET" not in err


def test_the_cli_refuses_a_missing_or_malformed_range_as_usage():
    repo, tmp, (a, b) = repo_with({"x.yaml": "a: b\n"}, {"x.yaml": "a: c\n"})
    with tmp:
        for args in ((), ("--root", str(repo.root)), (f"{a}...{b}",),
                     (a,), (f"..{b}",), (f"{a}..",)):
            code, out, err = run_cli(repo, *args, stdin=b"")
            assert code == 2 and out == b"", (args, code, err)


if __name__ == "__main__":
    _tests = [v for k, v in sorted(globals().items())
              if k.startswith("test_") and callable(v)]
    for _fn in _tests:
        _fn()
        print(f"ok  {_fn.__name__}")
    print(f"\n{len(_tests)} passed")
