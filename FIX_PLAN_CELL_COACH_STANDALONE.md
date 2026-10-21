# Cell Coach — Standalone Build Plan
**For:** a cheaper executing model · **Owner:** Sean · **Written:** 2026-07-15
**File under work:** `C:\Users\Admin\data_center\cell_coach\cellcoach.py` (single file, ~304 lines, stdlib-only HTTP server on port 5099)

---

## 0. Design intent — read first

Cell Coach is a **fully standalone** app: Sean dials on his cell via Microsoft **Phone Link**, the PC plays the call audio, this app listens (screen-share with system audio + mic), transcribes via AssemblyAI streaming, and coaches live via GPT-4o. It must work with **zero dependencies on `lead_machine/`, the shared databases, or anything else in `data_center\`** — the folder should be copy-pasteable anywhere on any machine and still run.

The current code violates this: it `sys.path`-imports `../lead_machine/app.py` as the primary brain (`CC311`) and treats standalone as a degraded fallback. **Reverse that: standalone is the ONLY mode.**

### Executor rules
- Touch ONLY files inside `cell_coach\`. Never import from, read from, or write to `lead_machine\`, `..\data\` (except the one config fallback in §1), or any other sibling folder.
- Keep it ONE Python file (`cellcoach.py`) + `START.bat` + local config + local DB. Pure stdlib (json, sqlite3, http.server, urllib, threading) — no pip installs.
- Atomic writes for any edit: write temp file, `py_compile`, `os.replace`. Confirm the file ends clean after writing.
- Before the first edit, copy the current `cellcoach.py` to `_backup_pre_standalone\cellcoach.py`.
- No secrets in code or in this repo's docs. Keys live only in config JSON.
- After each phase: `python -m py_compile cellcoach.py`, then launch and confirm the page loads.

---

## 1. Phase 1 — Decouple (delete the 311cmd bridge)

1. Delete the `CC311` import block (the `for cand in [...lead_machine...]` loop) and every `if CC311:` branch in `ep_aai / ep_queue / ep_prep / ep_analyze`.
2. Delete the `/api/queue` and `/api/prep/<id>` endpoints and ALL queue UI in the HTML: the search box, `#qlist`, `loadQueue/renderQ/filterQ/pick`, the `#dataline` "connecting to your lead data…" line, and the "Not in your list?" link. Manual mode becomes the only mode and is shown by default (remove `display:none` from `#manualCard`, remove `manualMode()` gating in `start()`).
3. Config resolution (keep the existing `_local_cfg()` order): `cell_coach\cc_config.json` **first**, then `..\data\cc_config.json` as a courtesy fallback (tolerate absence — it must not crash if the folder is moved). Needs only two keys: `openai_key`, `assemblyai_key`. If `cell_coach\cc_config.json` doesn't exist, create a template on first run: `{"openai_key": "", "assemblyai_key": ""}` and surface a clear banner in the UI when keys are missing.
4. Update the header/subtitle and `README.md`: no more "data-connected", no more "reads 311cmd next door", no OneDrive note. New one-liner: "Standalone live call coach for Phone Link calls. Fill in the call context, dial on your cell, press Start."
5. Delete `_verify_cc.py` (it only tested the 311cmd link).

**Acceptance:** rename `lead_machine` temporarily (or run from a copied folder elsewhere) → app starts, page loads, no errors, no references to queue/lead data anywhere.

## 2. Phase 2 — Port the full coaching brain (schema + prompt)

The local fallback currently uses a stripped prompt and the OLD JSON schema (`rebuttal`). Port the good brain from `lead_machine/app.py` **by copying text into cellcoach.py** (copy, never import):

1. **System prompt:** copy `COACH_SYS` (app.py ~line 448) — the full Cardone-method + Gong/BYAF/EPPM prompt with the `say_next` schema — replacing the current `SYS`. Keep the REP:/PROSPECT: labeling language (Phase 4 delivers labeled transcript).
   - Adjust identity line: keep "Sean with Risk & Compliance Bureau" as a config-overridable string `rep_identity` in cc_config.json with that as default.
2. **Stakes:** copy the full `COACH_STAKES` map (STR, LAND_USE, LAND_USE_COMMERCIAL, STRUCTURE, ABATEMENT, PERMIT, 311, FIRE) replacing the current 4-entry `STAKES`. Add `GENERAL` (keep existing text).
3. **Context:** the analyze call builds context from the **manual form fields** (see Phase 3 UI): play, owner, address, case #, fee, notes. Include `latest` (last PROSPECT turn) in the user message exactly as app.py does.
4. **Render:** update the UI `render()` to the new schema — always show `say_next` in a big prominent "SAY THIS" panel (not only when `objection` is present), show `coach_type` as a small tag, keep checklist / next_action / temperature / summary as-is. The current `#rebuttal` panel becomes the say_next panel; objection label shows above it when present.

**Acceptance:** with a fabricated transcript POSTed to `/api/analyze`, response contains `say_next` and the panel renders it.

## 3. Phase 3 — Richer manual context + instant objection tier

1. **Expand the context card** (this replaces the lead picker): fields for `Play` (dropdown, all 8 plays + General), `Owner name`, `Address`, `Case #`, `Your fee` (e.g. "$500 flat"), `Notes`. All optional except Play. Persist the last-used values in `localStorage` so repeat sessions don't retype.
2. **Instant objection tier (client-side, milliseconds):** copy the `COACH_OBJECTIONS` list (app.py ~line 577, 8 global objections: not interested / distrust / price / already handled / stalling / busy / wants to sell / not the owner) and `COACH_OBJECTIONS_PLAY` (STR, LAND_USE_COMMERCIAL, PERMIT) into a JS constant in the HTML. Template placeholders `{case}` and `{insp}`: fill `{case}` from the Case # field (fallback "the case"), replace `{insp}` references with "the inspector".
3. On each final PROSPECT turn, run the regex list (play-specific first, then global) against that turn. On match, show the canned rebuttal in the SAY THIS panel **immediately**, tagged "⚡ instant", then let the GPT-4o response overwrite it when it lands.

**Acceptance:** typing/receiving a turn containing "not interested" flashes the instant rebuttal before the API round-trip completes.

## 4. Phase 4 — Two-socket labeled transcript (biggest quality fix)

Today mic + system audio mix into ONE AssemblyAI socket → unlabeled transcript → the coach can misread Sean's own pitch as an objection. Fix by separating channels (the pattern exists in app.py's cockpit JS ~line 1885 — port the *approach*, adapted to this app's audio sources):

1. Request **two** AAI tokens from `/api/aai_token` (call it twice; each token is single-use).
2. Open two WebSockets: `WS_REP` and `WS_PROSPECT`.
3. Audio routing: **mic stream → WS_REP** worklet; **display/system-audio stream → WS_PROSPECT** worklet. Two AudioWorklet nodes (same processor code, instantiate twice), one AudioContext is fine.
4. On end-of-turn from either socket, append to a single ordered transcript as `REP: <text>` / `PROSPECT: <text>` (timestamp-ordered by arrival). Keep the live pane showing the labeled last ~600 chars.
5. `analyze` payload: full labeled transcript + `latest` = the most recent PROSPECT turn. Only schedule an analyze on **PROSPECT** turns (rep turns update the transcript but don't burn a GPT call) — this also cuts cost roughly in half.
6. **Echo caveat** stays in the hint box: headset required, otherwise the mic picks up the prospect's voice and both sockets hear it.
7. If system audio is missing (user didn't tick "share system audio"), keep the existing warning and fall back to single-socket REP-only rather than failing.

**Acceptance:** live pane shows interleaved `REP:` / `PROSPECT:` lines; analyze fires only after prospect turns; payload includes `latest`.

## 5. Phase 5 — Local call log + disposition + next-call prep

Cell Coach currently forgets every call. Give it its own memory — **local to the folder**, keyed by phone number (no lead IDs exist here):

1. New SQLite DB `cell_coach\cellcoach.db`, table:
   ```sql
   CREATE TABLE IF NOT EXISTS calls(
     id INTEGER PRIMARY KEY AUTOINCREMENT,
     phone TEXT, play TEXT, owner TEXT, address TEXT, case_id TEXT,
     started_at TEXT, ended_at TEXT, duration INTEGER DEFAULT 0,
     disposition TEXT, follow_up_date TEXT DEFAULT '',
     transcript TEXT DEFAULT '', checklist TEXT DEFAULT '{}',
     summary TEXT DEFAULT '', next_call_prep TEXT DEFAULT '');
   ```
2. **Disposition on Stop (mandatory):** when Stop is pressed (and a transcript exists), show 5 buttons — Paid / Follow-up / Not interested / No answer / Bad number — with number-key shortcuts 1–5. Follow-up prompts for a date (default +2 days). POST everything to a new `/api/call_end` endpoint which inserts the row.
3. **Post-call AI (background thread):** port the `_post_call_ai` pattern from app.py (~line 746): GPT-4o writes `summary` + `next_call_prep` (`last_time` bullets, `open_objections`, `recommended_opener`) into the row. Copy the prompt text; swap lead fields for the manual-context fields.
4. **Prep recall:** when a number is entered in the dial field (on blur or Dial click), `GET /api/prep_by_phone/<digits>` — if prior calls exist for that normalized number, show a brief panel: N prior calls, last disposition, summary, recommended opener, open objections. This restores the "prep from last call" loop with zero external data.
5. **History view (minimal):** a "📜 Past calls" link that lists the last 20 calls (date, phone, owner, disposition, one-line summary) from the local DB. Read-only, keep it simple.

**Acceptance:** end a call with a fake transcript → row lands in cellcoach.db → summary/prep populate within ~10s → re-entering the same number shows the prep panel.

## 6. Phase 6 — Verify (full pass)

1. `python -m py_compile cellcoach.py` clean; file ends properly (atomic-write check).
2. Cold start with `lead_machine` inaccessible (rename or run a copy of `cell_coach\` from another location, e.g. `%TEMP%`): app boots, page loads, missing-key banner behaves, template config is created.
3. Mock round-trips without real calls: POST `/api/analyze` with a labeled fake transcript (expects `say_next`); POST `/api/call_end` with a fake session (expect DB row + background summary); GET `/api/prep_by_phone` for that number.
4. Manual live test checklist for Sean (document at the top of README): Phone Link connected → dial → Start Coaching → entire screen + system audio → confirm both labels appear → confirm instant rebuttal on "not interested" → Stop → disposition → prep recall on redial.

---

## 7. Sequencing and effort

| Phase | What | Est. |
|---|---|---|
| 1 | Decouple from 311cmd | 1–2 hrs |
| 2 | Port coaching brain + say_next render | 1–2 hrs |
| 3 | Manual context + instant objections | 2 hrs |
| 4 | Two-socket labeled transcript | 3–4 hrs (fiddliest — audio plumbing) |
| 5 | Local call log + disposition + prep | 3 hrs |
| 6 | Verification | 1 hr |

Order is dependency order: 1 → 2 → 3 → 4 → 5 → 6. Each phase leaves the app runnable. Phases 2+3 give the biggest immediate coaching-quality lift; Phase 4 is what makes GPT coaching *accurate*; Phase 5 is what makes the tool compound across calls.

**Cost note:** analyze-on-prospect-turns-only (Phase 4.5) plus the instant tier (Phase 3) keeps GPT spend at roughly 1–2¢/call. AssemblyAI two-socket doubles transcription minutes: ~10–20¢ per 10-min call. Total ≈ 15–25¢/call.

**Out of scope (do not build):** any reconnection to lead_machine data, Twilio, call recording/audio storage, multi-rep support, cloud deployment.
