# Slice 023's cards section as filed (PilotAppSpecs 8e1a468, `slices/backlog/023_the_chat_ui/slice.md`)

### Cards, verbatim from the tracker (2026-10-25)

### P-36 — Slice 012: name its parts of F98.3 and F133 (In the chat as an icon, the chat's unsent text) in the plan's §3 row 012, so the ledger tracks them

State: Accepted · Type: Task · Tags: (none returned) · Reporter: jeeves · Created: 2026-10-23 · Parent: EPIC-9 [New] Pilot v1 · Relates: P-9

**Description:**

```
From slice 005's close-out report, entry D6, which the operator agreed to on 2026-10-23 ("I've read the close out and agree with the recommendations."). Its proposal: "Name them at 006's and 012's planning, as 004's D6 ruled for F1.6 and F113: F98.3's panel and overlay and F133's panel state 006's, F98.3's In the chat icon and F133's chat text 012's; the rows go back to partial with that edit."

005's doc phase ticked the ledger's F98.3 and F133 rows delivered while parts of them are unbuilt and named in no later slice's Features cell. 006 carries its half as requirement 13 of its `slice.md`; 012 has no slice folder yet, so this card carries 012's half to its triage: name in row 012's Features cell F98.3's In the chat as an icon in the block head (Ruling D2) and F133's chat unsent text keyed by project, and set the two rows partial if 006's planning has not already, `design/tools/check_ledger.py` green after.

The entry in full: PilotAppSpecs `slices/completed/005_timeline_and_items/close-out.md`, D6 (`close_out.py show`).
```

**Comments:**

- jeeves · 2026-10-24 08:36Z (7-6449):

```
Inbox 2026-10-24: slice, as proposed and approved by the operator: for slice 012's triage.
```

### P-54 — Slice 012: a save of the handbook or the project document announces project_changed, so an open overlay shows Pilot's new text and dots as an item's does

State: Accepted · Type: Task · Tags: (none returned) · Reporter: jeeves · Created: 2026-10-24 · Parent: EPIC-9 [New] Pilot v1 · Relates: P-10

**Description:**

```
From slice 006's close-out report, entry D3, which the operator agreed to on 2026-10-24 ("Agreed with all items."). Its proposal: "Fold into 012, which makes Pilot's dots live from the turn: a handbook or draft save announcing project_changed belongs with that; until then P10 shows a save on the next read, as the ruling has the dots clear."

`DocumentService.publish` (`backend/app/engine/documents.py`, the ProjectChanged at the end of publish) emits ProjectChanged for an item's text only. A project document's publish emits it only through `timeline_moved`, when a draft save renames the project. So a save of `handbook.md` reaches no browser, and a save of `project.md` reaches one only when its title changes. An open handbook or project-document overlay shows Pilot's new text and its dots only on its next read. The change itself is one line: emit ProjectChanged in publish for a project document whose text changed, and amend the event's docstring.

012 has no slice folder yet, so this card carries the ask to its triage, as P-36 does.

The entry in full: PilotAppSpecs `slices/completed/006_documents_and_overlay/close-out.md`, D3 (`close_out.py show`).
```

**Comments:**

none

### P-47 — PilotApp frontend: the shared Markdown renderer rewrites quote tags inside code and draws chips that do nothing outside a chat

State: Accepted · Type: Task · Tags: (none returned) · Reporter: jeeves · Created: 2026-10-24 · Parent: EPIC-9 [New] Pilot v1 · Relates: P-12

**Description:**

```
From slice 008's close-out report, entry B9, a card request the operator said yes to on 2026-10-24 ("I read everything (except the closed ones). Two items have a disposition. The rest I don't see why I would not follow the recommendation.").

### P-53 — PilotApp frontend: the Documents tab reads "None yet." for both lists while its reads are pending, and after they fail

State: Accepted · Type: Task · Tags: (none returned) · Reporter: jeeves · Created: 2026-10-24 · Parent: EPIC-9 [New] Pilot v1 · Relates: P-10

**Description:**

```
From slice 006's close-out report, entry B12, carded on the operator's word on 2026-10-24 ("Agreed with all items.").

`usePanelDocuments` takes `timeline.data?.items ?? []` (`frontend/src/hooks/use-panel.ts:106`). So DocumentsTab says "None yet." under both headings (`documents-tab.tsx:59`, `:73`) before the timeline is read, and keeps saying it once a read fails. The panel is open by default at 1200 px and wider, so every first open of a project there says it has no documents and then fills in. A failed read leaves a false "none" with nothing on the screen saying otherwise; only a failed mutation raises a toast (`frontend/src/lib/query-client.ts:35-43`).

Give the tab states of its own for a read still pending and for one that failed. The timeline's pattern is the likely shape for pending: it draws nothing until read, and says "Nothing yet" only for a list known to be empty (`timeline.tsx:170`). Still open:
- whether the headings stand over an empty body while pending;
- whether a failed read says so in the panel (F113's "did not load");
- what the project document's row reads before the draft read gives its title ("Project document" today, `:36`).

The entry in full: PilotAppSpecs `slices/completed/006_documents_and_overlay/close-out.md`, B12 (`close_out.py show`).
```

**Comments:**

- jeeves · 2026-10-24 18:29Z (7-6505):

```
Plan review of the open cards, 2026-10-24: for slice 012's triage, approved by the operator (implementation plan step 10). 012 adds the Chat tab to the same panel, which wants the same pending and failed states.
```

### P-49 — PilotApp frontend: a work item's Stop it and Resume drop the keyboard focus to the page body

State: Accepted · Type: Task · Tags: (none returned) · Reporter: jeeves · Created: 2026-10-24 · Parent: EPIC-9 [New] Pilot v1 · Relates: P-12

**Description:**

```
From slice 008's close-out report, entry B13, a card request the operator said yes to on 2026-10-24 ("I read everything (except the closed ones). Two items have a disposition. The rest I don't see why I would not follow the recommendation.").

Triage research, 2026-10-25 (the standing-decisions check): P-47 — F39.3 (`features.md`) — "rendered as the chip wherever the tag stands — in Pilot's replies too… clicking it goes to the item or block, opening the overlay when needed." The ask is a chip only "on screens where a chip has something to open", and the card leaves "the tag as written" or "a plain label" open. Both cut across the ruling that a tag renders as a chip everywhere it stands. Only the "chip opens the item on its timeline" option agrees with it.

## Q&A and operator rulings (triage, 2026-10-25)
