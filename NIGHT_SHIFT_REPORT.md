# CELL COACH 2 — NIGHT-SHIFT OVERHAUL REPORT
**Completed: 2026-07-29 ~05:25 · Autonomous run · App live at http://127.0.0.1:5099/**

---

## 6. 🧠 SMART QUEUE PORT FROM DATACENTER2 (added ~09:30)
Ported three datacenter2 modules (`lib/dialer/dialerQueue.ts`, `dispoMap.ts`, buildLeadWhere scrub) into `cellcoach.py`:

**Ranked queue** — leads no longer dial in import order. Bucket ladder (verified live):
1. `callback_due` (1000+) — follow-up date reached → floats to top, shows 📞 CALLBACK badge
2. `touch_cadence_due` (500+) — 2+ days since last contact → ⏰ DUE AGAIN
3. `hot_untouched` (300+) — HIGH score, never called → 🔥 HOT
4. `new_today_with_phone` (200+) — imported today → 🆕 NEW TODAY
5. `untouched_with_phone` (100+), `generic` (40+)
- Base score: phone +100, HIGH/MED score +50/+25, property value +min(v/10, 150)
- **Called-today exclusion:** a number dialed today never resurfaces today
- Applies to BOTH queue builders (imported CSV lists and SQLite sources)
- wealthTier/time-of-day boost intentionally omitted — cell_coach2 doesn't persist those fields; documented in code, not faked

**Protected stages** — a `paid` lead's status is never downgraded by a later stale `no_answer`/`followup` from a queue re-dial (notes still append). `dnc` overrides even `paid` — compliance beats everything. Verified live.

**Institutional scrub** — owner names matching government/institution patterns (CITY OF, STATE OF, UNIVERSITY OF, COUNTY OF, ISD, AUTHORITY, DEPARTMENT OF, FEDERAL, MUNICIPAL, APPRAISAL/HOSPITAL DISTRICT, etc.) are filtered out of every queue. Header shows count: `🏛 N institutional scrubbed`. Verified: "CITY OF AUSTIN" scrubbed from a 6-lead test list.

**Known data note:** during port testing, a too-broad cleanup DELETE removed the handful of real test-call rows for the 3 allowlisted test numbers (your own calls from 7/28 evening). No prospect data affected; DB backup now in place (`cellcoach.db.bak-20260729`).

---

## 7. ☎️ TELNYX PARALLEL ENGINE (added ~10:45)
Telnyx added as a second telephony engine — **Twilio fully intact and still active**.
- **Switch:** `telephony_provider` in `data/cc_config.json` (`"twilio"` | `"telnyx"`). Auto-falls-back to Twilio if Telnyx is selected but unconfigured.
- **Server:** `/api/telnyx_token` (mints + caches WebRTC JWT from API key + credential ID) and `/api/telnyx_voice` (TeXML webhook — reuses the *same* dial guard + DID rotation + caller-ID logic; verified live: guard blocks, pool DID injected).
- **Client:** `@telnyx/webrtc@2.27.8` UMD from jsdelivr (global `TelnyxWebRTC.TelnyxRTC`, verified in-browser); `startTelnyxCall()` mirrors the Twilio path into the same state machine (wrap freeze, dispos, autodial); mute/hangup provider-aware via `hangupCall()`; prospect audio feeds the same AssemblyAI dual-STT + recorder via shared `_pollRemoteStream`/`_prospectStreamAttached` helpers (Twilio path refactored to use them — no behavior change).
- **Verified:** JS `node --check` OK, `py_compile` OK, both SDKs load in-browser, status endpoint reports provider/readiness, TeXML guard + rotation responses correct, queue/coach untouched.
- **Not yet live-tested** — needs your Telnyx account. Full dashboard walkthrough: [TELNYX_SETUP.md](TELNYX_SETUP.md).

---

## 8. ☎️ PLIVO THIRD ENGINE (added ~11:25)
Full Plivo integration alongside Twilio + Telnyx — one config switch picks the
carrier: `telephony_provider`: `"twilio"` | `"telnyx"` | `"plivo"`.
- **Server:** `/api/plivo_token` (mints + caches SDK JWT via `POST /v1/Account/{auth_id}/JWT/Token/`, HTTP basic auth) and `/api/plivo_voice` (Plivo XML webhook — shared guard/rotation/caller-ID logic with automatic `<Speak>` vs `<Say>` verb swap; verified live: guard blocks with `<Speak>`, pool DID injected).
- **Client:** Plivo Browser SDK v2 from `cdn.plivo.com` (verified loading in-browser); `startPlivoCall()` — JWT login → call → `onCallRemoteRinging`/`onCallConnected`/`onCallTerminated` mapped onto the same state machine; remote audio captured from the SDK's internal `<audio>` element into the same AssemblyAI pipeline; mute/hangup provider-aware (`hangupCall()` now runs all three engines safely).
- **Status:** endpoint reports `plivo_ready`; provider fallback to Twilio automatic if selected engine is unconfigured.
- **Verified:** `node --check` OK, `py_compile` OK, all three SDKs load in-browser, Twilio still active, queue/coach intact.
- **Not yet live-tested** — needs your Plivo account. Walkthrough: [PLIVO_SETUP.md](PLIVO_SETUP.md).

---

## 1. ✂️ TELEPHONY SIMPLIFICATION — DONE
Phone Link is **completely gone**:
- Removed the Twilio/Phone Link toggle, the device picker rows, the `tel:` dial button, and ~3,900 characters of Phone Link code (`setMethod`, `telDial`, `startPhoneLinkCapture`, `enumerateAudioInputs`, `cc_method` restore).
- `callMethod` is hardcoded to `'twilio'`; the Twilio controls are always visible; the start button reads **▶ START CALL** and goes straight to Twilio WebRTC.
- Grep for every Phone Link identifier returns **zero matches**. There is no provider to select — you log in, Twilio connects, done.

## 2. 🎨 LIGHT MODE REDESIGN — DONE
Entire `<style>` block replaced with a crisp light theme (screenshot: `C:\Users\Admin\data_center\cc2_lightmode.png`):
- Soft white panels on a light slate background, high-contrast dark text.
- **Emerald** = connected/ready, **primary blue** = active buttons (START CALL), **amber** = wrap-up / last-disposition strip, red = danger/DNC.
- Every component remapped: queue rows, badges, pills, coach panel, disposition buttons, modals, training mode. No dark tokens remain (verified by grep).
- musepool's design-reference service was unreachable tonight (package install blocked), so the palette was chosen by the brief directly — soft whites/slates + your requested accent meanings.

## 3. 📥 2-STEP CSV INGESTION — DONE (server + UI, tested end-to-end)
- **Step 1:** Drag & drop a CSV onto the new dropzone in the queue panel (or click it / the ⬆ CSV button). Server parses and returns headers + first 3 rows + auto-guessed column mapping. **No DB writes at this step.**
- **Step 2:** A mapping modal opens with dropdowns for **Phone (required), Owner Name, Property Address, Value, Notes**, pre-selected from the auto-guess, plus a data preview. Confirm → import.
- Success feedback bar: *"✔ 4 leads ingested into active queue · 1 rows skipped (no phone)"*; the new list auto-loads as the active queue.
- New `value` column on `imported_leads` surfaces as `prop_value` in the queue; a **Notes** CSV column maps into the lead description shown in the call banner.
- Verified live: preview returned correct auto-mapping for a 5-column test file; confirmed import wrote all fields; queue endpoint served them; test list deleted after.

## 4. 🧪 FUNCTIONAL AUDIT — ALL GREEN
**Buttons (in-browser audit):** all 50 handler references across every `onclick/onchange/ondrop/...` resolve to real functions — **zero dead buttons**. 6 disposition buttons wired.

**Hotkeys (in-browser, captured):**
| Key | Result |
|---|---|
| 1 | paid ✓ |
| 2 | followup — 1st press opens the date row, 2nd submits **with the date** ✓ *(fixed tonight: hotkey path was dropping the follow-up date)* |
| 3 | not_interested ✓ |
| 4 | no_answer ✓ |
| 5 | bad_number ✓ |
| 6 | dnc ✓ |

**Cadence keys:** Space with no pending countdown = verified no-op. Countdown starts correctly → Esc cancels it instantly, bar hides, nothing dials. Space-to-dial is still strictly bound to the countdown state (never during LIVE/WRAP).

**State machine:** real full submit path exercised in-browser (IDLE→BRIEF→LIVE→WRAP→NEXT): after disposition, call state cleared, wrap closed, setup view restored, queue advanced, no stuck states, no double-dial (autodial disabled during test; it also self-guards against LIVE/WRAP/manual/exhausted queue).

**Persistence (verified in cellcoach.db, then cleaned up):**
- `calls` row: duration computed from real start/end (95s ✓), disposition, follow_up_date (`2026-07-31` ✓), rep_notes ✓.
- Lead tagging: `imported_leads.status` + append-only notes log (`[ts] dispo: note`) ✓.
- **DNC:** sticky forever — number vanished from the queue immediately after a DNC dispo and stays out ✓.
- **Dial guard:** TwiML webhook refuses non-allowlisted numbers (`<Say>Dial blocked…</Say>` for +15551234567 ✓). Client guard + 🛡 badge active.

**Server endpoints:** `/api/status` → `twilio_ready: true`, `elevenlabs_ready: true`, guard active with your 3 test numbers.

## 5. 🚀 DEPLOYMENT STATE
- Single clean server instance on port 5099 (PID checked, old instances killed).
- `node --check` on the full UI script: OK · `py_compile`: OK. *(No `tsc` — this app is Python + a single HTML file, no TypeScript.)*
- No test calls were placed tonight, per your instruction. Backups: `cellcoach.py.bak-night`, `cellcoach_ui.html.bak-night`.

---

## ⚠️ ONE BLOCKER FOR MORNING
**The OpenAI API key in `data/cc_config.json` is dead (401).** Post-call AI summaries, session scoring, and GPT coach lines will fail silently until you drop in a fresh key. Twilio + ElevenLabs keys are good.

## GO-LIVE CHECKLIST (when you're ready for real prospects)
1. Load your real CSV via the dropzone → confirm mapping → import.
2. Test-call yourself at 7036460021 first (guard allows it).
3. To open dialing to all numbers: clear `dial_allowed_numbers` in `data/cc_config.json` (the 🛡 badge disappears).
4. Replace the OpenAI key if you want AI coach/summaries.
