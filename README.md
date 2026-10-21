# Cell Coach — Standalone Live Call Coach

AI coaching overlay for cold calls made through Microsoft Phone Link.
Fill in the call context, dial on your cell, press Start.

## Quick start

1. Add your API keys to `cc_config.json` (created on first run):
   - `openai_key` — GPT-4o for live coaching and post-call summaries
   - `assemblyai_key` — real-time transcription
   - `rep_identity` — your intro line (default: "Sean with Risk & Compliance Bureau")

2. Double-click `START.bat` (or `python cellcoach.py`)

3. Browser opens at `http://127.0.0.1:5099`

## How it works

- Fill in the context card: play, owner, address, case #, fee, notes
- Dial the number (rings your cell via Phone Link)
- Press **Start Coaching** — share Entire Screen + check "Share system audio"
- Use a **headset** to avoid echo
- The coach transcribes both sides (REP / PROSPECT labels), detects objections instantly via regex then refines with GPT-4o, and shows exactly what to say next
- Press **Stop** — pick a disposition — call is logged locally with AI-generated prep for next time

## Live test checklist

- [ ] Phone Link connected
- [ ] Dial — Start Coaching — Entire Screen + system audio
- [ ] Both REP: and PROSPECT: labels appear in transcript
- [ ] Say "not interested" — instant rebuttal fires ahead of GPT
- [ ] Stop — disposition overlay — pick one
- [ ] Re-enter same number — prep recall panel appears

## Files

- `cellcoach.py` — Python backend (stdlib only, no pip installs)
- `cellcoach_ui.html` — Frontend (loaded at runtime)
- `cc_config.json` — API keys (created on first run, never committed)
- `cellcoach.db` — Local call history (SQLite, created on first run)
- `START.bat` — Launcher

## Cost per call

~15-25 cents for a 10-minute call (AssemblyAI two-socket + GPT-4o analyze-on-prospect-turns-only).
