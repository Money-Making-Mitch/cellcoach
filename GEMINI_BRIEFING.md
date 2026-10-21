# Cell Coach — Complete Technical Briefing
**Purpose:** This document gives an external AI (Gemini) full knowledge of Cell Coach so it can write precise, executable prompts for Claude to implement changes. Every system, file, data flow, and constraint is covered.

**Date:** 2026-07-20
**Owner:** Sean Tucker (seantucker2@googlemail.com)

---

## 1. WHAT CELL COACH IS

Cell Coach is a standalone, single-user cold-call AI coaching application. A sales rep calls property owners about code violations, fire damage, water damage, foreclosure, or STR enforcement issues. While the rep is on the phone, Cell Coach:

1. Transcribes both sides of the call in real time (rep mic + prospect audio)
2. Classifies what stage of the sales process the call is in
3. Detects objections, buying signals, and prospect intel from what the prospect says
4. Generates real-time coaching text telling the rep exactly what to say next
5. After the call ends, scores the rep's performance and builds a profile of recurring strengths/weaknesses

It also has a **training mode** where the rep practices against an AI-simulated prospect (text chat or ElevenLabs voice).

The sales methodology is **G.U.T.S.** (Claude Diamond's Great Unconventional Techniques of Selling), but the architecture is persona-agnostic — a Grant Cardone persona already exists, and any cold-call methodology can be plugged in by creating a new persona + exemplar library.

---

## 2. HARD RULES — NEVER VIOLATE

- **Keys stay on this machine.** All API keys live in `C:\Users\Admin\data_center\data\cc_config.json` only. Never committed, never uploaded, never printed.
- **Touch ONLY files inside `cell_coach/`.** Never import from `lead_machine` or `data/` folders.
- **No pip installs.** Python stdlib only. The server runs on `http.server.ThreadingHTTPServer`.
- **Before editing code, READ the actual function first.** Ground changes in real logic, not assumptions.
- **After any backend change, verify:** `python -c "import cellcoach; print('OK')"` (Windows — use `python` not `python3`).

---

## 3. FILE STRUCTURE

```
C:\Users\Admin\data_center\cell_coach\
├── cellcoach.py              # Backend server (~2,560 lines). ALL endpoints, all AI logic.
├── cellcoach_ui.html          # Frontend (~2,700 lines). Single HTML file, all JS inline.
├── cc_config.json             # Local config (may also be at ../data/cc_config.json)
├── cc_staircase.json          # G.U.T.S. exemplar library — per-step coaching examples
├── cc_personas.json           # Coaching personas (G.U.T.S., Cardone, custom)
├── cc_scenarios.json          # Training scenarios (5 scenarios × 3 difficulties each)
├── cc_sources.json            # Lead source registry (SQLite DBs + CSV imports)
├── cellcoach.db               # SQLite database (calls, leads, scores, profile)
├── recordings/                # Saved .webm call recordings
├── START.bat                  # Double-click launcher
├── HANDOFF.md                 # Dev handoff doc from last session
├── ENTERPRISE_AUDIT.md        # Full production-readiness audit (35 findings)
├── SPEC_coach_state_and_exemplars.md  # Spec for state carry-over + exemplar features
└── tests/
    ├── extract_dialogue.py    # Corpus extraction from conversations.json
    └── eval_coach.py          # 8 eval fixtures (gated behind CC_EVAL=1)
```

---

## 4. HOW TO RUN

```
cd C:\Users\Admin\data_center\cell_coach
python cellcoach.py
```

Opens `http://127.0.0.1:5099` in the browser. Port 5099, bound to localhost only.

---

## 5. API KEYS (in cc_config.json)

| Key | Service | Used For |
|-----|---------|----------|
| `openai_key` | OpenAI | GPT-4o (coaching Node 3), GPT-4o-mini (classification, signals, training prospect, scoring, post-call summary) |
| `assemblyai_key` | AssemblyAI | Real-time speech-to-text via WebSocket (v3 streaming, dual sockets) |
| `twilio_account_sid` | Twilio | Browser-based phone calls |
| `twilio_api_key` | Twilio | Token generation for Twilio Voice SDK |
| `twilio_api_secret` | Twilio | Token generation |
| `twilio_twiml_app_sid` | Twilio | TwiML app for call routing |
| `twilio_from_number` | Twilio | Caller ID number |
| `elevenlabs_key` | ElevenLabs | Voice training mode (AI prospect speaks) |
| `elevenlabs_agent_id` | ElevenLabs | Conversational AI agent for voice training |
| `elevenlabs_voice_id_male` | ElevenLabs | Male prospect voice |
| `elevenlabs_voice_id_female` | ElevenLabs | Female prospect voice |

Optional: `rep_identity` (defaults to `"Sean with Risk & Compliance Bureau"`)

---

## 6. THE G.U.T.S. STAIRCASE (sales methodology)

5 steps in strict order, never skipped:

### Step 1: INTRO (staircase_step = "intro")
- Name + agency + specific observed fact from records + ONE hook question
- Hook: "You aware of that situation?" (standard) or "You got a few minutes to talk?" (crisis)
- Tone matches severity: crisis calls (fire/water/foreclosure) acknowledge stress FIRST
- NEVER: "how are you", official/authority tone, agenda language yet
- Advance when: prospect engages past the hook

### Step 2: AGENDA (staircase_step = "agenda")
- Permission + roadmap + guilt-free exit
- "I want to ask you a couple questions... if it's not a fit, just tell me."
- Pre-commitment: "Fair?" — this gets cashed later when they stall
- Advance when: prospect says "sure", "go ahead", or asks what you need

### Step 3: QUALIFICATION (staircase_step = "qualification")
- Surface 4 pillars by ASKING, never assuming:
  1. **NEED/GREED** — pain level 1-10, emotional trigger, urgency
  2. **MONEY** — can they fund a fix, or is cash locked up
  3. **AUTHORITY** — decide alone or need spouse/partner
  4. **TIME** — how long, deadline, what happens if nothing changes
- Plus: **desired_outcome** — fix/keep, sell, lease, or done
- 75% of prospects don't qualify. Firing a bad prospect is a WIN.
- Never presuppose the play. Never present before qualifying.
- Advance when: all 4 pillars known AND desired_outcome surfaced
- `qualification_verdict`: pass | fail | undetermined

### Step 4: COMMITMENT (staircase_step = "commitment")
- Hypothetical close: "Say I could get that handled — what would you say?"
- Prospect names the finish line themselves BEFORE any play is presented
- Advance when: prospect states what they'd say yes to

### Step 5: PLAY + CLOSE (staircase_step = "play_close")
- Present exactly ONE play (the one qualification surfaced, never a menu):
  - **CONTRACTOR REFERRAL** — violation fixable, owner keeps it. Paid by contractor's referral fee. MANDATORY for crisis (fire/water).
  - **EXTENSION FILING** — buys time with city on compliance deadline. Direct fee OK.
  - **LEASE OPTION** — owner wants monthly income, out of management.
  - **CASH BUY** — owner wants out clean. ~70% ARV minus repairs, assignment fee margin.
  - **FORECLOSURE DEBT-PAYOFF** — pay off what they owe lender, fix, flip. NOT lease-option.
- Lock specific day/time callback TODAY
- Freedom close: "It's cool if the answer's no"
- Pin "I'll think about it": cash the pre-commitment from Step 2
- Capture phone + email

### The Three Moves (used throughout, not sequential):
- **STROKE** — sincere recognition on legit pushback
- **NURTURE** — normalize their pain
- **REDIRECTION** — short answer + question; negative phrasing; OPPOSITE when attacked
- **TAKEAWAY** — pull back when they're hot ("maybe this isn't a fit")

---

## 7. ARCHITECTURE — THE 3-NODE COACHING PIPELINE

`/api/analyze` is the core endpoint. Every coaching request flows through it.

### Opener (Node 0) — NO LLM
When `opening=True` and no transcript exists, `_node_opener()` fires. It's pure template fill:
- Reads `owner` (prospect name), `play` (violation type), `address`, `notes`
- `_play_to_intro_sub_step(play)` → crisis | vacant | standard
- `_build_fact_line(ctx)` → maps play type to a specific fact sentence (e.g., STR → "your property has been flagged for short-term rental activity without a valid license")
- Fills a template: `"Hey {firstName}, this is {repName} with {agency}. I'm calling because {fact}. {hookQuestion}"`
- Returns the full analysis JSON instantly — zero API calls, zero latency

### Ongoing Calls — 3 Nodes in Sequence

**Node 1: Stage Classifier** (`_node_classify`) — GPT-4o-mini, ~100 tokens out
- Input: transcript (last 2000 chars) + latest prospect line + prior state
- Output: `staircase_step`, `checklist`, `qualification_verdict`
- Enforces monotonic rules IN CODE (not LLM): checklist items never regress true→false
- System prompt is `_NODE1_SYSTEM` — focused exclusively on classification
- Falls back to prior state on any error

**Node 2: Signal Detector** (`_node_signals`) — GPT-4o-mini, ~200 tokens out
- Input: latest prospect statement + call context (last 800 chars)
- Output: `objection`, `context_line`, `temperature`, `prospect_intel` (5 fields)
- Merges new intel with prior intel — known facts are never lost
- System prompt is `_NODE2_SYSTEM`

**Node 3: Coach** (`_node_coach`) — GPT-4o, ~300 tokens out
- Input: current step + signals + lead context + persona prompt + active staircase block
- Output: `say_next`, `alt_suggestion`, `coach_type`, `next_action`, `summary`, `play`
- Uses `_NODE3_CONTRACT` which enforces **strict exemplar matching**:
  - Pick ONE closest-matching approved example
  - Copy its EXACT sentence structure
  - Swap ONLY: name, fact, agency, stated number
  - Do NOT blend multiple examples
  - Do NOT paraphrase or restructure

**Node 3 Skip Gate** (`skip_node3`):
- If step unchanged + no new objection + no new intel + we have a prior say_next → skip the expensive GPT-4o call and return the prior coaching. Saves ~300 tokens and one round trip per turn.

### Merge
All three node outputs are merged into the standard `analysis` JSON shape that the frontend expects. The frontend doesn't know or care about the node split — the API contract is unchanged.

### Staircase Block Injection
`_build_staircase_block(current_step)` loads ONLY the active step's exemplars from `cc_staircase.json` and formats them for the prompt. This keeps token usage tight — the coach never sees exemplars for steps it's not on.

### State Carry-Over
- Frontend stores `S.lastAnalysis` after each coaching response
- On every subsequent `/api/analyze` call, frontend sends `prior_state: { staircase_step, checklist, prospect_intel, play }`
- Backend's `_build_state_block(prior)` injects a CURRENT CALL STATE block with monotonic rules
- Node 1 (`_node_classify`) also receives prior state and enforces monotonicity in code

---

## 8. FRONTEND ARCHITECTURE (cellcoach_ui.html)

Single HTML file. All CSS and JS inline. No build step, no framework.

### State Object `S` (~line 1185)
```javascript
let S = {
  wsRep: null,              // AssemblyAI WebSocket for rep mic
  wsProspect: null,         // AssemblyAI WebSocket for prospect audio
  ctx: null,                // AudioContext
  workletRep: null,         // AudioWorkletNode for rep
  workletProspect: null,    // AudioWorkletNode for prospect
  transcript: '',           // Full labeled transcript (REP: / PROSPECT:)
  coachContext: '',          // Transcript minus screening lines
  transcriptLines: [],
  timer: null,
  streams: [],
  on: false,
  startedAt: null,
  lastProspect: '',         // Last prospect statement
  timerInterval: null,
  seconds: 0,
  altSuggestion: null,
  showingAlt: false,
  primaryText: '',
  twilioConn: null,
  twilioDevice: null,
  muted: false,
  instantFired: false,
  recDest: null,             // MediaStreamDestination for recording
  recorder: null,
  recChunks: [],
  recBlob: null,
  callLog: [],               // Event log for coaching exports
  seq: 0,
  lastAnalysis: null,        // Last coaching response (for state carry-over)
  openerShown: false,        // Gate: has the full opener been generated?
  recentCoachLines: [],      // Rolling buffer of last 3 say_next (for dedupe)
  trainMode: null,           // 'text' | 'voice' | null
  trainSessionId: null,
  custom: null,              // Custom play context (live calls only)
  repSpoke: false,           // Has the rep spoken yet? Gates coaching advancement
};
```

### UI Views
1. **Setup View** (`#setupView`) — the cockpit. Contains:
   - Top bar: persona selector, settings, train mode toggle
   - Left panel: lead queue (from cc_sources.json or CSV imports)
   - Right panel: lead detail form (owner, address, play, phone, notes, fee)
   - Call method selector (Phone Link vs Twilio)
   - Phone Link device picker (`#prospectDevSelect` — enumerates audio inputs, auto-selects Stereo Mix/loopback)
   - Start Call button

2. **Live View** (`#liveView`) — shown during active calls. Contains:
   - Left: scrolling transcript (labeled REP/PROSPECT, screening lines dimmed)
   - Right: AI Coach panel:
     - Context line (what the prospect just communicated)
     - Coach badge (rebuttal/discovery/empathy/close/rapport/screening/instant)
     - SAY THIS card (the coaching text — large, readable)
     - Alt suggestion toggle
     - False Start button (resets staircase)
     - Call Progress checklist (4 items: intro, qualified, play selected, committed)
     - Intel card (properties, urgency, decides, wants, their #, temperature)
   - Timer, status pill, end call / disposition buttons

3. **Train Setup** (`#trainSetup`) — shown when train mode is toggled. Contains:
   - Scenario picker (5 scenarios)
   - Difficulty selector (easy/medium/hard)
   - Gender picker (male/female/random)
   - Character preview (name + personality description)
   - Mode selector (text/voice)
   - Start Training button

### Key Frontend Functions

**Call Lifecycle:**
- `start()` → initializes audio, gets AAI tokens, opens WebSockets, shows `showFirstMoveCard()`
- `showFirstMoveCard()` → static card: "Hey, is this {firstName}?" — NO API call
- `showOpeningLine()` → calls `/api/analyze` with `opening:true` — fires AFTER first real prospect line (`S.openerShown` gate)
- `scheduleAnalyze()` → debounces 250ms, then calls `analyze()`
- `analyze()` → POST `/api/analyze` with transcript + prior_state
- `showCoaching(a, isInstant, isStub)` → renders the coaching card, stores `S.lastAnalysis`, runs dedupe
- `_isRepeatCoach(text)` → suppresses coaching cards with >65% word overlap vs recent
- `stopCall()` → tears down audio, WebSockets
- `dispo(d)` / `submitDispo()` → sends disposition + transcript to `/api/call_end`

**Prospect Audio (two methods):**
- **Phone Link:** `startPhoneLinkCapture()` — `getUserMedia` with selected loopback device (Stereo Mix, VB-Audio, etc.)
- **Twilio:** `startTwilioCall()` — Twilio Voice SDK, gets remote stream, connects to AAI WebSocket

**Training:**
- `startTraining()` → POST `/api/train/start`, sets form fields to prospect name + play, shows `showFirstMoveCard()`, starts text or voice mode
- `sendTrainChat()` → POST `/api/train/chat` with rep line + history + prior_state, gets prospect line + coaching
- `startVoiceTraining()` → connects to ElevenLabs Conversational AI agent
- `endTrainingSession()` → POST `/api/train/end`, triggers scoring

**Transcript Assembly:**
- Two separate AssemblyAI v3 WebSocket streams: one for REP (mic), one for PROSPECT (system audio or Twilio remote stream)
- `openSocket(token, label)` — handles the REP socket (same-page)
- `openProspectSocket(token)` — handles the PROSPECT socket (separate function for Phone Link / late-bind)
- Each socket receives Turn events. On `end_of_turn`, it:
  - Calls `addTranscriptLine()` which appends to both `S.transcript` and `S.coachContext`
  - If PROSPECT and not screening: checks `S.openerShown` gate, then `scheduleAnalyze()`
  - If REP: sets `S.repSpoke = true`
- `isScreeningText(text)` — detects automated screeners/voicemail by pattern matching

**Instant Objection Handling:**
- `INSTANT_REBUTTALS` object — pattern-matched responses for common objections (scam, not interested, how much, etc.)
- `checkInstant(text)` — checks prospect text against patterns, fires `showCoaching()` with `isInstant=true` if matched
- Fires once per call (`S.instantFired` flag), before the GPT call returns — zero latency

---

## 9. BACKEND ENDPOINTS (cellcoach.py)

### Core Coaching
| Endpoint | Method | Function | Description |
|----------|--------|----------|-------------|
| `/api/analyze` | POST | `ep_analyze(d)` | 3-node coaching pipeline. Opener (template) or classify→signals→coach |
| `/api/call_end` | POST | `ep_call_end(d)` | Saves call record, triggers background scoring + summary |
| `/api/aai_token` | GET | `ep_aai()` | Mints a 600s AssemblyAI streaming token |
| `/api/status` | GET | `ep_status()` | Returns key status, Twilio readiness, ElevenLabs readiness |

### Training
| Endpoint | Method | Function | Description |
|----------|--------|----------|-------------|
| `/api/train/scenarios` | GET | `ep_train_scenarios()` | Lists all training scenarios |
| `/api/train/start` | POST | `ep_train_start(d)` | Creates training session, returns scenario config |
| `/api/train/chat` | POST | `ep_train_chat(d)` | Text mode: generates prospect line + runs 3-node coach |
| `/api/train/credentials` | POST | `ep_train_credentials_full(d)` | Voice mode: returns ElevenLabs signed URL |
| `/api/train/end` | POST | `ep_train_end(d)` | Ends training, triggers scoring |
| `/api/train/preview_character` | GET | `ep_train_preview_character()` | Previews prospect name/gender for setup screen |
| `/api/train/voices` | GET | `ep_elevenlabs_voices()` | Lists ElevenLabs voices |
| `/api/train/voices/set` | POST | `ep_set_train_voices(d)` | Sets male/female voice IDs in config |

### Personas
| Endpoint | Method | Function | Description |
|----------|--------|----------|-------------|
| `/api/personas` | GET | `ep_personas_list()` | Lists all coaching personas |
| `/api/personas` | POST | `ep_persona_save(d)` | Creates or updates a persona |
| `/api/personas/delete` | POST | `ep_persona_delete(pid)` | Deletes non-built-in persona |
| `/api/personas/reset` | POST | `ep_persona_reset(pid)` | Resets built-in persona to default |

### Lead Management
| Endpoint | Method | Function | Description |
|----------|--------|----------|-------------|
| `/api/sources` | GET | `ep_sources()` | Lists configured lead sources |
| `/api/queue` | GET | `ep_queue(qs)` | Returns lead queue (filtered/paginated) |
| `/api/import_csv` | POST | `ep_import_csv(d)` | Imports leads from CSV |
| `/api/import_delete` | POST | `ep_import_delete(d)` | Deletes imported leads by source |

### Call History & Exports
| Endpoint | Method | Function | Description |
|----------|--------|----------|-------------|
| `/api/history` | GET | `ep_history()` | Returns all calls with scores |
| `/api/export/{id}/call` | GET | | Downloads clean call transcript (REP+PROSPECT only) |
| `/api/export/{id}/coaching` | GET | | Downloads coaching review (all 3 parties + raw JSON) |
| `/api/save_recording` | POST | `ep_save_recording()` | Binary upload of .webm recording |
| `/api/prep_by_phone/{phone}` | GET | `ep_prep_by_phone()` | Returns prior call summary + next-call prep for a phone number |

### Rep Profile & Scoring
| Endpoint | Method | Function | Description |
|----------|--------|----------|-------------|
| `/api/profile` | GET | `ep_get_profile()` | Returns aggregated rep profile |
| `/api/profile/scores` | GET | `ep_get_scores(qs)` | Returns individual session scores |
| `/api/profile/rules` | POST | `ep_update_rules(d)` | Updates manual coaching rules |
| `/api/profile/weaknesses` | POST | `ep_edit_weaknesses(d)` | Edits weakness labels |
| `/api/profile/backfill` | POST | `ep_backfill_scores()` | Rescores all unscored sessions |

### Twilio
| Endpoint | Method | Function | Description |
|----------|--------|----------|-------------|
| `/api/twilio_token` | GET | `ep_twilio_token()` | Mints Twilio access token |
| `/api/twilio_voice` | POST | `ep_twilio_voice(params)` | TwiML webhook for outbound calls |

---

## 10. DATABASE SCHEMA (cellcoach.db — SQLite, WAL mode)

### calls
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
phone TEXT, play TEXT, owner TEXT, address TEXT, case_id TEXT,
started_at TEXT, ended_at TEXT, duration INTEGER DEFAULT 0,
disposition TEXT,              -- paid | followup | not_interested | no_answer | bad_number | train_text | train_voice
follow_up_date TEXT DEFAULT '',
transcript TEXT DEFAULT '',    -- Full labeled transcript (REP: / PROSPECT:)
checklist TEXT DEFAULT '{}',
summary TEXT DEFAULT '',       -- GPT-generated post-call summary
next_call_prep TEXT DEFAULT '',-- GPT-generated prep brief for next call
recording TEXT DEFAULT '',     -- Filename of .webm recording
coach_log TEXT DEFAULT '',     -- JSON array of all coaching events during the call
scored INTEGER DEFAULT 0       -- 1 once _score_session has run
```

### session_scores
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
call_id INTEGER NOT NULL,
scored_at TEXT NOT NULL,
is_training INTEGER DEFAULT 0,
scenario_id TEXT DEFAULT '',
difficulty TEXT DEFAULT '',
overall_grade TEXT DEFAULT '',    -- A/B/C/D/F
opener_score INTEGER DEFAULT 0,  -- 1-10
discovery_score INTEGER DEFAULT 0,
objection_handling_score INTEGER DEFAULT 0,
pitch_timing_score INTEGER DEFAULT 0,
tone_score INTEGER DEFAULT 0,
close_score INTEGER DEFAULT 0,
weaknesses TEXT DEFAULT '[]',    -- JSON array of G.U.T.S.-specific labels
strengths TEXT DEFAULT '[]',
notes TEXT DEFAULT '',
raw_json TEXT DEFAULT '{}'
```

### rep_profile
```sql
id INTEGER PRIMARY KEY,          -- always row id=1 (single user)
updated_at TEXT DEFAULT '',
sessions_analyzed INTEGER DEFAULT 0,
avg_overall TEXT DEFAULT '',
weak_categories TEXT DEFAULT '[]',
strong_categories TEXT DEFAULT '[]',
recurring_habits TEXT DEFAULT '[]',
manual_rules TEXT DEFAULT '[]',  -- User-added coaching rules injected into every prompt
last_5_grades TEXT DEFAULT '[]'
```

### imported_leads
```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
source TEXT, owner TEXT, phone TEXT, address TEXT, zip TEXT DEFAULT '',
case_id TEXT DEFAULT '', play TEXT DEFAULT 'GENERAL', score TEXT DEFAULT '',
description TEXT DEFAULT '', imported_at TEXT
```

---

## 11. PERSONAS (cc_personas.json)

Two built-in personas:

### `sean_direct` — "Sean — G.U.T.S. Direct"
- Claude Diamond's G.U.T.S. method coached in Sean's voice (young, professional, direct)
- Extremely detailed system prompt (~4,000 words) covering:
  - Voice rules (what Sean sounds like, what he doesn't)
  - The Million-Dollar Rule (emotional decisions, 1-10 scale tracking)
  - Doctor posture (rep asks, prospect talks)
  - Full 4-step staircase with detailed exit criteria
  - The Three Moves with modern phrasing
  - Objection handling playbook (8 specific scenarios)
  - Non-negotiable rules
  - say_next output rules

### `cardone` — "Cardone Cold-Call Method"
- Grant Cardone's method: hook → problem → price early → one-call close
- Emphasis on research-backed rules (answer objections with questions 54% of time, freedom close, fear pairing)

Custom personas can be created through the UI. The persona is pure voice/philosophy — it gets `OUTPUT_CONTRACT` appended (for the old monolithic path) or `_NODE3_CONTRACT` appended (for the 3-node pipeline) to enforce JSON output.

---

## 12. EXEMPLAR LIBRARY (cc_staircase.json)

Version 2. Contains real verbatim dialogue from Sean's actual training transcripts.

Structure:
```json
{
  "version": 2,
  "steps": {
    "intro": {
      "label": "Intro (Step 1a)",
      "goal": "...",
      "advance_when": "...",
      "sub_steps": {
        "standard": { "guidance": "...", "exemplars": [...] },
        "vacant": { "guidance": "...", "exemplars": [...] },
        "multi_violation": { "guidance": "...", "exemplars": [...] },
        "crisis": { "guidance": "...", "exemplars": [...] }
      }
    },
    "agenda": { ... },
    "qualification": {
      "sub_steps": {
        "need_greed": { ... },
        "money": { ... },
        "authority": { ... },
        "time": { ... },
        "desired_outcome": { ... },
        "disqualify": { ... }
      }
    },
    "commitment": { ... },
    "play_close": { ... }
  },
  "moves": {
    "stroke": "...",
    "nurture": "...",
    "redirection": "...",
    "takeaway": "..."
  }
}
```

Each exemplar has: `situation`, `text` (the exact words), `source` (owner-verbatim | corpus | pattern-derived).

`_build_staircase_block(current_step)` loads ONLY the active step and formats it for the prompt. The coach never sees exemplars for steps it's not on.

---

## 13. TRAINING SCENARIOS (cc_scenarios.json)

5 scenarios, each with easy/medium/hard:
1. `code_violation_residential` — play_context: "STR, LAND_USE, STRUCTURE, PERMIT, or ABATEMENT"
2. `str_violation` — play_context: "STR"
3. `fire_damage_owner` — play_context: "FIRE"
4. `foreclosure_owner` — play_context: "FORECLOSURE"
5. `absentee_owner` — play_context: "LAND_USE, STRUCTURE, ABATEMENT"

Each difficulty has:
- `systemPrompt` — character instructions for the AI prospect (personality, behavior, objections)
- `firstMessage` — what the prospect says first ("Hello?" / "Yeah?")
- `objections` — list of objection types the prospect will raise
- `imperfections` — filler frequency, interruption chance, thinking pauses, emotional variability

`TRAIN_GUARDRAILS` is appended to every prospect system prompt to prevent the AI from breaking character.

Prospect name is randomly selected from `NAME_BANK` (25 male + 25 female names) and can be rerolled on the setup screen.

---

## 14. SCORING & PROFILE SYSTEM

### Post-Call Pipeline (background threads)
When a call ends with a transcript:
1. `_post_call_ai(sid)` — GPT-4o-mini generates a 2-3 sentence summary + next-call prep brief
2. `_score_session(sid)` — GPT-4o-mini scores 6 categories (1-10 each):
   - opener, discovery, objection_handling, pitch_timing, tone, close
   - Overall grade: A/B/C/D/F
   - Weaknesses: G.U.T.S.-specific labels (e.g., `premature_presentation`, `skipped_qualification`, `no_freedom_close`)
   - Strengths: G.U.T.S.-specific labels (e.g., `clean_intro_pattern`, `hit_all_four_pillars`, `used_takeaway`)
3. `_rebuild_profile()` — aggregates all scores into `rep_profile` table

### Profile Injection
`_get_profile_context()` reads the rep profile and formats it for injection into coaching prompts. This means the coach knows: "This rep tends to skip qualification" or "This rep's strength is objection handling."

---

## 15. CALL RECORDING

- `startRecorder()` in frontend creates a `MediaRecorder` from `S.recDest` (a `MediaStreamDestination` that both mic and prospect audio feed into)
- Records to .webm (opus codec)
- On call end, uploads via `POST /api/save_recording` as raw binary
- Files saved to `cell_coach/recordings/YYYYMMDD_HHMMSS_phone.webm`
- No consent handling exists (see ENTERPRISE_AUDIT.md §A2)

---

## 16. LEAD SOURCES & QUEUE

### cc_sources.json
Config-driven. Each source entry points to a SQLite DB with column mapping:
```json
{
  "id": "command_center",
  "path": "../data/command_center.db",
  "table": "leads",
  "where": "phone IS NOT NULL AND phone != '' AND stage = 'NEW'",
  "order": "priority DESC",
  "limit": 400,
  "map": { "owner": "owner", "phone": "phone", "address": "address", ... }
}
```

### CSV Import
Leads can also be imported from CSV via the UI. Stored in `imported_leads` table in cellcoach.db.

### Queue
`/api/queue` merges all sources + imported leads, returns them sorted by priority. The frontend renders a scrollable lead queue with search and filter.

---

## 17. COACH STAKES MAP

`COACH_STAKES` maps play types to pressure descriptions + crisis flag:
- STR, LAND_USE, STRUCTURE, ABATEMENT, PERMIT, 311 → not crisis
- FIRE, WATER, FORECLOSURE → crisis=True → crisis tone, never charge directly

---

## 18. WHAT'S BEEN DONE RECENTLY (as of 2026-07-20)

1. **Phone Link audio capture** — replaced `getDisplayMedia` with `getUserMedia` device picker
2. **State carry-over** — frontend stores + sends prior_state, backend injects CURRENT CALL STATE
3. **G.U.T.S. exemplar library** — cc_staircase.json with real verbatim lines
4. **3-node coaching pipeline** — split ep_analyze into classify → signals → coach
5. **Deterministic opener** — _node_opener does template fill, zero LLM calls
6. **Opener timing fix** — showFirstMoveCard() shows "Hey, is this {Name}?" on connect, real opener fires after prospect responds
7. **Dedupe suppression** — _isRepeatCoach() prevents redundant coaching cards
8. **Training mode fixed** — form fields now pass real prospect name + empty notes instead of "[TRAIN]" metadata
9. **Training upgraded to 3-node pipeline** — ep_train_chat now uses same classify→signals→coach as live calls

---

## 19. KNOWN ISSUES / TODO

1. **Voice training coaching** — the ElevenLabs voice path captures transcript via AssemblyAI but coaching fires through the same analyze() path as live calls. Needs verification that it works end-to-end.
2. **Scoring is fire-and-forget** — `_score_session` runs in a daemon thread with `time.sleep(4)` coordination. If it dies, the session is silently never scored. No retry.
3. **No authentication** — all endpoints are open on localhost. Fine for single-user, blocks enterprise.
4. **No recording consent** — no two-party-consent state detection.
5. **Script claims** — some exemplars include "I checked with the inspector this morning" which may be false (see ENTERPRISE_AUDIT.md §A1).
6. **No retry/backoff** — single-shot HTTP calls to OpenAI/AssemblyAI. One transient error = dead coaching turn.
7. **No WebSocket reconnect** — if AAI socket drops mid-call, transcription for that channel ends silently.

---

## 20. HOW TO PROMPT CLAUDE TO MAKE CHANGES

### For backend changes:
1. Name the exact function and what to change
2. Reference the 3-node pipeline by node name (Node 1 = _node_classify, Node 2 = _node_signals, Node 3 = _node_coach, Node 0 = _node_opener)
3. Specify which file: `cellcoach.py`
4. Always ask Claude to verify with `python -c "import cellcoach; print('OK')"` after

### For frontend changes:
1. Name the exact function (e.g., `showCoaching`, `analyze`, `startTraining`)
2. Reference the state variable involved (e.g., `S.lastAnalysis`, `S.openerShown`)
3. Specify: `cellcoach_ui.html`

### For persona/methodology changes:
1. Personas live in `cc_personas.json` — each is a `system_prompt` string
2. Exemplars live in `cc_staircase.json` — structured per-step/sub-step
3. To add a new methodology: create a new persona + optionally a new staircase file
4. The pipeline is persona-agnostic — it passes `persona_prompt` as a parameter to Node 3

### For training scenario changes:
1. Scenarios live in `cc_scenarios.json`
2. Each has difficulties with systemPrompt (prospect character), firstMessage, objections, imperfections
3. `TRAIN_GUARDRAILS` is appended automatically

### Example prompts:
- "In cellcoach.py, modify `_node_classify` to also detect when the prospect says 'let me talk to my wife' as an authority signal and set qualification_verdict to 'undetermined' rather than leaving it at the prior value."
- "In cellcoach_ui.html, modify `showCoaching()` to flash the coach card border red when an objection is detected (not just blue)."
- "Create a new training scenario in cc_scenarios.json for OSHA violations with easy/medium/hard difficulties."
- "Add a new persona to cc_personas.json implementing the Sandler Selling System methodology."
