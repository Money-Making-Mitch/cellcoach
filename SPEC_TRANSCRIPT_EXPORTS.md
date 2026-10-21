# CELL COACH — Call Transcript & Coaching-Review Exports
## Spec for executing model — implement exactly. Templates are normative.

### GOAL
Every call produces a permanent, reviewable record with TWO downloadable views:

1. **Clean Call Transcript** — rep + prospect only, the human conversation.
2. **Coaching Review Transcript** — the full teaching artifact: each prospect turn,
   the coach's response to it, and the rep's actual next line, interleaved in time
   order, so you can review *what the prospect said → what the coach called → what
   the rep ran → how the prospect reacted*.

Both must be readable by a human learning from the call AND cleanly parseable by an
AI that's handed the file later to improve the app or retrain a persona. The design
below satisfies both at once (human-readable Markdown body + a machine-readable JSON
block appended to the coaching file).

### HARD RULES
- Touch only `cellcoach.py` and `cellcoach_ui.html` in `cell_coach/`.
- No pip installs, no new JS libs, no build step.
- Does not change the live coaching behavior — this is a capture + export layer.
- Must work for BOTH a call that just ended AND any historical call in Past Calls,
  via the same code path (store the data, render on demand).
- Interoperates with the screening spec (SPEC_CALL_SCREENING.md): screening-flagged
  lines are captured and MARKED in the log, not dropped — see §4.

---

## 1. THE CAPTURE LAYER (frontend, cellcoach_ui.html)

Today coach responses render live and vanish; only the raw transcript is kept. Add a
single chronological event log that records everything as it happens.

Add to `S` (state) in `start()`, reset each call:
```js
S.callLog = [];   // chronological event stream, the source of truth for exports
S.seq = 0;        // monotonic sequence counter
```

Helper:
```js
function logEvent(type, payload){
  S.seq += 1;
  S.callLog.push(Object.assign({
    seq: S.seq,
    t: fmtElapsed(S.seconds),     // "mm:ss" since call start (S.seconds already tracked)
    ts: new Date().toISOString()  // absolute timestamp
  }, {type}, payload));
}
function fmtElapsed(sec){
  return String(Math.floor(sec/60)).padStart(2,'0')+':'+String(sec%60).padStart(2,'0');
}
```

Wire it in at the three existing choke points — no new event sources needed:

- In `addTranscriptLine(speaker, text, isScreening)`: after appending to the
  transcript, also `logEvent(speaker === 'rep' ? 'rep' : 'prospect', {text, screening: !!isScreening})`.
- In `showCoaching(a, isInstant)`: log the coaching event. Capture the full analysis
  so nothing is lost:
  ```js
  logEvent('coach', {
    trigger_seq: _lastProspectSeq,          // see below
    source: isInstant ? 'instant' : 'gpt',
    say_next: a.say_next || '',
    objection: a.objection || null,
    coach_type: a.coach_type || '',
    alt_suggestion: a.alt_suggestion || null,
    checklist: a.checklist || null,         // null for instant/screening cards
    temperature: a.temperature || null,
    prospect_intel: a.prospect_intel || null
  });
  ```
- Track `_lastProspectSeq`: a module-level var set to `S.seq` every time a
  non-screening PROSPECT line is logged. This links each coach response back to the
  exact prospect line that triggered it (used for the paired layout in File 2). For
  screening cards, `trigger_seq` links to the screening line's seq instead.

`S.callLog` is the ONE source of truth. The clean transcript and the coaching review
are both just different renderings of it — never maintain them separately.

---

## 2. PERSISTENCE (backend, cellcoach.py)

Add a `coach_log` column to the `calls` table (same ALTER-TABLE-in-try pattern
already used for `recording`):
```python
try:
    con.execute("ALTER TABLE calls ADD COLUMN coach_log TEXT DEFAULT ''")
except Exception:
    pass
```

In `submitDispo` (frontend) add `coach_log: JSON.stringify(S.callLog)` to the
`/api/call_end` body. In `ep_call_end` (backend) store it:
- Add `coach_log` to the INSERT column list and values (`d.get("coach_log", "")`).

Nothing else in `ep_call_end` changes.

---

## 3. EXPORT RENDERING (backend, cellcoach.py — server-side so live + historical are identical)

Two endpoints, both GET, both return a downloadable text file:

```
GET /api/export/<call_id>/call      -> Clean Call Transcript  (.md, text/markdown)
GET /api/export/<call_id>/coaching  -> Coaching Review        (.md, text/markdown)
```

Each reads the call row from `cellcoach.db`, parses `coach_log` JSON, renders the
matching template (§5), and serves it with:
```
Content-Type: text/markdown; charset=utf-8
Content-Disposition: attachment; filename="<owner_or_phone>_<date>_<type>.md"
```

Backward-compat: if `coach_log` is empty (calls logged before this feature), the
coaching export falls back to the raw `transcript` field with a header note
"(coach log not captured for this call)". The clean export always works — it can be
rendered from `coach_log` if present, else from the raw `transcript`.

Rendering is pure string building in Python — no libraries. One function per
template; both share a `_render_header(call_row)` helper.

---

## 4. WHICH EVENTS GO IN WHICH FILE

| Event type            | Clean Call | Coaching Review |
|-----------------------|:----------:|:---------------:|
| REP line              |     ✅     |       ✅        |
| PROSPECT line (real)  |     ✅     |       ✅        |
| PROSPECT line (screening-flagged) | ✅ *(marked)* | ✅ *(marked)* |
| COACH response (gpt)  |     ❌     |       ✅        |
| COACH response (instant rebuttal) | ❌ | ✅        |
| COACH response (screening card)   | ❌ | ✅ *(marked)* |

Screening lines appear in BOTH files but tagged `[SCREENING]` so a reviewer sees the
call was intercepted and can discount that stretch. This is why screening lines are
captured, not dropped (ties to SPEC_CALL_SCREENING §1).

---

## 5. TEMPLATES (normative — render exactly this shape)

### 5.1 Clean Call Transcript  (`..._call.md`)

```markdown
# Call Transcript — Marcus Thompson
**Date:** 2026-07-16 14:31  ·  **Duration:** 6:12  ·  **Disposition:** follow-up
**Phone:** 512-555-1234  ·  **Address:** 1234 Main St 78704  ·  **Case:** CE-2026-001234
**Play:** STR  ·  **Coach persona:** G.U.T.S. — Claude Diamond

---

[00:04] REP: Hi, is this Marcus? This is Sean with the Risk & Compliance Bureau.
[00:09] PROSPECT: Yeah, who is this again?
[00:14] REP: Sean — we're an independent agency that tracks the city's code portal...
[00:22] PROSPECT: [SCREENING] The person you are calling is not available. Please leave a message.
[00:31] PROSPECT: Okay yeah what's this about?
[00:38] REP: There's an active short-term-rental case on the Main Street property...
...

---
*Cell Coach · clean call transcript · rep + prospect only*
```

Rules:
- Header from call metadata. Duration = mm:ss.
- Body: only `rep` and `prospect` events, in `seq` order, each as
  `[mm:ss] SPEAKER: text`.
- Screening-flagged prospect lines get a `[SCREENING]` inline tag before the text.
- No coach lines anywhere in this file.

### 5.2 Coaching Review Transcript  (`..._coaching.md`)

```markdown
# Coaching Review — Marcus Thompson
**Date:** 2026-07-16 14:31  ·  **Duration:** 6:12  ·  **Disposition:** follow-up
**Play:** STR  ·  **Coach persona:** G.U.T.S. — Claude Diamond
**Coach fires:** 9  (gpt: 6 · instant: 2 · screening: 1)
**Final checklist:** intro ✅ · qualified ✅ · play ✅ · committed ❌

> How to read this: each PROSPECT turn is followed by the COACH's response to it,
> then the REP's actual next line. Compare what the coach called to what the rep ran,
> and watch how the prospect reacts on the following turn.

---

[00:09] PROSPECT: Yeah, who is this again?
        └─ COACH (gpt · rapport): "Sean, with the Risk & Compliance Bureau —
           independent, not the city. Quick one about your Main Street place, got a
           minute?"
           objection: — · checklist: intro▫ qualified▫ play▫ committed▫
[00:14] REP: Sean — we're an independent agency that tracks the city's code portal...

[00:22] PROSPECT: [SCREENING] The person you are calling is not available...
        └─ COACH (screening): "Sounds automated — state your name and company
           plainly, then wait for a live pickup before running your opener."
[00:31] PROSPECT: Okay yeah what's this about?
        └─ COACH (gpt · discovery): "There's an active STR case on the property —
           were you aware of it?"
           objection: — · checklist: intro✅ qualified▫ play▫ committed▫
[00:38] REP: There's an active short-term-rental case on the Main Street property...

[01:12] PROSPECT: How much is this gonna cost me?
        └─ COACH (instant · Price pushback): "Quick question — is it the fee, or
           you're not sure the case is real? Because next to what it costs if it
           keeps running, the fee's tiny..."
           alt: "Totally your call — pull the case up yourself, it's public record."
[01:19] REP: So it's a flat fee, one time...
...

---
## Machine-readable event log
```json
[
  {"seq":1,"t":"00:04","ts":"2026-07-16T14:31:04Z","type":"rep","text":"Hi, is this Marcus?..."},
  {"seq":2,"t":"00:09","ts":"...","type":"prospect","text":"Yeah, who is this again?","screening":false},
  {"seq":3,"t":"00:10","ts":"...","type":"coach","trigger_seq":2,"source":"gpt","say_next":"Sean, with...","objection":null,"coach_type":"rapport","checklist":{"intro":false,"qualified":false,"play_selected":false,"committed":false},"temperature":"neutral","prospect_intel":{...}},
  ...
]
```
```

Rules:
- Header adds coach stats: total fires, split by source, and final checklist state
  (from the last coach event that carried a checklist).
- Body: walk `S.callLog` in `seq` order. Render `prospect` and `rep` lines as
  `[mm:ss] SPEAKER: text`. Render each `coach` event indented under the line that
  triggered it as a `└─ COACH (source · tag): "say_next"` block, with a compact
  metadata line beneath (objection, checklist snapshot as ▫/✅, alt if present).
- Screening lines and screening coach cards tagged `[SCREENING]` / `(screening)`.
- **Appended fenced ```json block = the entire raw `S.callLog`.** This is the
  AI-ingestion half: a model handed this file gets the exact structured data
  (timestamps, triggers, checklist deltas, intel, temperature) without having to
  parse the prose. Humans read the top; AIs read the bottom; both are the same data.

---

## 6. DOWNLOAD UI (frontend)

Two places to expose the downloads:

**A. Immediately after a call.** On the setup view after a disposition, briefly show
a small strip (or in the Past Calls modal) with two links for the just-finished call.
Simplest: rely on Past Calls (B) — no separate post-call UI needed.

**B. Past Calls modal.** For each call row, add two small links:
`⬇ Call`  and  `⬇ Coaching`, pointing at the two export endpoints:
```
/api/export/<id>/call        /api/export/<id>/coaching
```
Browser downloads the .md directly (Content-Disposition handles it). Historical calls
without a coach log still offer `⬇ Call`; the coaching link shows the fallback note.

---

## 7. VERIFICATION CHECKLIST
1. Run a mock call (type into the sockets via console): confirm `S.callLog` grows
   with correctly typed/ordered events — rep, prospect, coach — each with `seq`,
   `t`, `ts`.
2. Confirm each `coach` event's `trigger_seq` points at the correct preceding
   prospect line.
3. Disposition the call; confirm `coach_log` JSON is stored in `cellcoach.db`
   (`SELECT length(coach_log) FROM calls ORDER BY id DESC LIMIT 1` > 2).
4. Hit `/api/export/<id>/call` — verify: header correct, only rep/prospect lines,
   NO coach lines, screening lines tagged, valid Markdown.
5. Hit `/api/export/<id>/coaching` — verify: coach blocks indented under the right
   trigger line, rep's next line follows, stats header correct, and the appended
   ```json block parses as valid JSON equal to the stored `coach_log`.
6. Old call (coach_log empty): coaching export renders the fallback note and the raw
   transcript without crashing.
7. `python -m py_compile cellcoach.py` passes.
8. Confirm live coaching behavior is unchanged — this layer only observes.

## OUT OF SCOPE
- No automatic deviation scoring ("rep didn't follow coach") — the paired layout
  makes deviations visible to a human/AI reviewer; computing a match score is a
  later, separate feature.
- No third "prospect + coach only" export — the coaching review already contains
  that data; it can be filtered from `S.callLog` later if a real need appears.
- No changes to persona content, sources, screening logic, or the cockpit view.
```
