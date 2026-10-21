# Cell Coach — Dev Handoff
**Date:** 2026-07-17  
**Written by:** Claude (Sonnet 4.6) at end of session  
**For:** Next Claude thread to continue the build  

---

## SECURITY RULES — do not violate ever

- Keys stay on this machine. All API keys live in `C:\Users\Admin\data_center\data\cc_config.json` only. Never committed, never uploaded.
- Touch ONLY files inside `cell_coach/` for this task. Never import from `lead_machine` or `data/` folders.
- No pip installs. Python stdlib only (server runs on stdlib `http.server`).

---

## What Cell Coach is

A standalone cold-call AI coaching app. A Python HTTP server (`cellcoach.py`, port 5099) serves a single-file HTML/JS frontend (`cellcoach_ui.html`). When a rep is on a live call, it transcribes both sides via AssemblyAI (two WebSocket streams — REP from mic, PROSPECT from system audio/Stereo Mix), then calls GPT to generate real-time coaching on what to say next. Also has a training mode (text or ElevenLabs voice) where the rep practices against an AI prospect.

**Key files:**
- `C:\Users\Admin\data_center\cell_coach\cellcoach.py` — backend (~2,300+ lines after today's edits)
- `C:\Users\Admin\data_center\cell_coach\cellcoach_ui.html` — frontend (~2,700 lines)
- `C:\Users\Admin\data_center\cell_coach\cc_staircase.json` — G.U.T.S. exemplar library (built this session)
- `C:\Users\Admin\data_center\cell_coach\cc_personas.json` — coaching personas
- `C:\Users\Admin\data_center\cell_coach\cc_config.json` — local config (or `../data/cc_config.json`)
- `C:\Users\Admin\data_center\cell_coach\cellcoach.db` — SQLite DB

**Run:** `python cellcoach.py` from `C:\Users\Admin\data_center\cell_coach\`  
**Verify imports after any backend change:** `python -c "import cellcoach; print('OK')"`

---

## G.U.T.S. Staircase (the sales method the coach follows)

5 steps in order, never skipped:
1. **intro** — name + agency + specific observed fact + ONE hook question ("You aware of that?")
2. **agenda** — permission + roadmap + guilt-free exit ("It's okay to say no")
3. **qualification** — surface 4 pillars: NEED/GREED, MONEY, AUTHORITY, TIME + desired outcome
4. **commitment** — hypothetical close before presenting any play
5. **play_close** — present exactly ONE play, lock specific callback day/time

Plays: contractor referral, extension filing, lease option, cash buy, foreclosure debt-payoff.  
Firing a bad prospect (no money/authority/urgency) is a WIN — 75% of prospects don't qualify.

---

## What was built BEFORE today's session

1. **Phone Link audio capture** — replaced `getDisplayMedia` screen-share with Stereo Mix/loopback device picker using `getUserMedia`. Frontend has `#prospectDevSelect` dropdown + `enumerateAudioInputs()` function.

2. **State carry-over (C1)** — `S.lastAnalysis` stored in frontend, sent as `prior_state` on every analyze call. Backend had `_build_state_block(prior)` that injected a CURRENT CALL STATE block.

3. **G.U.T.S. exemplar library (C2)** — `cc_staircase.json` with real verbatim lines from conversations.json corpus. 5 steps, ~30 exemplars total. Intro sub-steps: standard, vacant, multi_violation, crisis.

4. **`_build_staircase_block(current_step)`** — backend injects only the ACTIVE step's exemplars into the prompt (not all steps).

5. **Eval harness** — `tests/eval_coach.py` (8 fixtures, gated behind `CC_EVAL=1 env flag`).

6. **Enterprise audit** — `ENTERPRISE_AUDIT.md` (35 findings, A-F categories).

---

## What was done TODAY (this session)

### Architectural decision
User and Claude agreed: the single monolithic `ep_analyze` call (one GPT-4o doing classification + signal detection + coaching all at once) is why the coach drifts and paraphrases instead of following exact exemplar structure. The fix is splitting into a **3-node pipeline**, exactly like voice agent architectures use. Each node has ONE job. The external API shape stays identical — `/api/analyze` still returns the same JSON.

### Backend changes made (PARTIALLY COMPLETE — see "What's Left")

**Added to `cellcoach.py`** — all new code was inserted between `_build_state_block` and `ep_analyze`:

**Helper functions:**
- `_parse_rep_identity(rep_identity)` → `(first_name, full_name, agency)` — parses "Sean with Risk & Compliance Bureau"
- `_play_to_intro_sub_step(play)` → `'crisis' | 'vacant' | 'standard'` — maps FIRE/FORECLOSURE → crisis, VACANT → vacant, else standard
- `_build_fact_line(ctx)` → builds the specific fact sentence for the opener from notes/address/play

**Node 0 — Opener (no LLM):**
- `_node_opener(d, c)` — deterministic template fill, no API call. Maps play type to intro sub-step, fills `{name}`, `{agency}`, `{fact}`, picks the right hook question. Returns full analysis dict.

**Node 1 — Stage Classifier (gpt-4o-mini):**
- `_NODE1_SYSTEM` — tight system prompt, one job: classify staircase_step + checklist + qualification_verdict
- `_node_classify(transcript, latest, prior, key)` — enforces monotonic checklist (never regress true → false), falls back to prior state on error

**Node 2 — Signal Detector (gpt-4o-mini):**
- `_NODE2_SYSTEM` — extracts objection, context_line, temperature, prospect_intel from latest prospect statement only
- `_node_signals(latest, transcript_tail, key)` — merges new intel with prior intel (never loses known facts)

**Node 3 — Coach (gpt-4o):**
- `_NODE3_CONTRACT` — strict instruction: "Pick ONE exemplar, copy its EXACT structure, swap only name/fact/agency. Do NOT blend examples. Do NOT paraphrase."
- `_node_coach(step, signals, ctx, rep_identity, persona_prompt, staircase_block, key)` — generates say_next, alt_suggestion, coach_type, next_action, summary, play

**`ep_analyze` rewritten** to:
1. If `opening=True` and no transcript → call `_node_opener(d, c)` — zero LLM calls
2. Otherwise: run Node 1 → Node 2 → Node 3, merge outputs into standard OUTPUT_CONTRACT JSON shape

**Also updated `_build_staircase_block`** label from "imitate the PATTERN/voice" to "pick the ONE closest match — copy its structure exactly" (this edit may not have been saved — verify).

### Frontend changes — NOT YET DONE

These are the two remaining frontend fixes that need to happen:

---

## WHAT'S LEFT — frontend fixes needed in `cellcoach_ui.html`

### Fix 1: Opener timing
**Problem:** `start()` calls `showOpeningLine()` at line 1282 immediately — before the prospect even picks up. The coach generates the full intro before anyone speaks.

**Correct G.U.T.S. flow:**
1. Call connects → show a STATIC card: `"Hey, is this {firstName}?"` (no API call — just fill name from form)
2. Prospect says "Hello?" or confirms → THEN call `showOpeningLine()` → backend's `_node_opener` generates the real intro line

**Changes needed:**

**A. S init (~line 1135)** — add two fields:
```javascript
let S = {... lastAnalysis:null, openerShown:false, recentCoachLines:[]};
```

**B. `start()` (~line 1282)** — replace `showOpeningLine()` with `showFirstMoveCard()`:
```javascript
// OLD:
showOpeningLine();
// NEW:
showFirstMoveCard();
```

Also add to the reset block in start() (~line 1274):
```javascript
S.openerShown = false; S.recentCoachLines = [];
```

**C. Add `showFirstMoveCard()` function** (add it right before `showOpeningLine()`):
```javascript
function showFirstMoveCard(){
  const owner = ($('owner')||{}).value || '';
  const firstName = owner.split(' ')[0].replace(/,/g,'') || '[Name]';
  showCoaching({
    say_next: `Hey, is this ${firstName}?`,
    alt_suggestion: `Or if someone else answers: "Hey, is ${firstName} available?"`,
    context_line: 'Call just connected — waiting for prospect to pick up.',
    coach_type: 'rapport',
    staircase_step: 'intro',
    qualification_verdict: 'undetermined',
    play: null,
    checklist: {intro:false, qualified:false, play_selected:false, committed:false},
    next_action: `Wait for ${firstName} to confirm, then the coach will generate your full intro.`,
    summary: 'Call connecting.',
    temperature: 'neutral',
    prospect_intel: {properties_owned:null, urgency:null, decision_maker:null, desired_outcome:null, stated_number:null}
  }, false, true);  // isStub=true — don't store as lastAnalysis
}
```

**D. `showCoaching(a, isInstant)` (~line 1566)** — add third param `isStub` and dedupe logic:

```javascript
function showCoaching(a, isInstant, isStub){
  // Dedupe suppression: skip rendering if >65% word overlap with recent coaching
  if(!isInstant && !isStub && a.say_next && S.recentCoachLines.length > 0){
    if(_isRepeatCoach(a.say_next)){
      // Still update checklist/intel but don't re-render the card
      if(a.checklist) renderChecklist(a.checklist);
      if(!isStub) S.lastAnalysis = a;
      return;
    }
  }
  // ... ALL existing showCoaching code stays unchanged ...
  // At the end of showCoaching, before the closing brace, add:
  if(!isInstant && !isStub && a.say_next){
    S.recentCoachLines.push(a.say_next);
    if(S.recentCoachLines.length > 3) S.recentCoachLines.shift();
  }
  // And modify the lastAnalysis storage line:
  if(!isInstant && !isStub && ct !== 'screening'){
    S.lastAnalysis = a;
  }
}
```

Add the dedupe helper function (add near top of script section):
```javascript
function _isRepeatCoach(text){
  const words = new Set(text.toLowerCase().split(/\s+/).filter(w => w.length > 3));
  if(words.size < 4) return false;
  for(const prev of S.recentCoachLines){
    const prevWords = prev.toLowerCase().split(/\s+/).filter(w => w.length > 3);
    const overlap = prevWords.filter(w => words.has(w)).length;
    if(overlap / Math.max(words.size, prevWords.length) > 0.65) return true;
  }
  return false;
}
```

**E. `openSocket` prospect branch (~line 1339)** — trigger opener on first real prospect line:
```javascript
// CURRENT:
} else if(!S.repSpoke){
  // Prospect just picked up ("Hello?") before the rep spoke...
}
// REPLACE WITH:
} else {
  if(!S.openerShown){
    S.openerShown = true;
    showOpeningLine();
  }
  if(S.repSpoke){
    S.lastProspect = m.transcript;
    checkInstant(m.transcript);
    scheduleAnalyze();
  }
}
```

**F. `openProspectSocket` (~line 1463)** — same trigger:
```javascript
// Find the equivalent !S.repSpoke block in openProspectSocket and apply same fix
```

**G. Training section (~line 2018)** — replace `showOpeningLine()` with `showFirstMoveCard()`:
```javascript
// OLD (line ~2018):
showOpeningLine();
// NEW:
showFirstMoveCard();
```

Also add to training resets (~line 2022):
```javascript
S.openerShown = false; S.recentCoachLines = [];
```

Then in the text training first_message block (~line 2057-2066), after `addTrainMsg('prospect', trainSession.first_message)`:
```javascript
if(!S.openerShown){ S.openerShown = true; showOpeningLine(); }
```

**H. `resetStaircase()` (~line 1632)** — add resets:
```javascript
S.openerShown = false;
S.recentCoachLines = [];
```

---

## Fix 2: Verify `_build_staircase_block` label update

In `cellcoach.py` around line 1155, the `_build_staircase_block` function has this line:
```python
"APPROVED EXAMPLES for this step (imitate the PATTERN/voice; swap in the real "
"name/agency/fact — never copy verbatim if details differ):",
```

Change it to:
```python
"APPROVED EXAMPLES for this step (pick the ONE closest match — copy its structure exactly, swap only name/fact/agency):",
```

This was attempted but may not have saved — verify by reading the file.

---

## Verify backend after any changes

```
cd C:\Users\Admin\data_center\cell_coach
python -c "import cellcoach; print('OK')"
```

---

## Architecture summary (final state once all done)

```
/api/analyze request
       │
       ├── opening=True, no transcript
       │       └── _node_opener()  ← NO LLM, template fill
       │
       └── ongoing transcript
               ├── Node 1: _node_classify()   ← gpt-4o-mini, ~100 tokens out
               │          staircase_step + checklist + qualification_verdict
               │          (monotonic rules enforced in code, not LLM)
               │
               ├── Node 2: _node_signals()    ← gpt-4o-mini, ~200 tokens out
               │          objection + context_line + temperature + prospect_intel
               │          (only looks at latest prospect statement, not full transcript)
               │
               └── Node 3: _node_coach()      ← gpt-4o, ~300 tokens out
                          say_next + alt_suggestion + coach_type + next_action + summary + play
                          (persona voice + STRICT: pick ONE exemplar, copy structure exactly)
```

Frontend:
- `showFirstMoveCard()` — static "Hey, is this {name}?" — shown at call start, NO API call
- `showOpeningLine()` — fires only after first real prospect line (`S.openerShown` gate)
- `_isRepeatCoach()` — word-overlap dedupe, suppresses redundant coaching cards
- `S.recentCoachLines[]` — rolling buffer of last 3 say_next outputs

---

## Other context

- **`cc_staircase.json`** has intro sub-steps: standard, vacant, multi_violation, crisis. All exemplars are real verbatim from conversations.json corpus or owner-verbatim from chat. Some commitment/close are pattern-derived (labeled).
- **Training mode** works fully — text and ElevenLabs voice. The training path also sends `prior_state` on every analyze call.
- **The `sean_direct` persona** is NOT in DEFAULT_PERSONAS (which only has `cardone`) — it may be in `cc_personas.json` on disk. The GUTS_PERSONA constant in cellcoach.py is the canonical one but may not be registered under `sean_direct` key. Check `cc_personas.json` if persona lookups fail.
- **Windows machine**, Python 3.14.4, use `python` not `python3`.
- **Bash sandbox is separate from the Windows machine** — use Read/Edit/Write tools for file changes, not bash, since bash runs in a Linux sandbox that can't write to the Windows paths.

---

## Exact line numbers (approximate — may drift after edits)

| Symbol | ~Line in cellcoach.py |
|---|---|
| `COACH_STAKES` | 210 |
| `PERSONAS / GUTS_PERSONA` | 237 |
| `OUTPUT_CONTRACT` | 393 |
| `_load_staircase()` | 44 |
| `_build_staircase_block()` | 1143 |
| `_build_state_block()` | 1167 |
| All new node functions | 1200–1430 (approx, after today's inserts) |
| `ep_analyze()` (rewritten) | ~1430+ |

| Symbol | ~Line in cellcoach_ui.html |
|---|---|
| `S` init | 1135 |
| `start()` | 1270 |
| `showOpeningLine()` | 1687 |
| `analyze()` | 1710 |
| `showCoaching()` | 1566 |
| `resetStaircase()` | 1632 |
| Training `startTraining()` | ~1960 |
| Training first_message block | ~2055 |
| `openSocket` prospect branch | 1339 |
| `openProspectSocket` | 1449 |
