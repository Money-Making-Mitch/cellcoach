# CELL COACH — Setup Screen Redesign: "Dialer Cockpit"
## Implementation spec for executing model — follow exactly, do not improvise design

### CONTEXT
Cell Coach is a standalone live AI cold-call coach at `C:\Users\Admin\data_center\cell_coach\`.
Two files matter: `cellcoach.py` (pure-stdlib Python HTTP server, port 5099) and
`cellcoach_ui.html` (single-file frontend, served at `/`).

The app has two views inside one HTML file:
- **Setup view** (`#setupView`) — THIS IS WHAT YOU ARE REPLACING. Currently a narrow
  centered column (max-width 520px) that requires page scrolling. Unacceptable.
- **Live view** (`#liveView`) — the in-call coaching screen. **DO NOT TOUCH IT.**
  Do not touch any CSS class or JS function used only by the live view.

### HARD RULES
1. Touch ONLY `cellcoach.py` and `cellcoach_ui.html` in `cell_coach/`. Nothing else.
2. `command_center.db` is opened **READ-ONLY** (`file:...?mode=ro` URI). Never write
   to it, never create tables in it, never ALTER it. All call logging stays in
   `cellcoach.db` exactly as it works today.
3. No pip installs. Python stdlib only. No new JS libraries. No build step.
4. Keep every existing endpoint, function, and the entire live-view + Twilio +
   Phone Link + AssemblyAI logic working unchanged. This is a setup-view redesign
   plus one new backend endpoint — not a rewrite.
5. **Zero page scroll on the setup view.** `body` stays `overflow:hidden`. Only the
   queue list (`.queue-list`) scrolls internally. Design target: 1280×720 at 100%
   zoom with every control visible, including the Start button. Test mentally at
   1366×768 and 1920×1080 too.
6. Keys stay on this machine; nothing is uploaded.

---

## PART 1 — BACKEND (`cellcoach.py`)

### 1.1 New helper: command center DB path
Add near `_local_cfg()`:

```python
def _cc_leads_db():
    """Path to the command center leads DB. Config can override."""
    c = _local_cfg()
    p = c.get("command_center_db") or os.path.join(os.path.dirname(BASE), "data", "command_center.db")
    return p if os.path.exists(p) else None
```

### 1.2 New endpoint: `ep_queue()`
The `leads` table in command_center.db has (relevant cols):
`id, play, case_id, address, zip, owner, phone, score, stage, priority,
prop_value, portfolio_n, absentee, distress, description, opened_date, is_business`.
Stages present: NEW (2102), VAULT (1183), DEAD (848). 924 rows have non-empty phone.
Play values (ABATEMENT, 311, STRUCTURE, FIRE, LAND_USE, STR, PERMIT) match
`COACH_STAKES` keys directly — no mapping needed.

```python
def ep_queue(qs):
    """Read-only lead queue from the command center DB, priority order."""
    p = _cc_leads_db()
    if not p:
        return {"available": False, "leads": []}
    try:
        con = sqlite3.connect("file:" + p.replace("\\", "/") + "?mode=ro", uri=True, timeout=3)
        con.row_factory = sqlite3.Row
        stage = (qs.get("stage", ["NEW"])[0] or "NEW").upper()
        rows = con.execute(
            "SELECT id, play, case_id, address, zip, owner, phone, score, priority, "
            "prop_value, portfolio_n, distress, description, opened_date, is_business "
            "FROM leads WHERE phone IS NOT NULL AND phone != '' AND stage = ? "
            "ORDER BY priority DESC LIMIT 400", (stage,)).fetchall()
        con.close()
    except Exception as e:
        return {"available": False, "leads": [], "error": str(e)[:200]}
    # Cross-reference local call history: phone -> (count, last disposition)
    hist = {}
    try:
        lc = db()
        for r in lc.execute("SELECT phone, disposition FROM calls WHERE phone != '' ORDER BY id ASC"):
            k = _normalize_phone(r["phone"])
            if k:
                c0 = hist.get(k, (0, ""))
                hist[k] = (c0[0] + 1, r["disposition"] or "")
        lc.close()
    except Exception:
        pass
    leads = []
    for r in rows:
        k = _normalize_phone(r["phone"] or "")
        cnt, last = hist.get(k, (0, ""))
        leads.append({
            "lead_id": r["id"], "play": r["play"] or "GENERAL",
            "case_id": r["case_id"] or "", "address": r["address"] or "",
            "zip": r["zip"] or "", "owner": r["owner"] or "",
            "phone": r["phone"], "score": r["score"] or "",
            "priority": r["priority"] or 0, "prop_value": r["prop_value"],
            "portfolio_n": r["portfolio_n"], "distress": r["distress"] or "",
            "description": r["description"] or "", "opened": r["opened_date"] or "",
            "is_business": bool(r["is_business"]),
            "call_count": cnt, "last_disposition": last,
        })
    return {"available": True, "leads": leads}
```

### 1.3 Route
In `do_GET`, add (before the 404 line):

```python
if p == "/api/queue":
    return self._s(ep_queue(parse_qs(urlparse(self.path).query)))
```

`parse_qs` and `urlparse` are already imported.

### 1.4 Config template
In `_ensure_config()`, add `"command_center_db": ""` to the template dict (empty =
use the default `../data/command_center.db`). Do NOT modify the user's existing
`cc_config.json` — the template only writes when the file doesn't exist.

---

## PART 2 — FRONTEND (`cellcoach_ui.html`)

### 2.0 What gets deleted vs. kept
DELETE the entire current setup-view markup (`#setupView` contents) and its
setup-only CSS: `.setup`, `.method-toggle`, `.method-btn`, `.persona-row`,
`.prep-recall`, `.hint`, `.history-panel`, `.hist-row`, `.footer-link`, `.btn-go`,
`.btn-dial`, `.banner`.
KEEP unchanged: all live-view CSS/markup/JS, `.card`, `label`, `select/input/textarea`
base styles, topbar styles, and ALL existing JS functions — you will modify only the
ones named below. All element IDs read by live-call JS (`play`, `owner`, `address`,
`caseId`, `fee`, `notes`, `dialNum`) MUST still exist in the new markup — the live
call flow reads context from them via `$('play').value` etc. Keep them as real
inputs (visible where specified, `type="hidden"` is NOT acceptable for the editable
ones listed in 2.4).

### 2.1 Design language (new, must not resemble the old look)
Old look: dark slate cards floating on a #111827 background, centered column.
New look: full-bleed **panel-grid cockpit** — flat surfaces separated by 1px hairlines,
no floating cards, no rounded card containers on the main surfaces, denser and darker.

New CSS variables (replace `:root` block values — live view uses the same var names,
so changing values restyles both views consistently; that is fine and desired):

```css
:root{
  --bg:#0a0e14;        /* near-black blue */
  --panel:#0f141c;     /* main surfaces */
  --panel2:#161d28;    /* inputs, hover rows */
  --line:#232c3a;      /* hairlines */
  --txt:#e6edf3; --dim:#7d8896;
  --acc:#4cc2ff;       /* electric blue accent (replaces cyan) */
  --good:#3fb950; --bad:#f85149; --gold:#d29922;
  --blue:#316dca; --purple:#a371f7; --green:#2ea043; --red:#da3633; --yellow:#bb8009;
}
```

Font stays system-ui. Base font-size 13px on the setup view (denser).

### 2.2 Layout skeleton

```
┌──────────────────────────────────────────────────────────────────────┐
│ TOPBAR 48px: 🎧 CELL COACH · [PhoneLink|Twilio seg] · persona ▾ ·    │
│              [Past calls] [+ Persona]                    ● ready     │
├───────────────┬──────────────────────────────────────────────────────┤
│ QUEUE 380px   │ CALL SETUP (flex:1)                                  │
│ ┌───────────┐ │  ┌ selected lead banner ────────────────────────┐    │
│ │⌨ Manual   │ │  │ OWNER NAME (22px bold)     [PLAY badge][score]│    │
│ │  dial     │ │  │ ☎ 512-555-1234 (20px mono)                   │    │
│ ├───────────┤ │  │ 1234 Main St 78704 · Case CE-2026-1234        │    │
│ │ filter row│ │  │ desc · opened 2026-06-29 · $483k · 2 props    │    │
│ ├───────────┤ │  └───────────────────────────────────────────────┘   │
│ │ lead row  │ │  ┌ prior-call recall strip (only if history) ────┐   │
│ │ lead row  │ │  └───────────────────────────────────────────────┘   │
│ │ lead row  │ │  editable grid: play ▾ · owner · address · case      │
│ │  (scrolls │ │                 fee · notes                          │
│ │   inside) │ │                                                      │
│ │    ...    │ │  ┌──────────────────────────────────────────────┐    │
│ │           │ │  │        ▶  START COACHING   (64px tall)       │    │
│ └───────────┘ │  └──────────────────────────────────────────────┘    │
└───────────────┴──────────────────────────────────────────────────────┘
```

Structure CSS:

```css
#setupView{display:flex;flex-direction:column;height:100vh;overflow:hidden}
.cockpit{flex:1;display:grid;grid-template-columns:380px 1fr;overflow:hidden}
.queue-col{border-right:1px solid var(--line);display:flex;flex-direction:column;overflow:hidden;background:var(--panel)}
.queue-list{flex:1;overflow-y:auto}   /* the ONLY scrolling element */
.setup-col{display:flex;flex-direction:column;overflow:hidden;padding:16px 20px;gap:12px}
.setup-col .spacer{flex:1}            /* pushes Start button to bottom */
```

### 2.3 Topbar (48px, flat, hairline bottom border)
Left to right:
- `🎧 CELL COACH` — 14px, bold, letter-spacing 1px.
- Segmented method toggle: two small buttons (Phone Link / Twilio), 28px tall,
  joined, active = `--acc` background with dark text. Same behavior as current
  `setMethod()`; Twilio stays disabled until `twilio_ready`. Keep ids
  `methodPhoneLink` / `methodTwilio` so existing JS works with minimal edits.
- Persona: a native `<select id="personaSelect">` (28px tall, 200px wide) replacing
  the radio list entirely. `loadPersonas()` populates it; `onchange` calls
  `selectPersona(this.value)`. Rewrite `renderPersonaList()` to fill the select.
- Two ghost buttons: `Past calls` → opens history modal; `+ Persona` → opens
  persona modal. Ghost = transparent bg, 1px `--line` border, `--dim` text.
- Right edge: status pill (existing `#statusPill`) + keys-missing warning collapses
  into the pill (title attribute has the detail); delete the big red banner.

### 2.4 Right panel — Call Setup
Top-to-bottom, all fixed height, `.spacer` absorbs leftover space so the Start
button hugs the bottom:

1. **Lead banner** (`#leadBanner`) — flat panel, 1px hairline, 12px padding:
   - Row 1: owner name 22px/700. Right side: play badge (colored pill — reuse a new
     `.play-badge` class; color by play: FIRE/WATER/FORECLOSURE red, STR gold,
     others blue) + score chip (HIGH green / MEDIUM gold / LOW dim).
   - Row 2: phone 20px, `Courier New` mono, `--acc` color.
   - Row 3 (12px, `--dim`): address · zip · case_id.
   - Row 4 (11px, `--dim`): description · opened date · `$` prop_value (format
     `$484k`) · `portfolio_n` props · `↻ called Nx, last: <dispo>` if call_count>0.
   - Manual mode: banner shows a phone `<input id="dialNum">` (large, mono) instead
     of a static number, title "Manual dial", and rows 3-4 hidden.
   IMPORTANT: in queue mode `dialNum` still exists — render it as the visible
   phone element itself (an input styled borderless/transparent that LOOKS like
   text but is editable). One element serves both modes. On lead select, set its
   value to the lead's phone.
2. **Prior-call recall strip** (`#prepRecall` reworked): single flat row, gold left
   border 2px, max 2 lines with `overflow:hidden`. Filled by existing `checkPrep()`
   — keep that function, restyle output to:
   `LAST CALL: <dispo> — <summary> · OPENER: <recommended_opener>`. Hidden if none.
3. **Editable context grid** — two rows, 6 columns total using CSS grid
   `grid-template-columns:repeat(6,1fr);gap:8px`:
   Row A: Play (`<select id="play">`, same options as now, spans 2), Owner
   (`#owner`, spans 2), Case # (`#caseId`, spans 2).
   Row B: Address (`#address`, spans 2), Fee (`#fee`, spans 1), Notes (`#notes`,
   spans 3). Inputs 34px tall, 12px font, labels 9px uppercase above each.
4. `.spacer`
5. **Start button** (`#btnStart`): full width, 64px, 18px/800 text
   `▶ START COACHING`, gradient `linear-gradient(135deg,#1158c7,#4cc2ff)`, calls
   `start()`. Below it one 11px `--dim` centered line that switches with method:
   Phone Link → "Dial on your cell first · Chrome will ask to share screen + system audio · use a headset"
   Twilio → "Call places from this browser when coaching starts · use a headset".
   In Phone Link mode ALSO show a small `📞 Dial on phone` ghost button inline left
   of the Start button (60/40 split row) that calls the existing `telDial()`.

### 2.5 Left panel — Queue
1. **Pinned manual row** (top, always first, NOT part of scroll):
   `⌨ Manual dial — type a number` — selecting it enters manual mode (clears
   banner to input state, clears context fields, keeps whatever user types).
   Highlighted with `--acc` left border 2px when active.
2. **Filter row** (36px, flat, hairline bottom): three controls inline —
   search `<input id="qSearch" placeholder="Search owner / address / phone">`
   (flex:1), play `<select id="qPlay">` (All plays + each play), score
   `<select id="qScore">` (All / HIGH / MEDIUM / LOW). All 26px tall, 11px font.
   Filtering is client-side over the fetched array; re-render on `input`/`change`.
3. **Header line** (24px, 10px uppercase `--dim`): `CALL QUEUE · <n> leads` — n
   updates with filters. If `available:false`: show
   `Command center DB not found — manual dial only` and auto-enter manual mode.
4. **Lead rows** (`.q-row`, 54px, hairline separators, cursor pointer, hover
   `--panel2`, selected = `--acc` 2px left border + `--panel2` bg):
   - Line 1: owner (13px/600, truncate) — right-aligned play badge (9px) + score
     dot (6px circle: green/gold/dim).
   - Line 2 (11px `--dim`): phone (mono) · address (truncate).
   - If `call_count>0`: tiny `↻N` marker after phone, `--gold`.
   Click → `selectLead(i)`.

### 2.6 New/changed JS

```
let Q = {leads:[], filtered:[], selected:-1, manual:true};

loadQueue()      – fetch /api/queue; store; applyFilters(); if leads exist select
                   index 0 (queue mode) else manual mode.
applyFilters()   – search across owner+address+phone (case-insensitive), play,
                   score; renderQueue().
renderQueue()    – rebuild .queue-list rows + count. Escape all strings with esc().
selectLead(i)    – Q.selected=i; Q.manual=false; fill: dialNum=phone, play (if the
                   lead's play exists as an option, else GENERAL), owner, address,
                   caseId; owner/address/caseId are OVERWRITTEN on each selection
                   (fee/notes are NOT — they persist as user prefs); render banner;
                   call checkPrep(); highlight row.
selectManual()   – Q.manual=true; Q.selected=-1; clear dialNum/owner/address/caseId;
                   play=GENERAL; banner→input mode; hide recall strip.
renderBanner()   – paint #leadBanner from selected lead or manual state.
```

Changes to existing JS:
- `renderPersonaList()` → fills `#personaSelect` options; delete per-row delete
  links (persona deletion moves into the persona modal: a small list with delete
  buttons next to the paste form).
- `saveCtx()/loadCtx()` — keep, but on startup call order is: `loadCtx()` →
  `loadPersonas()` → `loadQueue()`. `loadQueue()`'s auto-select of lead 0 may
  overwrite restored ctx owner/address — acceptable; fee/notes survive.
- After `submitDispo()` → `resetToSetup()`: append `advanceQueue()` — if in queue
  mode, select the next lead down (wrap to none at end, show manual). This gives
  the dial→coach→dispo→next-lead loop.
- `start()` — unchanged except: guard `if(!$('dialNum').value.trim() && callMethod==='twilio')`
  already effectively handled; keep as is.
- History: `toggleHistory()` now opens a modal (`#histModal`) instead of an inline
  panel. Same fetch/rendering.

### 2.7 Modals (shared minimal styles)

```css
.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.6);display:none;
  align-items:center;justify-content:center;z-index:50}
.modal-bg.show{display:flex}
.modal{background:var(--panel);border:1px solid var(--line);border-radius:8px;
  width:560px;max-height:80vh;overflow-y:auto;padding:20px}
```

Two modals: `#personaModal` (name input + textarea + save/cancel + list of existing
personas with delete buttons for non-built-ins — reuse `savePersona()` /
`deletePersona()`) and `#histModal` (existing history list rendering). Close on
backdrop click and an `×` button. Modal internal scroll is permitted (it's an
overlay, not the page).

### 2.8 Responsive floor
At `max-width:1100px`: queue column narrows to 300px. No mobile layout needed —
this is a desktop cockpit. Do not add a stacked/mobile variant for the setup view.
Leave the existing live-view `@media(max-width:768px)` block alone.

---

## PART 3 — VERIFICATION CHECKLIST (do all, in order)
1. `python -m py_compile cellcoach.py` passes. NOTE: this repo sits on a mount
   where the sandbox can serve stale file copies — if compile output looks
   inconsistent with your edit, re-read the file with the Read tool (Windows path)
   and trust THAT, not bash cat.
2. Start server, `GET /api/queue` returns `{"available": true, "leads": [...]}` with
   ~400 leads, sorted priority desc, each with owner/phone/play/score/call_count.
3. Confirm command_center.db was NOT modified: record its byte size + mtime before
   testing and after — must be identical.
4. `GET /` serves the new UI. In the served HTML verify: ids `play, owner, address,
   caseId, fee, notes, dialNum, personaSelect, methodPhoneLink, methodTwilio,
   btnStart, leadBanner, qSearch` all present exactly once.
5. JS sanity: `node --check` is not available for inline HTML — instead extract the
   `<script>` body to a temp file and run `node --check` on it if node exists in
   sandbox, else careful manual brace/paren review of every function you touched.
6. Walk the flows mentally against the code (write the trace down):
   a) load → queue fetch → lead 0 selected → fields filled → Start → live view.
   b) manual mode → type number → Twilio start.
   c) dispo → back to setup → next lead auto-selected.
   d) queue DB missing (rename check via `_cc_leads_db()` returning None) →
      manual-only fallback, no JS errors.
7. No element on the setup view can force `body` scroll: every column uses
   overflow:hidden except `.queue-list`.
8. Live view untouched: diff your final HTML against the original and confirm zero
   changes inside `#liveView` markup and live-view-only functions.

## OUT OF SCOPE — DO NOT DO
- No writes/stage updates back to command_center.db (future feature, not now).
- No auto-dialing on lead select. Dialing starts only via Start/Dial buttons.
- No changes to coaching prompts, personas content, OUTPUT_CONTRACT, Twilio, or
  AssemblyAI logic.
- No new dependencies, no frameworks, no separate CSS/JS files.
