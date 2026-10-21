# Cell Coach — Train Mode Spec

**Purpose:** Generate diverse, realistic call transcripts that stress-test the AI coach's responses so its personas, stakes map, and `say_next` output improve over time. NOT rep training — coach training.

**Architecture constraint:** Single-file Python (`cellcoach.py`) + single-file HTML (`cellcoach_ui.html`). No npm, no React, no Supabase, no pip installs. Stdlib HTTP server on port 5099.

---

## 1. Two Sub-Modes

### 1A. Text Mode ("Rapid Fire")

A chat interface where an LLM plays the prospect. You type your rep lines, the coach responds, the simulated prospect reacts. Runs entirely through GPT-4o-mini. Near-zero cost per conversation (~$0.01-0.03).

**Why it matters for coach training:** You can run 50 scenario variations in an hour, exposing the coach to edge cases, unusual objections, emotional shifts, and plays it rarely sees in live calls. Each session produces a transcript + coach log you can review to find where the coach gave weak/wrong advice.

**Flow:**
1. Pick scenario + difficulty from the scenario bank
2. Frontend sends `POST /api/train_start` → backend creates a training session record, returns `session_id` + prospect persona prompt + first message
3. Prospect's first message appears in the chat panel
4. You type your rep line → frontend sends it to `POST /api/train_chat` with the full conversation so far
5. Backend does TWO things in sequence:
   - Runs the prospect LLM (GPT-4o-mini with the scenario system prompt) → generates the prospect's next line
   - Runs the existing `ep_analyze()` coaching engine against the growing transcript → produces the coach response
6. Returns both: `{ prospect_line, coach_analysis }`
7. Frontend displays the prospect line in the chat panel, the coach response in the existing coaching panel (same UI as live calls)
8. Repeat until you end the session → `POST /api/train_end` saves the full transcript + coach log to the `calls` table with `disposition = 'train_text'`

### 1B. Voice Mode ("Live Sim")

Browser-based voice call using ElevenLabs Conversational AI. You speak into your mic, the AI prospect talks back out loud, AssemblyAI transcribes both sides into `REP:`/`PROSPECT:` lanes, and the coaching engine runs on the transcript identically to a real call.

**Why it matters for coach training:** Tests the coach under realistic conditions — interruptions, crosstalk, filler words, emotional tone shifts, timing pressure. Things text mode can't simulate.

**Cost:** ~$0.08/min ElevenLabs + $0.01-0.03 coach analysis = ~$0.80-0.85 per 10-min call.

**Flow:**
1. Pick scenario + difficulty
2. Frontend sends `POST /api/train_start` → backend creates session, returns `session_id`
3. Frontend calls `GET /api/train_credentials?session_id=X` → backend hits ElevenLabs signed-URL API server-side, returns `{ signedUrl, systemPrompt, firstMessage }`
4. Frontend opens WebSocket to `signedUrl`, sends `conversation_initiation_client_data` with optional `conversation_config_override` containing the scenario's system prompt + first message
5. Browser mic → captures audio → sends as `{ user_audio_chunk: "<base64>" }` over WebSocket
6. ElevenLabs responds with audio chunks (prospect talking) + transcript events
7. Meanwhile, AssemblyAI dual-socket transcription runs exactly as it does today (REP + PROSPECT lanes) — the coaching panel updates live via `ep_analyze()`
8. On call end → `POST /api/train_end` saves everything with `disposition = 'train_voice'`

---

## 2. Salvage Map (from `cleancall-ai-main`)

### SALVAGE — adapt and port

| Source file | What to take | How it maps to Cell Coach |
|---|---|---|
| `src/lib/scenarios.ts` | `ImperfectionConfig` interface, `DifficultyConfig` structure, per-difficulty system prompts, objection lists | → Python dict `TRAIN_SCENARIOS` in `cellcoach.py` + JSON file `cc_scenarios.json`. Rewrite all prompts from cleaning-service context to code-violation/property-owner context using Cell Coach's existing `COACH_STAKES` types |
| `src/lib/scenarios.ts` | Scenario structure: id, name, description, difficulties (easy/medium/hard), each with systemPrompt + firstMessage + imperfections + trust params | → Same structure as Python dicts. Cut: `drillSections`, `idealFlow`, `rubricRules`, `previewConversation`, `estimatedDuration`, `objectives`, `tips` (all rep-training artifacts) |
| `src/app/api/calls/[callId]/credentials/route.ts` | The signed-URL pattern: `GET https://api.elevenlabs.io/v1/convai/conversation/get-signed-url?agent_id=...` with `xi-api-key` header → returns `{ signed_url }` | → Python function `_get_elevenlabs_signed_url()` in `cellcoach.py` using `urllib.request` (already in stdlib). ~15 lines |
| `src/lib/elevenlabs/connection.ts` | WebSocket protocol: connect to signed URL → send `conversation_initiation_client_data` with optional `conversation_config_override` → receive audio + transcript events. Message types: `user_audio_chunk`, `audio`, `transcript`, `conversation_initiation_metadata` | → JavaScript class `ElevenLabsConnection` in `cellcoach_ui.html`. Simplified from the repo's version — strip reconnection logic, trust meter updates, drill timer, upload progress. ~120 lines |
| `src/lib/analysis/feedback.ts` | `buildAnalysisPrompt()` structure — the idea of injecting scenario context, ideal flow, and rubric rules into the analysis prompt | → NOT ported directly. Cell Coach already has `ep_analyze()` with `OUTPUT_CONTRACT`. Instead, the training session passes scenario metadata as additional context into the existing `ep_analyze()` call, so the coach knows what scenario it's coaching against |

### CUT — do not port

| What | Why |
|---|---|
| Supabase auth, RLS, profiles, business accounts | Cell Coach has no auth — single-user local app |
| CSRF tokens, rate limiting | Local-only server on 127.0.0.1 |
| Skill levels, difficulty unlocking, `isDifficultyUnlocked()` | Rep gamification, not coach training |
| Trust meter UI (`TrustMeter.tsx`, `trustAnalyzer.ts`) | Visual rep feedback, not needed for coach eval |
| Drill mode / `DrillTimer`, `DrillSection`, section-specific prompts | Rep-focused drill practice |
| Recording upload to S3, `CallRecorder`, `uploadRecordingDirect` | Cell Coach records locally already |
| `AudioCapture`, `AudioPlayback` classes | Cell Coach already has mic capture via AssemblyAI WebSocket + browser audio playback |
| Business context injection, perfect call references | Enterprise features |
| Mock analysis fallback | Cell Coach requires a live OpenAI key |
| RouteLLM / Abacus routing | Cell Coach uses OpenAI directly |
| All React components, Next.js routing, Tailwind | Cell Coach is vanilla HTML/JS |

---

## 3. Build-New List

### Python backend (`cellcoach.py`) — ~200 lines added

1. **`cc_scenarios.json`** — New file. Scenario definitions for code-violation property owners, structured as:
   ```json
   {
     "code_violation_residential": {
       "id": "code_violation_residential",
       "name": "Code Violation — Residential Owner",
       "description": "Property owner with an active code violation...",
       "difficulties": {
         "easy": {
           "label": "Easy",
           "systemPrompt": "You are a property owner named Mike...",
           "firstMessage": "Hello?",
           "imperfections": { "fillerFrequency": "none", ... },
           "objections": ["scheduling"]
         },
         "medium": { ... },
         "difficult": { ... }
       }
     },
     "foreclosure_owner": { ... },
     "fire_damage_owner": { ... },
     "str_violation": { ... }
   }
   ```

   **Scenarios to write (matching `COACH_STAKES` keys):**
   - `code_violation_residential` — Standard code case (STR, LAND_USE, STRUCTURE, PERMIT, ABATEMENT)
   - `fire_damage_owner` — Crisis: post-fire, must use contractor-referral play only
   - `water_damage_owner` — Crisis: water damage, same crisis rules
   - `foreclosure_owner` — Crisis: auction date approaching, debt-payoff play
   - `str_violation` — STR-specific: Airbnb/VRBO host facing delisting + fines

   Each difficulty tier gets a unique prospect persona with imperfection config (fillers, interruptions, emotional volatility) adapted from the cleancall-ai patterns.

2. **`_load_scenarios()`** — Load `cc_scenarios.json`, analogous to existing `_load_personas()`. ~15 lines.

3. **`_get_elevenlabs_signed_url(agent_id, api_key)`** — Hits `https://api.elevenlabs.io/v1/convai/conversation/get-signed-url?agent_id=...` with `xi-api-key` header. Returns the signed WebSocket URL. Uses existing `_http()` helper. ~15 lines.

4. **`ep_train_start(d)`** — `POST /api/train_start`
   - Accepts: `{ scenario_id, difficulty, mode: "text"|"voice" }`
   - Validates scenario exists
   - Creates a call record in `calls` table with `disposition = 'train_text'` or `'train_voice'`, `play = scenario_id`
   - Returns: `{ session_id, scenario, difficulty_config }` (includes systemPrompt, firstMessage, imperfections)
   - ~30 lines

5. **`ep_train_chat(d)`** — `POST /api/train_chat` (text mode only)
   - Accepts: `{ session_id, rep_line, conversation_history, scenario_id, difficulty }`
   - Builds the prospect system prompt from the scenario config
   - Calls GPT-4o-mini as the prospect → generates next prospect line
   - Calls `ep_analyze()` with the growing transcript (existing coach engine)
   - Returns: `{ prospect_line, coach_analysis }`
   - ~50 lines

6. **`ep_train_credentials(session_id)`** — `GET /api/train_credentials?session_id=X` (voice mode only)
   - Loads ElevenLabs key from config (`elevenlabs_key`, `elevenlabs_agent_id`)
   - Calls `_get_elevenlabs_signed_url()`
   - Loads scenario config for this session
   - Returns: `{ signedUrl, systemPrompt, firstMessage }`
   - ~25 lines

7. **`ep_train_end(d)`** — `POST /api/train_end`
   - Accepts: `{ session_id, transcript, coach_log }`
   - Updates the call record with final transcript and coach log
   - Kicks off `_post_call_ai()` for summary generation (reuses existing code)
   - Returns: `{ ok: true }`
   - ~15 lines

8. **Route registration** — Add 4 new routes to `do_GET` and `do_POST` in the HTTP handler. ~15 lines.

9. **Config update** — Add `elevenlabs_key` and `elevenlabs_agent_id` to `cc_config.json` template in `_ensure_config()`. ~5 lines.

### HTML frontend (`cellcoach_ui.html`) — ~400 lines added

1. **Train Mode toggle** — A button/switch in the top bar. When active, replaces the lead-info panel (phone, owner, address, case_id) with the scenario picker. The coaching panel, transcript display, and staircase tracker stay identical. ~30 lines.

2. **Scenario picker panel** — Dropdown for scenario, radio buttons for difficulty (Easy/Medium/Hard), radio buttons for mode (Text/Voice), "Start Training" button. Displays the selected scenario's description and the prospect persona summary. ~60 lines.

3. **Text mode chat panel** — Replaces the dialer area when in text training mode. Shows the conversation as alternating `REP:`/`PROSPECT:` bubbles. Has a text input + send button at the bottom. On send:
   - Appends the rep line to the display
   - Calls `POST /api/train_chat`
   - Appends the prospect response
   - Updates the coaching panel with the coach analysis (same rendering as live calls)
   - ~100 lines

4. **Voice mode integration** — When voice training starts:
   - Calls `GET /api/train_credentials` to get the signed URL
   - Opens an `ElevenLabsConnection` WebSocket (new JS class, ~120 lines)
   - Browser mic captures audio, sends as base64 chunks to ElevenLabs
   - ElevenLabs sends back audio (played through speakers) + transcript entries
   - Transcript entries feed into `S.transcript` exactly like live AssemblyAI does today
   - The existing coaching pipeline (`askCoach()` → `ep_analyze()`) runs unchanged
   - ~120 lines for the ElevenLabs client class
   - ~30 lines for the voice mode UI wiring

5. **Session history markers** — Training sessions show in Past Calls with a tag: `[TRAIN-TEXT]` or `[TRAIN-VOICE]` next to the disposition. No new UI needed — just use the existing disposition display. ~10 lines.

---

## 4. ElevenLabs Agent Setup (Manual, One-Time)

Before voice mode works, you need an ElevenLabs Conversational AI agent:

1. Go to `elevenlabs.io` → Conversational AI → Create Agent
2. Set the agent's default system prompt to a generic placeholder (the real prompt will be overridden per-call via `conversation_config_override`)
3. In agent security settings, **enable overrides** — this allows the Cell Coach backend to inject scenario-specific prompts dynamically
4. Copy the Agent ID → put it in `cc_config.json` as `elevenlabs_agent_id`
5. Copy your API key → put it in `cc_config.json` as `elevenlabs_key`

The same agent handles all scenarios — the prompt is swapped per-call.

---

## 5. Config Changes

`cc_config.json` adds two keys:
```json
{
  "elevenlabs_key": "",
  "elevenlabs_agent_id": ""
}
```

Both are optional — text mode works without them (uses GPT-4o-mini only). Voice mode requires both.

---

## 6. Database Changes

No schema changes. Training sessions use the existing `calls` table:
- `disposition` = `'train_text'` or `'train_voice'` (distinguishes from real calls)
- `play` = scenario ID (e.g., `'code_violation_residential'`)
- `transcript`, `coach_log`, `summary`, `next_call_prep` — all populated normally

---

## 7. What the Coach Learns

After each training session, you review:
1. **The transcript** — Did the simulated prospect behave realistically?
2. **The coach's `say_next` responses** — Were they good advice? Did they follow the G.U.T.S. staircase? Did they respect crisis rules?
3. **The post-call summary** — Did `_post_call_ai()` produce useful prep for a hypothetical next call?

When you find weak spots, you:
- Edit the coaching persona (`GUTS_PERSONA` or custom) via the existing persona editor
- Adjust the `OUTPUT_CONTRACT` if the coach's JSON structure needs refinement
- Add/modify `COACH_STAKES` entries if the coach mishandled a violation type
- Tweak scenario prompts in `cc_scenarios.json` if the simulated prospect wasn't realistic enough

The training loop is: **run scenario → review coach output → edit persona/stakes → run again → verify improvement**.

---

## 8. Implementation Order

1. **Phase 1: Scenario engine + text mode** (~2 hours)
   - Write `cc_scenarios.json` with 5 scenarios × 3 difficulties
   - Add `_load_scenarios()`, `ep_train_start()`, `ep_train_chat()`, `ep_train_end()` to `cellcoach.py`
   - Add routes to HTTP handler
   - Add Train Mode toggle + scenario picker + text chat panel to `cellcoach_ui.html`
   - Test: run a text training session, verify coach responds, verify it saves to history

2. **Phase 2: Voice mode** (~2 hours)
   - Add `elevenlabs_key` and `elevenlabs_agent_id` to config
   - Add `_get_elevenlabs_signed_url()` and `ep_train_credentials()` to `cellcoach.py`
   - Write the `ElevenLabsConnection` JS class in `cellcoach_ui.html`
   - Wire voice mode: mic capture → ElevenLabs WebSocket → audio playback + transcript → coaching pipeline
   - Test: run a voice training session end-to-end

3. **Phase 3: Scenario prompts** (~1 hour)
   - Write the actual prospect persona prompts for each scenario/difficulty
   - Test each against the coach to verify realistic interactions
   - Iterate on prompts where the coach gives weak responses

---

## 9. What This Does NOT Include

- No analytics dashboard for training sessions
- No scoring/grading of the rep's performance
- No badges, skill unlocks, or gamification
- No team management or multi-user support
- No drill mode or timed sections
- No trust meter visualization
- No admin panel
- No billing integration
- No cloud deployment — runs locally only
