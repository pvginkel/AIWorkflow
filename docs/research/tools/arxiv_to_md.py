#!/usr/bin/env python3
"""Download an arXiv paper's LaTeX source and convert it to Markdown.

One paper per invocation. The pipeline is:

    arXiv API      -> title, authors, abstract, dates (used for the front matter
                      and to name the output file)
    /e-print/<id>  -> the submitter's original source tarball
    latexpand      -> flatten \\input/\\include and inline the .bbl, so pandoc
                      sees one self-contained document
    pandoc         -> GitHub-flavoured Markdown, through cleanup.lua

References come from the .bbl the authors submitted; when there is none, pandoc's
citeproc renders them from the .bib instead. Either way the citations survive,
which a default conversion does not manage.

The output file is named ``<arxiv-id>-<title-slug>.md``. Because the slug is not
known until the metadata has been fetched, the "already converted?" check globs
for ``<arxiv-id>-*.md`` rather than testing one exact path.

Not every submission has usable source: some are PDF-only, and a few ship
non-LaTeX formats. Those are reported and skipped rather than faked.
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

import httpx
from slugify import slugify

API_URL = "https://export.arxiv.org/api/query"
EPRINT_URL = "https://export.arxiv.org/e-print/{arxiv_id}"
HTML_URL = "https://arxiv.org/html/{arxiv_id}"
USER_AGENT = "arxiv2md/0.1 (AIWorkflow research tooling; +https://arxiv.org/help/api)"

ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"

HERE = Path(__file__).resolve().parent
LUA_FILTER = HERE / "cleanup.lua"

# 2502.08235, 2502.08235v2, math/0309136, cs.CL/0309136v1 — with or without an
# arxiv.org URL wrapped around them.
ID_RE = re.compile(
    r"(?:arxiv\.org/(?:abs|pdf|html|e-print|format)/)?"
    r"(?P<id>\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Za-z]{2})?/\d{7}(?:v\d+)?)"
    r"(?:\.pdf)?/?$",
    re.IGNORECASE,
)

# Preferred names for the root .tex when a tarball holds several candidates.
MAIN_NAMES = ("main", "ms", "paper", "arxiv", "root", "manuscript", "article", "neurips")


class ConversionError(RuntimeError):
    """The paper cannot be converted — reported, not retried."""


@dataclass(frozen=True)
class Paper:
    arxiv_id: str  # as requested, may carry a version suffix
    title: str
    authors: list[str]
    abstract: str
    published: str
    updated: str
    categories: list[str]
    doi: str | None
    journal_ref: str | None

    @property
    def id_slug(self) -> str:
        """Filename-safe form of the id: ``cs.CL/0309136`` -> ``cs.CL-0309136``."""
        return self.arxiv_id.replace("/", "-")

    @property
    def abs_url(self) -> str:
        return f"https://arxiv.org/abs/{self.arxiv_id}"


def parse_arxiv_id(reference: str) -> str:
    """Accept an abs/pdf URL or a bare id and return the id."""
    match = ID_RE.search(reference.strip())
    if not match:
        raise ConversionError(f"not an arXiv reference: {reference!r}")
    return match.group("id")


def base_id(arxiv_id: str) -> str:
    """Drop the version suffix — v1 and v3 of a paper share an output file."""
    return re.sub(r"v\d+$", "", arxiv_id)


def _text(node: ElementTree.Element | None) -> str:
    if node is None or node.text is None:
        return ""
    return re.sub(r"\s+", " ", node.text).strip()


def fetch_metadata(client: httpx.Client, arxiv_id: str) -> Paper:
    response = client.get(API_URL, params={"id_list": arxiv_id, "max_results": 1})
    response.raise_for_status()
    feed = ElementTree.fromstring(response.text)

    entry = feed.find(f"{ATOM}entry")
    if entry is None:
        raise ConversionError(f"no arXiv entry for {arxiv_id}")
    # The API answers a withdrawn or unknown id with a placeholder entry whose
    # title is literally "Error".
    title = _text(entry.find(f"{ATOM}title"))
    if title.lower() == "error":
        reason = _text(entry.find(f"{ATOM}summary"))
        raise ConversionError(f"arXiv API rejected {arxiv_id}: {reason}")

    return Paper(
        arxiv_id=arxiv_id,
        title=title,
        authors=[_text(a.find(f"{ATOM}name")) for a in entry.findall(f"{ATOM}author")],
        abstract=_text(entry.find(f"{ATOM}summary")),
        published=_text(entry.find(f"{ATOM}published")),
        updated=_text(entry.find(f"{ATOM}updated")),
        categories=[c.attrib["term"] for c in entry.findall(f"{ATOM}category")],
        doi=_text(entry.find(f"{ARXIV_NS}doi")) or None,
        journal_ref=_text(entry.find(f"{ARXIV_NS}journal_ref")) or None,
    )


def download_source(client: httpx.Client, arxiv_id: str) -> bytes:
    response = client.get(EPRINT_URL.format(arxiv_id=arxiv_id))
    response.raise_for_status()
    return response.content


def unpack_source(payload: bytes, dest: Path) -> None:
    """Write the e-print payload out as a source tree under ``dest``.

    arXiv hands back one of: a gzipped tar, a bare gzipped .tex, an
    uncompressed tar, or — for submissions that never had TeX — a PDF.
    """
    if payload[:5] == b"%PDF-":
        raise ConversionError("PDF-only submission: arXiv holds no LaTeX source")

    for mode in ("r:gz", "r:"):
        try:
            with tarfile.open(fileobj=io.BytesIO(payload), mode=mode) as tar:
                tar.extractall(dest, filter="data")
            return
        except tarfile.TarError:
            continue

    # Not a tar: a single-file submission, gzipped or not.
    if payload[:2] == b"\x1f\x8b":
        payload = gzip.decompress(payload)
    if payload[:5] == b"%PDF-":
        raise ConversionError("PDF-only submission: arXiv holds no LaTeX source")
    (dest / "main.tex").write_bytes(payload)


def read_tex(path: Path) -> str:
    """TeX sources predate the utf-8 consensus; never fail on an odd byte."""
    return path.read_bytes().decode("utf-8", errors="replace")


def find_main_tex(root: Path) -> Path:
    """Pick the root document out of an unpacked source tree."""
    tex_files = sorted(p for p in root.rglob("*.tex") if p.is_file())
    if not tex_files:
        raise ConversionError("source archive contains no .tex file")

    with_document = [p for p in tex_files if r"\begin{document}" in read_tex(p)]
    candidates = with_document or tex_files
    if len(candidates) == 1:
        return candidates[0]

    def rank(path: Path) -> tuple[int, int, int, int]:
        body = read_tex(path)
        return (
            0 if path.stem.lower() in MAIN_NAMES else 1,
            len(path.relative_to(root).parts),  # prefer the top of the tree
            0 if re.search(r"\\documentclass|\\documentstyle", body) else 1,
            -path.stat().st_size,
        )

    return min(candidates, key=rank)


def find_bbl(root: Path, main: Path) -> Path | None:
    """The .bbl arXiv requires alongside the source — inlining it keeps the
    reference list in the Markdown."""
    bbls = sorted(p for p in root.rglob("*.bbl") if p.is_file())
    if not bbls:
        return None
    for bbl in bbls:
        if bbl.stem == main.stem:
            return bbl
    return bbls[0]


def find_bibs(root: Path) -> list[Path]:
    """BibTeX databases, used only when the source ships no .bbl."""
    return sorted(p for p in root.rglob("*.bib") if p.is_file())


def flatten(main: Path, bbl: Path | None) -> str:
    """Resolve \\input/\\include (and the bibliography) into one document."""
    command = ["latexpand", "--empty-comments"]
    if bbl is not None:
        command += ["--expand-bbl", str(bbl.resolve())]
    command.append(main.name)

    result = subprocess.run(
        command, cwd=main.parent, capture_output=True, timeout=180, check=False
    )
    if result.returncode != 0 or not result.stdout.strip():
        # latexpand is a convenience, not a requirement: without it pandoc still
        # converts the root file, just without the \input-ed sections.
        print("  latexpand failed, converting the root file only", file=sys.stderr)
        return read_tex(main)
    return result.stdout.decode("utf-8", errors="replace")


BIBITEM_RE = re.compile(r"\\bibitem(\[[^]]*\])?\{([^}]+)\}")

# Rubber lengths ("\hskip 1em plus 0.5em minus 0.4em"). IEEEtran's .bbl puts one
# in every entry, and pandoc's reader cannot parse the plus/minus components: it
# discards the whole thebibliography environment without a word of warning.
GLUE_RE = re.compile(
    r"\\[hv](?:skip|glue)\s*[-+]?[\d.]*\s*(?:em|ex|pt|pc|cm|mm|in|bp|dd|sp|mu|\\fill)?"
    r"(?:\s*(?:plus|minus)\s*[-+]?[\d.]*\s*(?:em|ex|pt|pc|cm|mm|in|bp|dd|sp|mu|\\fill))*"
)

# natbib probes for urlstyle with \csname, which pandoc renders as a stray word.
# The conditional is bounded, so a stray \csname elsewhere cannot swallow half
# the document; whatever \csname survives that is dropped name and all, since
# pandoc cannot expand a constructed control sequence either way.
CSNAME_PROBE_RE = re.compile(
    r"\\expandafter\\ifx\\csname\s+\w+\\endcsname\\relax.{0,300}?\\fi", re.DOTALL
)
CSNAME_RE = re.compile(r"\\csname[^\\]*\\endcsname")

# Markdown output width. Prose wrapped for reading and reviewable diffs; wide
# enough that tables and long URLs rarely have to break out of it.
COLUMNS = 100


def prepare_tex(tex: str) -> str:
    """The rewrites pandoc cannot do for us, all of them about the references.

    Pandoc collapses a whole ``thebibliography`` into one paragraph and throws
    the citation keys away, so a reference list comes out as anonymous prose.
    Stamping the key onto each entry keeps it joinable with the ``[key]``
    markers cleanup.lua leaves at the citation sites.

    The rest is bibliography-style boilerplate that pandoc either mis-renders or
    trips over: the environment's width argument (``{53}``) becomes a stray
    number in front of the first reference, the natbib urlstyle probe a stray
    word, and rubber lengths cost the entire reference list.
    """
    tex = BIBITEM_RE.sub(
        lambda m: f"\\bibitem{m.group(1) or ''}{{{m.group(2)}}} \\textbf{{{m.group(2)}}} ", tex
    )
    tex = re.sub(r"(\\begin\{thebibliography\})\{[^}]*\}", r"\1{}", tex)
    tex = CSNAME_PROBE_RE.sub("", tex)
    tex = CSNAME_RE.sub("", tex)
    return GLUE_RE.sub(" ", tex)


# tcolorbox definitions take arguments pandoc's LaTeX reader cannot parse, and
# it aborts on them rather than skipping them. They only ever affect how a box
# is drawn, so dropping the definitions costs nothing in a Markdown rendering.
BOX_DEFINITION_RE = re.compile(
    r"\\(?:new|renew|provide|declare)tcolorbox|\\NewTColorBox|\\DeclareTColorBox"
    r"|\\newtcbtheorem|\\tcbset|\\newmdenv|\\newmdtheoremenv"
)


def salvage(tex: str) -> str:
    """Drop the styling macro definitions pandoc chokes on, arguments and all."""
    kept: list[str] = []
    cursor = 0
    while True:
        match = BOX_DEFINITION_RE.search(tex, cursor)
        if match is None:
            kept.append(tex[cursor:])
            return "".join(kept)
        kept.append(tex[cursor : match.start()])

        # Swallow the definition's [optional] and {mandatory} groups.
        cursor = match.end()
        while cursor < len(tex):
            while cursor < len(tex) and tex[cursor] in " \t\n":
                cursor += 1
            if cursor >= len(tex) or tex[cursor] not in "{[":
                break
            depth = 0
            while cursor < len(tex):
                if tex[cursor] in "{[":
                    depth += 1
                elif tex[cursor] in "}]":
                    depth -= 1
                cursor += 1
                if depth == 0:
                    break


def to_markdown(tex: str, bibs: list[Path]) -> str:
    """Convert flattened LaTeX to GitHub-flavoured Markdown via pandoc."""
    base = [
        "pandoc",
        "--to=gfm+tex_math_dollars",
        f"--columns={COLUMNS}",
        # \section becomes H2, leaving H1 for the paper title we prepend.
        "--shift-heading-level-by=1",
    ]
    # Order matters: citeproc has to resolve the citations before cleanup.lua
    # sees them, or the filter would overwrite what it produced.
    for bib in bibs:
        base += ["--bibliography", str(bib)]
    if bibs:
        base += ["--citeproc", "--metadata", "reference-section-title=References"]
    base.append(f"--lua-filter={LUA_FILTER}")
    # Increasingly lossy attempts: the plain reader gives the cleanest Markdown,
    # salvage() sacrifices styling macros, and raw_tex stops pandoc bailing out
    # on anything left that it cannot model, at the cost of leaking LaTeX.
    attempts = [
        ("--from=latex", tex),
        ("--from=latex", salvage(tex)),
        ("--from=latex+raw_tex", salvage(tex)),
    ]
    errors = []
    for reader, source in attempts:
        result = subprocess.run(
            [*base, reader],
            input=source.encode("utf-8"),
            capture_output=True,
            timeout=600,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.decode("utf-8")
        message = result.stderr.decode("utf-8", errors="replace").strip()
        errors.append(f"[{reader}] {' / '.join(message.splitlines()[-3:])}")

    raise ConversionError("pandoc could not convert the source:\n  " + "\n  ".join(errors))


ARTICLE_RE = re.compile(r"<article\b.*?</article>", re.DOTALL | re.IGNORECASE)


def html_fallback(client: httpx.Client, arxiv_id: str) -> str:
    """arXiv's own HTML rendering, for sources pandoc's LaTeX reader rejects.

    Lossier than the LaTeX path (equations and citations come out as the
    renderer drew them) but complete: it carries every section, figure
    caption and reference, which is what a reading corpus needs. Only the
    ``<article>`` element is converted, so the page chrome stays out.
    """
    response = client.get(HTML_URL.format(arxiv_id=arxiv_id))
    response.raise_for_status()
    page = response.text
    match = ARTICLE_RE.search(page)
    html = match.group(0) if match else page
    result = subprocess.run(
        ["pandoc", "--from=html", "--to=gfm+tex_math_dollars", f"--columns={COLUMNS}",
         "--shift-heading-level-by=1"],
        input=html.encode("utf-8"), capture_output=True, timeout=600, check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise ConversionError("HTML fallback failed too: " + " / ".join(message.splitlines()[-2:]))
    markdown = result.stdout.decode("utf-8")
    # The rendering repeats the title/abstract block heading() already prepends.
    markdown = re.sub(r"\A.*?(?=\n#+ +1\b|\n#+ +1\.|\n## +Introduction)", "", markdown,
                      count=1, flags=re.DOTALL)
    return markdown


def yaml_value(value) -> str:
    """JSON is a subset of YAML 1.2, so json.dumps is a safe scalar quoter."""
    if isinstance(value, list):
        return "[" + ", ".join(json.dumps(v) for v in value) + "]"
    return json.dumps(value)


def front_matter(paper: Paper, source: str) -> str:
    fields = {
        "title": paper.title,
        "authors": paper.authors,
        "arxiv_id": paper.arxiv_id,
        "url": paper.abs_url,
        "published": paper.published,
        "updated": paper.updated,
        "categories": paper.categories,
    }
    if paper.doi:
        fields["doi"] = paper.doi
    if paper.journal_ref:
        fields["journal_ref"] = paper.journal_ref
    fields["source"] = source

    lines = ["---"]
    lines += [f"{key}: {yaml_value(value)}" for key, value in fields.items()]
    lines.append("---")
    return "\n".join(lines)


def heading(paper: Paper) -> str:
    """Title and abstract, which the converted body never carries.

    Pandoc lifts ``\\title`` and ``\\begin{abstract}`` into document metadata
    rather than into the body, so a plain conversion starts abruptly at the
    introduction. The API copy of both is authoritative anyway.
    """
    # break_on_hyphens off: pandoc does not split "LLM-based" across lines when
    # it wraps the body, and the abstract should not read differently.
    abstract = "\n".join(textwrap.wrap(paper.abstract, width=COLUMNS, break_on_hyphens=False))
    return f"# {paper.title}\n\n## Abstract\n\n{abstract}"


def tidy(markdown: str) -> str:
    """Squash the blank-line runs and stray artefacts pandoc leaves behind."""
    markdown = markdown.replace(" ", " ")
    markdown = re.sub(r"\n{3,}", "\n\n", markdown)
    markdown = re.sub(r"[ \t]+\n", "\n", markdown)
    # Some \cite variants are dropped before the filter sees them, leaving the
    # sentence with a gap in front of its punctuation.
    markdown = re.sub(r" +([,.;:)])", r"\1", markdown)
    return markdown.strip() + "\n"


def existing_output(outdir: Path, arxiv_id: str) -> Path | None:
    pattern = f"{base_id(arxiv_id).replace('/', '-')}-*.md"
    return next(iter(sorted(outdir.glob(pattern))), None)


def output_path(outdir: Path, paper: Paper) -> Path:
    slug = slugify(paper.title, max_length=70, word_boundary=True) or "untitled"
    return outdir / f"{base_id(paper.id_slug)}-{slug}.md"


def convert(
    reference: str, outdir: Path, *, force: bool, delay: float, keep_source: Path | None
) -> Path | None:
    arxiv_id = parse_arxiv_id(reference)

    outdir.mkdir(parents=True, exist_ok=True)
    if not force:
        existing = existing_output(outdir, arxiv_id)
        if existing is not None:
            print(f"{arxiv_id}: already converted -> {existing.name}")
            return existing

    headers = {"User-Agent": USER_AGENT}
    with httpx.Client(headers=headers, follow_redirects=True, timeout=120.0) as client:
        paper = fetch_metadata(client, arxiv_id)
        print(f"{arxiv_id}: {paper.title}")

        # arXiv asks bulk callers to leave a gap between requests.
        if delay > 0:
            time.sleep(delay)
        payload = download_source(client, arxiv_id)

    provenance = "arXiv LaTeX e-print, converted with latexpand + pandoc"
    try:
        with tempfile.TemporaryDirectory(prefix="arxiv2md-") as tmp:
            source = Path(tmp) / "src"
            source.mkdir()
            unpack_source(payload, source)

            # Copied before the conversion runs: a failed conversion is exactly
            # when the source is worth looking at.
            if keep_source is not None:
                target = keep_source / base_id(paper.id_slug)
                shutil.rmtree(target, ignore_errors=True)
                shutil.copytree(source, target)

            main = find_main_tex(source)
            # A .bbl is the reference list the authors actually published, so it
            # wins. Only when the submission omits one does the .bib get handed
            # to citeproc, which resolves whatever the citations happen to name.
            bbl = find_bbl(source, main)
            bibs = [] if bbl else find_bibs(source)
            tex = flatten(main, bbl)
            markdown = to_markdown(prepare_tex(tex), bibs)
    except ConversionError as error:
        # PDF-only submissions and LaTeX pandoc cannot parse both land here;
        # arXiv's HTML rendering covers most of them.
        print(f"  LaTeX path failed ({str(error).splitlines()[0]}); "
              "falling back to the arXiv HTML rendering", file=sys.stderr)
        with httpx.Client(headers=headers, follow_redirects=True, timeout=120.0) as client:
            markdown = html_fallback(client, arxiv_id)
        provenance = "arXiv HTML rendering, converted with pandoc (LaTeX source not convertible)"

    destination = output_path(outdir, paper)
    document = f"{front_matter(paper, provenance)}\n\n{heading(paper)}\n\n{tidy(markdown)}"
    destination.write_text(document, encoding="utf-8")
    print(f"  wrote {destination.name} ({destination.stat().st_size // 1024} KiB)")
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("reference", help="arXiv abs/pdf URL or bare id")
    parser.add_argument(
        "-o", "--outdir", type=Path, default=HERE.parent / "articles",
        help="where the .md goes (default: ../articles)",
    )
    parser.add_argument(
        "-f", "--force", action="store_true", help="re-convert even if the .md exists"
    )
    parser.add_argument(
        "--delay", type=float, default=3.0,
        help="seconds to wait before pulling the e-print, per arXiv's rate guidance",
    )
    parser.add_argument(
        "--keep-source", type=Path, default=None,
        help="also copy the unpacked LaTeX tree here, for debugging a bad conversion",
    )
    args = parser.parse_args(argv)

    try:
        convert(
            args.reference,
            args.outdir.resolve(),
            force=args.force,
            delay=args.delay,
            keep_source=args.keep_source.resolve() if args.keep_source else None,
        )
    except (ConversionError, httpx.HTTPError, subprocess.SubprocessError) as error:
        print(f"FAILED {args.reference}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
