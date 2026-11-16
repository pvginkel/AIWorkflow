#!/usr/bin/env python3
"""The workflow's labeller for Pilot's analysis dashboard (docs/labeller.md).

    python3 -B labeller.py <verb>      # one JSON request on stdin

Every verb reads one JSON document on stdin and writes its answer to stdout:
one JSON document, except `label`, which streams JSON Lines.

  info          the contract, the plugin's version and the verbs
  vocabularies  every declared list, the nestings and the groups
  stamps        the stamp each transcript would get now, never reading one
  label         the labels of the transcripts it is handed, one line each
  classes       the class of each file it is handed
  check         the replay check over transcripts on a home; its arguments are
                flags, not a request (`check --help`), and it exits 0 when every
                transcript agrees, 1 otherwise, 2 for arguments it cannot use

Exit 0 when answered (per-transcript errors included), 2 when the request was
refused (`{"error": {"code", "detail"}}` on stdout), 1 on a crash.

It writes nothing anywhere. The run records are read through
`labeller_records`, a transcript through `labeller_engine`, each imported only
by the verbs that need it, so `stamps`, `classes` and `vocabularies` stay cheap.
"""

import sys

sys.dont_write_bytecode = True

import functools  # noqa: E402
import gc  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import traceback  # noqa: E402
from pathlib import Path  # noqa: E402

TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

CONTRACT = 1
SPEAKS = (1,)
VERBS = ("info", "vocabularies", "stamps", "label", "classes", "check")
PLUGIN_MANIFEST = TOOLS_DIR.parent / ".claude-plugin" / "plugin.json"
# The index handed back is at most this long; past it none is handed back.
INDEX_CAP = 16 * 1024 * 1024
# The stamp's format tag, its text's first field.
STAMP_FORMAT = "1"
_DATA_ID_RE = re.compile(r"[^A-Za-z0-9_-]")


class Refusal(Exception):
    """A request refused: exit 2 with `{"error": {"code", "detail", **extra}}`."""

    def __init__(self, code: str, detail: str, **extra):
        super().__init__(detail)
        self.code, self.detail, self.extra = code, detail, extra

    def answer(self) -> dict:
        return {"error": {"code": self.code, "detail": self.detail, **self.extra}}


def _manifest() -> dict:
    try:
        data = json.loads(PLUGIN_MANIFEST.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


@functools.cache
def plugin_version() -> str:
    """The plugin's version, Pilot's `labelled_under`."""
    return str(_manifest().get("version") or "unknown")


# ---------------------------------------------------------------------------
# The request


def read_request(stream) -> dict:
    text = stream.read()
    try:
        request = json.loads(text)
    except ValueError as e:
        raise Refusal("json", f"the request is not JSON: {e}") from None
    if not isinstance(request, dict):
        raise Refusal("request", "the request is not a JSON object")
    return request


def check_contract(request: dict) -> None:
    contract = request.get("contract")
    if type(contract) is not int or contract not in SPEAKS:
        raise Refusal("contract", f"contract {contract!r} is not spoken here",
                      speaks=list(SPEAKS))


def check_home(request: dict) -> dict:
    home = request.get("home")
    if not isinstance(home, dict):
        raise Refusal("home", "the request names no `home`")
    for key in ("projects", "plugins"):
        if not isinstance(home.get(key), str) or not home[key]:
            raise Refusal("home", f"`home.{key}` is missing")
    if "data" in home and (not isinstance(home["data"], str) or not home["data"]):
        raise Refusal("home", "`home.data` is not a path")
    return home


def data_dir(home: dict, tools_dir: Path = TOOLS_DIR) -> Path:
    """The run records' folder: `home.data`, else the data folder of the
    plugin's installed key under `home.plugins` (runner-state.md § The run
    records, `plugin_data_dir`). The key's marketplace is read off the cache
    layout this file runs from, else the sole `<name>@*` key of
    `installed_plugins.json` there is taken."""
    if home.get("data"):
        return Path(home["data"])
    plugins = Path(home["plugins"])
    name = _manifest().get("name")
    key = None
    parts = tools_dir.parts
    if (name and len(parts) >= 6 and parts[-1] == "tools" and parts[-3] == name
            and parts[-5] == "cache" and parts[-6] == "plugins"):
        key = f"{name}@{parts[-4]}"
    elif name:
        try:
            installed = json.loads((plugins / "installed_plugins.json").read_text())
        except (OSError, ValueError):
            installed = {}
        table = installed.get("plugins") if isinstance(installed, dict) else None
        keys = [k for k in table or {} if k.split("@", 1)[0] == name]
        key = keys[0] if len(keys) == 1 else None
    if not key:
        raise Refusal("home", f"no data folder can be told under {plugins}: the "
                              f"plugin's installed key is not known")
    return plugins / "data" / _DATA_ID_RE.sub("-", key)


def _conversations(request: dict, verb: str) -> list[dict]:
    convs = request.get("conversations")
    if not isinstance(convs, list):
        raise Refusal("request", f"`{verb}` needs `conversations`, a list")
    for n, conv in enumerate(convs):
        where = f"conversation {n + 1}"
        if not isinstance(conv, dict) or not isinstance(conv.get("session_id"), str):
            raise Refusal("request", f"{where} has no `session_id`")
        for key in ("sessions", "documents"):
            if not isinstance(conv.get(key, []), list):
                raise Refusal("request", f"{where}'s `{key}` is not a list")
        transcripts = conv.get("transcripts")
        if not isinstance(transcripts, list) or not all(
                isinstance(t, dict) for t in transcripts):
            raise Refusal("request", f"{where}'s `transcripts` is not a list of objects")
        if verb == "label":
            for m, t in enumerate(transcripts):
                _check_label_item(t, f"{where}, transcript {m + 1}")
    return convs


def _check_label_item(t: dict, where: str) -> None:
    if not isinstance(t.get("path"), str) or not t["path"]:
        raise Refusal("request", f"{where} has no `path`")
    mode = t.get("mode")
    if mode not in ("whole", "appended"):
        raise Refusal("request", f"{where} has `mode` {mode!r}, not whole or appended")
    if not isinstance(t.get("calls"), list):
        raise Refusal("request", f"{where} has no `calls` list")
    if not isinstance(t.get("launches", []), list):
        raise Refusal("request", f"{where}'s `launches` is not a list")
    if mode == "appended" and not isinstance(t.get("from"), dict):
        raise Refusal("request", f"{where} is appended and has no `from`")


def _pilot(request: dict) -> frozenset:
    """The `pilot` header: the conversations any Pilot Session ran."""
    pilot = request.get("pilot") or {}
    convs = pilot.get("conversations") if isinstance(pilot, dict) else None
    return frozenset(c for c in convs or [] if isinstance(c, str))


def _index_out(blob):
    """The index to hand back: none past INDEX_CAP."""
    return blob if blob is not None and len(blob) <= INDEX_CAP else None


def load_records(request: dict):
    """(Records, its new index blob) from the request's data folder and index."""
    import labeller_records
    return labeller_records.Records.load(data_dir(request["home"]), request.get("index"))


# ---------------------------------------------------------------------------
# The stamp


def parse_stamp(text) -> list[str]:
    """The `<named>` part of a stamp, the slices the transcript's own content
    named; none for a stamp of another format, or none at all."""
    if not isinstance(text, str):
        return []
    parts = text.split(":", 2)
    if len(parts) < 3 or parts[0] != STAMP_FORMAT or not parts[2]:
        return []
    return [name for name in parts[2].split(",") if name]


def format_stamp(inputs, named=()) -> str:
    """`1:<digest>[:<named>]`, the digest over the canonical JSON of the inputs."""
    import labeller_vocab
    text = f"{STAMP_FORMAT}:{labeller_vocab.digest(inputs)}"
    named = list(dict.fromkeys(n for n in named if n))
    return f"{text}:{','.join(named)}" if named else text


# The context of a conversation Pilot handed no Session or Document with, as canonical JSON.
_NO_CONTEXT = '{"documents":[],"sessions":[]}'


def context_key(conversation: dict) -> str:
    """The canonical JSON of `conversation_inputs`, the stamp's first input."""
    import labeller_vocab
    if not conversation.get("sessions") and not conversation.get("documents"):
        return _NO_CONTEXT
    return labeller_vocab.canonical(conversation_inputs(conversation))


def conversation_inputs(conversation: dict) -> dict:
    """The stamp's inputs of what Pilot handed with a conversation: the
    Sessions' kind, brief, repo, clarification and `created_at`, which
    places a Launch on its Session, and their Holds and Turns (D6), in
    their order, and the Documents' ids, Sessions and source paths."""
    return {
        "sessions": [[s.get("kind"), s.get("brief"), s.get("repo"), s.get("clarification"),
                      s.get("created_at"), _rows(s.get("holds"), "kind", "started_at",
                                                 "ended_at"),
                      _rows(s.get("turns"), "started_at", "cause")]
                     for s in conversation.get("sessions") or [] if isinstance(s, dict)],
        "documents": [[d.get("id"), d.get("session"), d.get("source_path")]
                      for d in conversation.get("documents") or [] if isinstance(d, dict)],
    }


def _rows(rows, *keys) -> list | None:
    """A Session's Holds or Turns as the stamp takes them: none where Pilot handed none."""
    if not isinstance(rows, list):
        return None
    return [[r.get(k) for k in keys] for r in rows if isinstance(r, dict)]


def transcript_stamp(records, conversation: dict, transcript: dict, pilot: frozenset,
                     named=(), conv_key: str | None = None, memo: dict | None = None):
    """(the stamp, the tie) of one transcript. `named` is the slices its own
    content named: the held stamp's for `stamps`, what the engine read in the
    file for `label`. The tie is asked with them as the transcript's
    `named`; the run records' half of the inputs, the Pilot bit included, is
    `records.stamp_inputs`'. The `conversation` slot is the inputs taken
    from another transcript of the conversation: nothing in contract 1.

    `conv_key` is `context_key(conversation)`, which a caller with many
    transcripts of a conversation takes once. `memo`, a dict kept for one
    call over one set of records, holds each stamp under the inputs it was
    taken over, so that transcripts with the same inputs are digested once."""
    named = list(dict.fromkeys(named)) if len(named) > 1 else list(named)
    item = {**transcript, "named": named}
    tie = records.tie(conversation, item)
    recs = tuple(records.stamp_inputs(
        tie, {"conversation": conversation, "transcript": item, "pilot": pilot}).items())
    if conv_key is None:
        conv_key = context_key(conversation)
    inputs = (conv_key, transcript.get("agent_type"), recs, None)
    if memo is None:
        return format_stamp(inputs, named), tie
    try:
        key = (inputs, tuple(named))
        stamp = memo.get(key)
    except TypeError:               # inputs no tuple can stand for: digested each time
        return format_stamp(inputs, named), tie
    if stamp is None:
        stamp = memo[key] = format_stamp(inputs, named)
    return stamp, tie


def declarations(records) -> str:
    """The digest of what `vocabularies` would answer now."""
    import labeller_vocab
    return labeller_vocab.declarations(vocabularies(records))


def vocabularies(records) -> dict:
    import labeller_vocab
    return labeller_vocab.vocabularies(CONTRACT, plugin_version(), records.groups())


def stamps(request: dict, records, index=None, convs=None) -> dict:
    """The `stamps` answer: each transcript's stamp now, in request order,
    computed from the run records and the context alone. A transcript whose
    stamp cannot be computed gets a null stamp, as one no labelling covers."""
    import labeller_files
    if convs is None:
        convs = _conversations(request, "stamps")
    version = plugin_version()
    pilot = _pilot(request)
    out = []
    memo: dict = {}
    for conv in convs:
        conv_key = context_key(conv)
        # A sub-agent is stamped from the conversation and its `agent_type` alone (§ The
        # stamp), so the conversation's sub-agents of one type share a stamp.
        agents: dict = {}
        for t in conv["transcripts"]:
            named = parse_stamp(t.get("held"))
            agent = (t.get("agent_type"), *named) if t.get("agent_id") is not None else None
            stamp = agents.get(agent) if agent is not None else None
            if stamp is None:
                try:
                    stamp, _ = transcript_stamp(records, conv, t, pilot, named, conv_key, memo)
                except Exception:  # noqa: BLE001 — one bad transcript fails only itself
                    stamp = None
                if agent is not None and stamp is not None:
                    agents[agent] = stamp
            out.append({"session_id": conv["session_id"], "agent_id": t.get("agent_id"),
                        "stamp": stamp})
    rules = labeller_files.load_rules(data_dir(request["home"]), version)
    return {"contract": CONTRACT, "version": version,
            "declarations": declarations(records), "file_rules": rules.digest,
            "index": _index_out(index), "stamps": out}


# ---------------------------------------------------------------------------
# The label batch


def _last_frame(exc: BaseException) -> str:
    frames = traceback.extract_tb(exc.__traceback__)
    where = ""
    if frames:
        f = frames[-1]
        where = f" at {Path(f.filename).name}:{f.lineno} in {f.name}"
    return f"{type(exc).__name__}: {exc}{where}"


def error_line(session_id: str, agent_id, code: str, detail: str) -> dict:
    return {"session_id": session_id, "agent_id": agent_id, "answer": "error",
            "error": {"code": code, "detail": detail}}


def _transcript_file(projects: Path, path: str) -> Path | None:
    """The transcript's file under `home.projects`, or None for a path that
    leaves it."""
    rel = Path(path)
    if rel.is_absolute() or ".." in rel.parts:
        return None
    return projects / rel


def label_one_transcript(engine, records, conversation: dict, transcript: dict,
                         projects: Path, pilot: frozenset) -> dict:
    """One transcript's answer line: the engine's, or its error line."""
    sid, aid = conversation["session_id"], transcript.get("agent_id")
    try:
        file = _transcript_file(projects, transcript["path"])
        if file is None:
            return error_line(sid, aid, "unreadable",
                              f"{transcript['path']} is not under home.projects")
        stamp, tie = transcript_stamp(records, conversation, transcript, pilot)
        item = {**transcript, "session_id": sid, "file": str(file), "stamp": stamp,
                "conversation": conversation, "pilot": pilot,
                # The engine re-stamps with the slices the file's own content
                # names (the adoption rules R2 to R4): (stamp, tie).
                "restamp": lambda named: transcript_stamp(
                    records, conversation, transcript, pilot, named)}
        line = engine.label_one(item, tie, records)
    except engine.LabelError as e:
        code = getattr(e, "code", None) or (e.args[0] if e.args else "internal")
        detail = getattr(e, "message", None) or (e.args[1] if len(e.args) > 1 else str(e))
        return error_line(sid, aid, code, detail)
    except OSError as e:
        return error_line(sid, aid, "unreadable", f"{transcript['path']}: {e}")
    except Exception as e:  # noqa: BLE001 — one bad transcript fails only itself
        return error_line(sid, aid, "internal", _last_frame(e))
    return {"session_id": sid, "agent_id": aid,
            **{k: v for k, v in line.items() if k not in ("session_id", "agent_id")}}


def label_batch(request: dict, records, write_line, index=None) -> int:
    """The `label` answer as JSON Lines through `write_line`: the header, a
    line per transcript in request order with each conversation's main
    thread before its sub-agents, then the `done` line. Returns the count."""
    import labeller_engine
    convs = _conversations(request, "label")
    projects = Path(request["home"]["projects"])
    pilot = _pilot(request)
    write_line({"contract": CONTRACT, "version": plugin_version()})
    count = 0
    for conv in convs:
        ordered = sorted(conv["transcripts"], key=lambda t: t.get("agent_id") is not None)
        for t in ordered:
            write_line(label_one_transcript(labeller_engine, records, conv, t, projects, pilot))
            count += 1
    write_line({"done": True, "count": count, "index": _index_out(index)})
    return count


# ---------------------------------------------------------------------------
# File classes


def classes(request: dict) -> dict:
    import labeller_files
    files = request.get("files")
    if not isinstance(files, list) or not all(
            isinstance(f, list) and len(f) == 2 and all(isinstance(x, str) for x in f)
            for f in files):
        raise Refusal("request", "`classes` needs `files`, a list of [repo, path] pairs")
    version = plugin_version()
    rules = labeller_files.load_rules(data_dir(request["home"]), version)
    return {"contract": CONTRACT, "version": version, "file_rules": rules.digest,
            "classes": labeller_files.classify(files, rules)}


# ---------------------------------------------------------------------------
# The command


def _dump(value) -> str:
    """An answer's JSON. A long ASCII `index` is put in apart, which the encoder's non-ASCII
    path would take three times as long over."""
    index = value.get("index") if isinstance(value, dict) else None
    if isinstance(index, str) and len(index) > 4096 and index.isascii():
        rest = json.dumps({k: v for k, v in value.items() if k != "index"},
                          ensure_ascii=False, separators=(",", ":"))
        return f'{rest[:-1]}{"," if len(rest) > 2 else ""}"index":{json.dumps(index)}}}'
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def main(argv=None, stdin=None, stdout=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout

    def answer(value) -> None:
        stdout.write(_dump(value) + "\n")
        stdout.flush()

    verb = argv[0] if argv else None
    paused_gc = False
    try:
        if verb == "check":
            import types

            import labeller_check
            return labeller_check.main(argv[1:], types.SimpleNamespace(**globals()), stdout)
        if verb not in VERBS:
            raise Refusal("verb", f"unknown verb {verb!r}; the verbs are " + ", ".join(VERBS))
        if verb == "info":
            # Reads nothing: its request is taken and not read, so that a
            # collector of any contract learns the one spoken here.
            stdin.read()
            answer({"contract": CONTRACT, "version": plugin_version(),
                    "verbs": list(VERBS)})
            return 0
        if verb == "stamps" and gc.isenabled():
            # One request's objects, all freed at the exit: the cyclic collector's passes
            # over them, as the request and the index are parsed, cost a tenth of the call.
            gc.disable()
            paused_gc = True
        request = read_request(stdin)
        check_contract(request)
        check_home(request)
        if verb == "classes":
            answer(classes(request))
        elif verb == "vocabularies":
            records, _ = load_records(request)
            answer(vocabularies(records))
        elif verb == "stamps":
            convs = _conversations(request, "stamps")
            records, blob = load_records(request)
            answer(stamps(request, records, blob, convs))
        else:
            _conversations(request, "label")
            records, blob = load_records(request)
            label_batch(request, records, answer, blob)
    except Refusal as r:
        answer(r.answer())
        return 2
    finally:
        if paused_gc:
            gc.enable()
    return 0


if __name__ == "__main__":
    sys.exit(main())
