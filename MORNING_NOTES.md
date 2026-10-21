# Cell Coach 2 — Morning Handoff (built overnight 2026-07-29)

> **📋 LATEST: the full night-shift overhaul (Phone Link stripped, light-mode UI, 2-step CSV import, complete button/hotkey audit) is in `NIGHT_SHIFT_REPORT.md` — read that first.** Everything below still applies.

## What's new since you went to sleep

### ⚡ Autodial cadence (new)
- **⚡ Auto toggle** in the queue header (persists between sessions). ON by default.
- After every disposition: **3-second countdown bar** appears above the Start button → auto-dials the next queue lead.
  - **Space** = skip the buffer, dial now (only works while a countdown is showing — dead key otherwise, can never double-dial or hang up a live call)
  - **Esc** or the ✕ button = stop the cadence
  - Clicking any queue row / the manual row / toggling Auto off instantly cancels a pending countdown
  - Queue exhausted → cadence stops itself. A failed dial never retries — no loops, ever.
- **Session counter chip** (`N dials`) next to the toggle.

### 🛡 Test-mode dial guard (armed right now)
- `data/cc_config.json` → `dial_allowed_numbers` = your 3 test numbers.
- **Server-enforced**: the TwiML webhook refuses any other number — a mis-click can never ring a real prospect. Client shows the same block as a setup error, plus a `🛡 TEST: 3 numbers` badge in the queue header.
- **GOING LIVE = remove that one line** (or set it to `[]`) and restart. That's it.

### Also shipped last night (verified live with your calls)
- **Hangup freeze**: the instant a call ends, the timer stops at true duration, coach/transcription/recording stop, dispo bar pulses "pick a disposition (1-6)". Duration in the DB is now real talk time, not talk + wrap.
- **Lead tagging**: every call writes disposition → `imported_leads.status` + appends timestamped notes. Rep notes from the notes field are saved (`calls.rep_notes`) — they were being discarded before.
- **🚫 DNC button (hotkey 6)**: permanently scrubs a number from every queue. Sticky — nothing un-hides it except editing the DB.
- **DID rotation bookkeeping**: `dials_today` now increments on every pool call (it never did in the standalone app). Pool still has only ONE number — buy 2–3 more Twilio DIDs for real rotation.

## Morning test sequence (only your 3 numbers will dial)
1. Server should already be running: http://127.0.0.1:5099 (if not: `python cellcoach.py` in this folder)
2. Pick the **TEST-SEAN-ONLY** list (or any list — the guard makes mis-dials impossible)
3. Click the lead → START → answer your phone → hang up from your cell → watch the freeze + pulsing dispo bar
4. Hit a dispo hotkey (1-6) → watch the 3s countdown → Space to fire immediately, or let it ride
5. Let it chain 2-3 calls, then hit Esc to stop the cadence

## 🚨 Still blocked — needs you
**OpenAI key in `data/cc_config.json` is dead (401).** Post-call AI summaries, session scoring, and GPT live-coach suggestions are OFF until you paste a fresh key (rule-based instant coaching still works). Failures now log loudly to the server console instead of dying silently.

## Rollback / pivot notes
- Backups: `cellcoach.py.bak-pre-test`, `cellcoach_ui.html.bak-pre-test`
- datacenter2 restore: point TwiML App voice URL back to `/api/dialer/voice-webhook` and the ngrok tunnel back to 8080 (currently `/api/twilio_voice` → 5099)
- ngrok reserved domain: `atrophy-strict-heroics.ngrok-free.dev`
