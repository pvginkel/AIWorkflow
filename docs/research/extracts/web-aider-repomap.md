---
source: web-aider-repomap-docs.md + web-aider-repomap-post-2023.md
paper: "Repository map" (aider docs, undated) + "Building a better repository map with tree sitter"
  — Paul Gauthier / Aider-AI, 2023-10-22 — https://aider.chat/docs/repomap.html and
  https://aider.chat/2023/10/22/repomap.html
read: full (both pages; they overlap heavily — the docs page is a condensed restatement of the 2023
  post plus two sentences on dynamic budget sizing)
extracted_by: Claude Opus 5, 2026-08-22
---

**Practitioner source. There is not a single measurement on either page** — no benchmark, no A/B, no
token-count comparison, no accuracy or cost figure, no ablation. Every effect claim is qualitative
and hedged by the tool's author. The only numbers are a default setting (`--map-tokens` = 1k) and a
list of 17 languages. A design description, not evidence.

## Core results

1. **A whole-repo symbol map, sent with every change request.** "Aider sends a repo map to the LLM
   along with each change request from the user. The repo map contains a list of the files in the
   repo, along with the key symbols which are defined in each file. It shows how each of these
   symbols are defined, by including the critical lines of code for each definition" (both pages,
   §"Using a repo map to provide context"). The unit is the git repository, not the task.

2. **Contents: verbatim definition lines, no bodies.** The published sample (both pages) renders a
   file path, then source lines prefixed `│`, with elided regions collapsed to `⋮...`:
   `│class Coder:` / `│    abs_fnames = None` / `⋮...` / `│    @classmethod` / `│    def create(`
   followed by each parameter on its own line / `⋮...` / `│    def run(self, with_message=None):`.
   So: class declarations, full multi-line call signatures (decorators and defaults included), and
   some class-level attribute assignments — lifted verbatim from source, not paraphrased. Bodies,
   docstrings, comments, imports and call-sites are omitted.

3. **Extraction: tree-sitter, definitions *and* references.** 2023 post, §"Using tree-sitter":
   tree-sitter parses each file to an AST; "we can identify where functions, classes, variables,
   types and other definitions occur… We can also identify where else in the code these things are
   used or referenced. Aider uses all of these definitions and references to determine which are the
   most important identifiers." The references half is what makes ranking possible — a
   definitions-only index (ctags) could not rank. Implementation: the `py-tree-sitter-languages` pip
   module (binary wheels) with aider's modified `tags.scm` queries for 17 languages (§Credits).

4. **Ranking: a graph ranking algorithm over a file-level dependency graph. Neither page names
   PageRank.** Identical wording on both: "analyzing the full repo map using a graph ranking
   algorithm, computed on a graph where each source file is a node and edges connect files which
   have dependencies." Symbol selection is stated separately: the map "only includes the most
   important identifiers, the ones which are most often referenced by other portions of the code."
   (PageRank is aider's actual implementation and widely reported as such, but **it is not stated in
   these sources** — do not cite these pages for it.)

5. **Budget: `--map-tokens`, default 1k, soft.** "Aider optimizes the repo map by selecting the most
   important parts of the codebase which will fit into the active token budget… The token budget is
   influenced by the `--map-tokens` switch, which defaults to 1k tokens" (docs, §Optimizing). The
   docs page adds the only fact absent from the 2023 post: "Aider adjusts the size of the repo map
   dynamically based on the state of the chat. It will usually stay within that setting's value. But
   it does expand the repo map significantly at times, especially when no files have been added to
   the chat and aider needs to understand the entire repo as best as possible." The budget is a
   target, deliberately overshot when the model has no other grounding. No number for the expansion.

6. **Per-request re-ranking toward the chat.** "The optimization identifies and maps the portions of
   the code base which are most relevant to the current state of the chat" (docs, §Optimizing). The
   map is a function of (repo, chat state), not a static artefact. *How* chat state enters the
   ranking is unstated, as is whether files already in the chat are dropped from the map.

7. **Claimed effects — two, both hedged.** (a) Sufficiency: signatures from everywhere "alone may
   give it enough context to solve many tasks… it can probably figure out how to use the API
   exported from a module just based on the details shown in the map." (b) Routing: "If it needs to
   see more code, the LLM can use the map to figure out which files it needs to look at." Nothing
   stronger is claimed anywhere on either page.

8. **Freshness is never discussed.** Neither page contains the words cache, stale, invalidate,
   incremental or regenerate. Only that the map is "built automatically" from source and sent "along
   with each change request". The implication is strong but unstated: the map is a pure derivation
   of the working tree, so it cannot drift — no authored copy, therefore no staleness rule.

9. **Deliberate omissions.** Function bodies; low-reference identifiers ("doesn't contain *every*
   class, method and function from those files"); files outside the 17 tree-sitter languages (config,
   markdown, SQL, templates, YAML); anything below file granularity in the graph — nodes are files,
   so intra-file structure is rendered but not ranked. And **change localisation**: §Future work is
   explicit that aider solves step 2 (how code relates) and not step 1 (find the code to change) —
   "aider relies on the user to specify which source files will need to be modified."

10. **Why tree-sitter replaced ctags** (§"What about ctags?"): a richer map (full call signatures
    straight from source), many languages via a pip wheel installed with the tool, and — the
    operationally interesting one — removal of a **user-installed external binary**
    (`universal-ctags`). The dependency envelope of the map generator was a first-class constraint.

## Method and setting (what was actually built/tested)

Built, not tested. The setting is aider, an interactive single-agent CLI pair-programmer, circa
GPT-4 (2023) and unspecified frontier models (docs page). The consumer of the map is **one chat
model with no file-reading tools of its own**: it cannot open a file; it asks, and aider or the user
`/add`s the file. Horizon is a human-driven conversation, not an autonomous loop. Nothing is
trained; everything is prompted. Alternatives are named and rejected on reasoning alone: send the
whole codebase (does not fit); hand-pick whole files (works "pretty well" but "sending whole files
is a bulky way to send code context, wasting the precious context window"). Open source: aider,
`py-tree-sitter-languages`, the modified `tags.scm` queries.

## Relevance to P1–P4

**P2 (orientation reads dominate the long sessions).** This is the problem the map targets, one step
upstream: claim 7b is that a map lets the model *name* the files it needs instead of hunting. Our
14–65 orientation turns before a first edit (≈ 38 % of a big code-writer's cost) is that hunt. The
transfer gap is large and cuts both ways: aider's model *cannot* hunt — the map is its only route to
the repo — whereas our sessions have Read/Grep and already navigate. So this source gives **no
evidence about the marginal value of a map to an agent that already has a tool loop**; it shows only
that a ~1k-token map was judged sufficient to route a model with nothing else. What it does
establish is a feasibility bound: a whole-repo routing index at ~1k tokens is a shipped artefact,
not an aspiration.

**P3 (every session rebuilds the same picture).** The map is the canonical instance of the fix
shape: compute the shared picture once, mechanically, prefix it to every request. Aider recomputes
per-request and per-chat rather than caching a document — the artefact is cheap enough that caching
was never the question. Note the tension with our economics: a map that re-ranks per dispatch
changes the prefix and would break prompt-cache reuse across our ≈ 30 sessions. Aider says nothing
about prompt caching (barely a practice at the 2023 post's date).

**P4 (unknown grounding cost of smaller reads).** Silent, and silent in a telling way: aider
replaced whole-file context with signature-only context on the author's judgment and never published
a quality delta. Adopting a map means adopting an unmeasured trade in exactly the dimension P4
names. The page hedges its own claim — "may give it enough context", "can probably figure out".

Nothing bears on P1 beyond the generic direction (fewer input tokens per request).

## Interventions this paper supports

- **Generate a mechanical repo index and hand it to orientation-heavy roles.** Rests on results 2–5
  (verbatim signature lines, ranked by reference count, clipped to a budget). Direction: replaces
  some orientation turns with a prefix read; artefact cost ~1–4k tokens per session. **Loses:**
  bodies, docstrings, and everything the ranking clips. A code-writer is no worse off (it can still
  Grep), but a reviewer that reads the map as complete would be wrong — label it an index, never an
  inventory.
- **Rank by references, not definitions** (result 3): definitions-only was exactly why ctags was
  dropped. Stdlib `ast` yields both for Python (`FunctionDef`/`ClassDef`; `Name`/`Attribute`), and
  file-level PageRank is ~25 lines of power iteration — no dependency. **Loses:** non-Python files.
- **Make the index derived, never authored** (result 8): regenerate from the working tree at
  dispatch time; never commit a hand- or model-maintained copy. That *is* the staleness rule — there
  isn't one, because nothing can be stale. **Loses:** the ability to put judgment in it (why a module
  exists, which abstraction is preferred), which is what our doc phase's authored prose is for. The
  design says split those two surfaces, not merge them.
- **Treat the token budget as a soft target with a documented overshoot case** (result 5): aider's
  is 1k, expanded "significantly" when the model holds no files. Our analogue: a larger index for
  the plan-writer and a slice's first phase, smaller once plan.md names the target files.
- **Do not expect the index to localise the change** (result 9): step 1 stays outside it. Our
  plan.md `Target:` lines are already our step-1 answer; a map sits under them, not instead of them.

## Applicability caveats

- **No numbers, anywhere.** Nothing here can size an intervention; it can only justify trying one.
- **Model mismatch.** GPT-4, 2023, chat scaffold. No Claude, no maximum-effort reasoning, no
  evidence about how a model that *can* read files values a map it did not build.
- **Scaffold mismatch is the big one.** Aider's model has no Read/Grep; the map substitutes for
  browsing. Our agents browse. The map's value for us is a *turn-count* claim this source never
  tested, not the *feasibility* claim it does support.
- **Dependency mismatch.** The extractor is a pip package with binary wheels; our plugin is
  stdlib-only, so multi-language coverage is unavailable at aider's fidelity — stdlib `ast` covers
  Python well, heuristics cover the rest badly. Aider treated this same dependency question as
  decisive when dropping ctags; our resolution must be different (stdlib, weaker coverage) rather
  than the same (a better package).
- **Cache interaction unaddressed.** Per-request re-ranking (result 6) is incompatible with a stable
  cached prefix. We would likely want aider's *content* design at a *per-slice* regeneration cadence
  — a variant with no support here.
- **Granularity and repo shape.** File-level nodes; no evidence for symbol-level graphs, and none
  for repos like ours, where markdown carries most of the contract and is invisible to tree-sitter.

## Briefing check

The briefing files this under Q4: *"per-repository orientation map (S3, Aider) — our doc phase
produces that surface, a loop-internal flywheel whose staleness needs a rule."*

**Supported, with one correction and one addition.** Supported: the artefact is real, is
per-repository ("a concise map of your whole git repository"), and is an orientation surface in
exactly the briefing's sense — its two claimed jobs are "figure out how to use the API exported from
a module" and "figure out which files it needs to look at".

**Correction — "staleness needs a rule" mis-frames the lesson.** Aider's map has no staleness rule
because it is not maintained: it is recomputed from the working tree and re-ranked against the
current chat on every request (results 1, 6, 8). The lesson is not *write a staleness rule for the
produced map* but *make the map a derivation so the question cannot arise*, confining staleness to
the authored prose that genuinely needs judgment. A doc phase where a model writes the orientation
surface owns a staleness problem aider deliberately never took on.

**Addition — "loop-internal flywheel" does not describe this.** Nothing accumulates: each map is
computed fresh, carrying nothing forward from previous requests. A flywheel (state that improves
across runs) is a different mechanism with different failure modes, and this map is not evidence
for it.

Also flag back: the implied "PageRank" attribution cannot be sourced from these pages — they say
only "a graph ranking algorithm" over a file-dependency graph (result 4). And with no benchmark
anywhere, Q4 gets a design pattern and a feasibility bound from Aider, not an effect size.
