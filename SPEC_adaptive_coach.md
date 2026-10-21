# Cell Coach — Adaptive Training System

## Spec for Sonnet to execute

**Goal:** Make the coach learn from the rep's past sessions so coaching advice on both training AND live calls targets the rep's actual weaknesses, not generic advice. The rep can also inject manual coaching rules that override or supplement auto-detected patterns.

**Security rules (carry forward):** Keys stay on this machine. All API keys live in `C:\Users\Admin\data_center\data\cc_config.json` only. Never committed, never uploaded. Touch ONLY files inside `cell_coach/` for this task. Never import from `lead_machine` or `data/` folders (reading the config file is fine — that's already happening).

**Architecture constraints:** Python stdlib only (no pip installs). Single-file HTTP server on port 5099. SQLite DB at `cell_coach/cellcoach.db`. Frontend is a single HTML file `cellcoach_ui.html`. GPT-4o-mini for all LLM calls via `_http()` helper.

---

## 1. Database Schema Changes

File: `cellcoach.py`, inside `_ensure_db()`

### 1a. New table: `session_scores`

Stores the graded rubric for every completed session (training AND live calls).

```sql
CREATE TABLE IF NOT EXISTS session_scores(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id INTEGER NOT NULL,          -- FK to calls.id
    scored_at TEXT NOT NULL,            -- ISO timestamp
    is_training INTEGER DEFAULT 0,     -- 1 = training session, 0 = live call
    scenario_id TEXT DEFAULT '',        -- scenario_id if training, '' if live
    difficulty TEXT DEFAULT '',         -- easy/medium/difficult if training
    overall_grade TEXT DEFAULT '',      -- A/B/C/D/F letter grade
    opener_score INTEGER DEFAULT 0,    -- 1-10
    discovery_score INTEGER DEFAULT 0, -- 1-10
    objection_handling_score INTEGER DEFAULT 0, -- 1-10
    pitch_timing_score INTEGER DEFAULT 0,       -- 1-10
    tone_score INTEGER DEFAULT 0,      -- 1-10
    close_score INTEGER DEFAULT 0,     -- 1-10
    weaknesses TEXT DEFAULT '[]',      -- JSON array of string labels, e.g. ["pitches_too_early", "weak_trust_answer"]
    strengths TEXT DEFAULT '[]',       -- JSON array of string labels
    notes TEXT DEFAULT '',             -- free-text AI commentary
    raw_json TEXT DEFAULT '{}'         -- full scorer output for future use
)
```

### 1b. New table: `rep_profile`

The aggregated weakness profile + manual coaching rules. Single row (rep_id = 1 for now — only one rep).

```sql
CREATE TABLE IF NOT EXISTS rep_profile(
    id INTEGER PRIMARY KEY DEFAULT 1,
    updated_at TEXT DEFAULT '',
    sessions_analyzed INTEGER DEFAULT 0,
    avg_overall TEXT DEFAULT '',            -- running average letter grade
    weak_categories TEXT DEFAULT '[]',      -- JSON: [{"category":"objection_handling","avg_score":4.2,"trend":"declining","detail":"Fumbles 'how do you get paid' and trust objections consistently"}]
    strong_categories TEXT DEFAULT '[]',    -- JSON: same shape
    recurring_habits TEXT DEFAULT '[]',     -- JSON: ["pitches before qualifying","drops energy mid-call","strong openers"]
    manual_rules TEXT DEFAULT '[]',         -- JSON: ["always push contractor-referral on fire","remind me to slow down","never suggest lowball framing"]
    last_5_grades TEXT DEFAULT '[]'         -- JSON: ["B","C","B","A","C"] most recent first
)
```

### 1c. Alter existing `calls` table

Add column to link to the score (or just query by call_id — no alter needed). BUT add a column to flag whether post-session scoring has run:

```sql
ALTER TABLE calls ADD COLUMN scored INTEGER DEFAULT 0
```

Use try/except like the existing ALTER patterns so it's safe to re-run.

---

## 2. Post-Session Scorer

File: `cellcoach.py`

### 2a. New function: `_score_session(call_id)`

Called in a background thread after every session ends — both training (`ep_train_end`) and live calls (`ep_call_end`). Runs AFTER the existing `_post_call_ai()` so the summary is already written.

**Logic:**

1. Read the call record from `calls` table (transcript, play, disposition, coach_log).
2. If transcript is empty or < 4 lines, skip (no meaningful session to score).
3. Determine `is_training` from disposition (starts with `train_`).
4. Call GPT-4o-mini with a scoring prompt (see below).
5. Parse the JSON response.
6. INSERT into `session_scores`.
7. UPDATE `calls SET scored = 1 WHERE id = ?`.
8. Call `_rebuild_profile()` to update the aggregate.

**Scoring prompt (system):**

```
You are a sales call performance scorer for a cold-call coaching system. You grade the REP's performance on a training or live call transcript.

Score each category 1-10:
- opener: Did the rep match tone to severity? Was the intro natural and permission-based?
- discovery: Did they ask qualifying questions before proposing solutions? Did they surface the prospect's situation, urgency, decision-maker, and desired outcome?
- objection_handling: When the prospect pushed back, did the rep acknowledge, isolate, and re-close? Or did they panic, over-explain, or cave?
- pitch_timing: Did they wait until qualification was complete to propose a play? Or did they jump to solutions too early?
- tone: Was the rep natural, conversational, and appropriately matched to the prospect's emotional state? Or robotic/scripted/too aggressive?
- close: Did they lock a specific next step with a date/time? Or leave it vague?

Also identify:
- weaknesses: specific bad habits observed (list as short labels)
- strengths: specific good habits observed (list as short labels)
- overall_grade: A (excellent) / B (solid) / C (needs work) / D (significant issues) / F (failed basic steps)
- notes: 2-3 sentence summary of what the rep did well and what they need to work on

Respond ONLY with JSON:
{
  "opener_score": int,
  "discovery_score": int,
  "objection_handling_score": int,
  "pitch_timing_score": int,
  "tone_score": int,
  "close_score": int,
  "overall_grade": "A|B|C|D|F",
  "weaknesses": ["label1", "label2"],
  "strengths": ["label1", "label2"],
  "notes": "string"
}
```

**User prompt:**

```
CALL TYPE: {training|live}
PLAY: {play}
DISPOSITION: {disposition}
DURATION: {duration}s

TRANSCRIPT:
{transcript (last 6000 chars)}

Score the REP's performance. JSON only.
```

### 2b. Threading

Same pattern as `_post_call_ai`:

```python
threading.Thread(target=_score_session, args=(call_id,), daemon=True).start()
```

Add this call at the end of both:
- `ep_train_end()` — after the existing `_post_call_ai` thread fires
- `ep_call_end()` — after the existing `_post_call_ai` thread fires

Use a small `time.sleep(3)` at the start of `_score_session` so the summary finishes first (they're both async, order doesn't actually matter, but it avoids rate-limit collisions on the OpenAI key).

---

## 3. Profile Rebuilder

File: `cellcoach.py`

### 3a. New function: `_rebuild_profile()`

Called after every new score is inserted. Reads ALL rows from `session_scores` and rebuilds the single `rep_profile` row.

**Logic:**

1. `SELECT * FROM session_scores ORDER BY id DESC` — get all scores.
2. Compute per-category averages: `avg(opener_score)`, `avg(discovery_score)`, etc.
3. Identify weak categories: any category averaging < 6.0.
4. Identify strong categories: any category averaging >= 8.0.
5. Aggregate weaknesses/strengths labels across all sessions — count frequency. Top 5 recurring ones become `recurring_habits`.
6. Compute trend per category: compare avg of last 5 sessions vs. avg of all sessions. If last-5 avg is lower → "declining", higher → "improving", within 1 point → "stable".
7. Last 5 overall grades.
8. Read existing `manual_rules` from `rep_profile` (preserve them — they're user-edited).
9. UPSERT the `rep_profile` row (INSERT OR REPLACE with id=1).

This is pure Python + SQLite, no LLM call needed.

---

## 4. Coach Memory Injection

File: `cellcoach.py`

### 4a. New function: `_get_profile_context()`

Returns a string block that gets prepended to the coach's system prompt on every call (training and live).

**Logic:**

1. Read `rep_profile` row.
2. If `sessions_analyzed == 0`, return empty string (no data yet).
3. Format:

```
REP PERFORMANCE PROFILE (based on {N} scored sessions):
Overall trend: {avg_overall} (last 5: {grades})

WEAK AREAS (prioritize coaching these):
{for each weak category: "- {category}: avg {score}/10, {trend}. {detail}"}

RECURRING HABITS:
{for each habit: "- {habit}"}

STRONG AREAS (leverage these, don't over-coach):
{for each strong: "- {category}: avg {score}/10"}

REP'S CUSTOM COACHING RULES (always follow these):
{for each manual_rule: "- {rule}"}

Use this profile to personalize your SAY THIS advice. When the rep is about to make a mistake they've made before, call it out preemptively. When they're in a strong area, trust them and focus coaching elsewhere.
```

### 4b. Inject into `ep_analyze()`

In `ep_analyze()`, after building `sys_prompt` from the persona + OUTPUT_CONTRACT, append the profile:

```python
profile_ctx = _get_profile_context()
if profile_ctx:
    sys_prompt += "\n\n" + profile_ctx
```

This covers:
- Live call coaching (uses `ep_analyze`)
- Training opening line (uses `ep_analyze` with `opening=True`)

### 4c. Inject into `ep_train_chat()`

Same injection into the coach analysis step (the second LLM call in `ep_train_chat`, around line 691):

```python
profile_ctx = _get_profile_context()
if profile_ctx:
    sys_prompt += "\n\n" + profile_ctx
```

---

## 5. Manual Rules Management

File: `cellcoach.py`

### 5a. New endpoint: `GET /api/profile`

Returns the full rep profile for the UI to display.

```python
def ep_get_profile():
    con = db()
    row = con.execute("SELECT * FROM rep_profile WHERE id=1").fetchone()
    con.close()
    if not row:
        return {"profile": None}
    return {"profile": {
        "sessions_analyzed": row["sessions_analyzed"],
        "avg_overall": row["avg_overall"],
        "weak_categories": json.loads(row["weak_categories"] or "[]"),
        "strong_categories": json.loads(row["strong_categories"] or "[]"),
        "recurring_habits": json.loads(row["recurring_habits"] or "[]"),
        "manual_rules": json.loads(row["manual_rules"] or "[]"),
        "last_5_grades": json.loads(row["last_5_grades"] or "[]"),
        "updated_at": row["updated_at"],
    }}
```

### 5b. New endpoint: `POST /api/profile/rules`

Accepts `{"rules": ["rule1", "rule2", ...]}` — replaces the manual rules list.

```python
def ep_update_rules(d):
    rules = d.get("rules") or []
    if not isinstance(rules, list):
        return {"error": "rules must be a list"}
    rules = [r.strip() for r in rules if isinstance(r, str) and r.strip()]
    con = db()
    con.execute("UPDATE rep_profile SET manual_rules=?, updated_at=? WHERE id=1",
                (json.dumps(rules), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    if con.total_changes == 0:
        con.execute("INSERT INTO rep_profile(id, manual_rules, updated_at) VALUES(1,?,?)",
                    (json.dumps(rules), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    con.commit()
    con.close()
    return {"ok": True}
```

### 5c. New endpoint: `POST /api/profile/weaknesses/edit`

Lets the rep review auto-detected weaknesses and remove/edit them.

```python
def ep_edit_weaknesses(d):
    weak = d.get("weak_categories")
    if weak is None:
        return {"error": "weak_categories required"}
    con = db()
    con.execute("UPDATE rep_profile SET weak_categories=?, updated_at=? WHERE id=1",
                (json.dumps(weak), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    con.commit()
    con.close()
    return {"ok": True}
```

### 5d. New endpoint: `GET /api/profile/scores`

Returns the last N session scores for the progress dashboard.

```python
def ep_get_scores(qs):
    limit = int((qs.get("limit", ["20"])[0] or "20"))
    con = db()
    rows = con.execute("SELECT * FROM session_scores ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    con.close()
    return {"scores": [dict(r) for r in rows]}
```

### 5e. Route registration

Add to `do_GET`:
```python
if p == "/api/profile":
    return self._s(ep_get_profile())
if p == "/api/profile/scores":
    return self._s(ep_get_scores(parse_qs(urlparse(self.path).query)))
```

Add to `do_POST`:
```python
if path == "/api/profile/rules":
    return self._s(ep_update_rules(d))
if path == "/api/profile/weaknesses":
    return self._s(ep_edit_weaknesses(d))
```

---

## 6. Frontend — Progress Dashboard

File: `cellcoach_ui.html`

### 6a. New topbar button

Add next to the existing "Coach Training" and "Train Mode" buttons:

```html
<button class="ghost-btn" onclick="openProfileModal()">📊 My Progress</button>
```

### 6b. New modal: `#profileModal`

Same pattern as `personaModal` and `histModal`. Contains:

**Section 1: Overall Stats**
- Sessions analyzed count
- Average grade (big letter)
- Last 5 grades as colored pills
- Updated timestamp

**Section 2: Weak Areas (editable)**
- Each weak category shown as a row: category name, avg score, trend arrow (↑↓→), detail text
- Each row has a ✕ button to remove it (calls `/api/profile/weaknesses/edit` with the updated list)
- Red/yellow background depending on severity

**Section 3: Strong Areas**
- Same layout but green, read-only

**Section 4: Recurring Habits**
- Simple list of habit labels

**Section 5: My Coaching Rules (editable)**
- Textarea or list of editable rules
- "Add rule" button
- Each rule has a ✕ to remove
- Save button calls `/api/profile/rules`
- Placeholder examples: "always push contractor-referral on fire damage", "remind me to slow down before objection handling"

**Section 6: Session History**
- Table of last 20 scored sessions: date, scenario/phone, difficulty, overall grade, category scores as a mini bar chart or number row
- Each row expandable to show the scorer's notes

### 6c. CSS

Follow existing patterns: `var(--panel)`, `var(--line)`, `var(--txt)`, `var(--dim)`, etc. Grade colors:
- A: `var(--good)` (#3fb950)
- B: `var(--acc)` (#4cc2ff)
- C: `var(--gold)` (#d29922)
- D: `var(--bad)` (#f85149)
- F: `var(--red)` (#da3633)

### 6d. JS functions

```javascript
async function openProfileModal() { ... }  // fetch /api/profile + /api/profile/scores, render
function closeProfileModal() { ... }
async function saveManualRules() { ... }    // POST /api/profile/rules
async function removeWeakness(idx) { ... }  // POST /api/profile/weaknesses
```

---

## 7. Adaptive Scenario Selection (optional, lower priority)

Once the profile exists, add a "Recommended" badge to the scenario picker in Train Mode:

In `renderTrainScenarioPicker()`, after loading scenarios, fetch `/api/profile`. If `weak_categories` includes `objection_handling`, badge the scenarios that have hard objection tiers. If `pitch_timing` is weak, badge scenarios where the prospect punishes early pitching.

This is cosmetic — just a visual hint. The rep still picks manually.

---

## 8. Backfill Existing Sessions

### 8a. New endpoint: `POST /api/profile/backfill`

Scores all unscored calls that have transcripts:

```python
def ep_backfill_scores():
    con = db()
    rows = con.execute("SELECT id FROM calls WHERE scored=0 AND transcript!='' AND transcript IS NOT NULL").fetchall()
    con.close()
    count = 0
    for row in rows:
        threading.Thread(target=_score_session, args=(row["id"],), daemon=True).start()
        count += 1
        time.sleep(1)  # rate limit spacing
    return {"ok": True, "queued": count}
```

### 8b. UI trigger

Add a "Score past sessions" button in the profile modal that calls this endpoint. Show a confirmation first ("This will use ~{N} API calls to GPT-4o-mini, ~$0.01 each").

---

## 9. File Change Summary

| File | Changes |
|------|---------|
| `cellcoach.py` | New tables in `_ensure_db()`. New functions: `_score_session()`, `_rebuild_profile()`, `_get_profile_context()`. New endpoints: `ep_get_profile()`, `ep_update_rules()`, `ep_edit_weaknesses()`, `ep_get_scores()`, `ep_backfill_scores()`. Modified: `ep_analyze()` and `ep_train_chat()` to inject profile. Modified: `ep_train_end()` and `ep_call_end()` to trigger scoring. New routes in `do_GET` and `do_POST`. |
| `cellcoach_ui.html` | New topbar button. New `#profileModal` with all sections. New CSS for grade colors, score rows, rule editor. New JS functions for profile CRUD. |
| `cc_scenarios.json` | No changes. |
| `cc_config.json` | No changes. |

---

## 10. Testing Checklist

1. Start server, verify no crash (new tables created).
2. Run a text training session end-to-end. Verify `session_scores` row appears after ~5s.
3. Run a second session. Verify `rep_profile` row exists and `sessions_analyzed = 2`.
4. Open "My Progress" modal — verify stats, weak areas, and scores render.
5. Add a manual rule ("always push contractor-referral on fire damage"). Save. Start a new training session on a fire scenario. Verify the coach's SAY THIS advice references the rule.
6. Start a live call coaching session. Verify the coach prompt includes the profile context (check server logs or coach behavior).
7. Remove a weakness from the profile. Verify it persists after page reload.
8. Click "Score past sessions" if there are unscored calls. Verify they get scored.
9. `python3 -m py_compile cellcoach.py` passes.
10. `node --check` on the HTML (or just open in browser with no console errors).

---

## 11. What NOT to Change

- Do not modify `cc_scenarios.json` structure.
- Do not change the ElevenLabs voice/WebSocket code.
- Do not change the AssemblyAI transcription code.
- Do not add pip dependencies.
- Do not change the persona system — profile injection is additive (appended to whatever persona is active).
- Do not change the `OUTPUT_CONTRACT` JSON schema — the frontend depends on it.
- Keep the `TRAIN_GUARDRAILS` block — it's for the prospect LLM, not the coach.
