# Cell Coach — Custom Play Mode (Spec)

**Date:** 2026-07-17
**Author:** Claude (Opus) — design handoff
**For:** Next instance to implement
**Status:** Approved scope, not yet built

---

## Goal (one line)

Add a single **"✦ Custom"** play that lets the rep describe *any* goal in a short questionnaire — B2B lead-gen, a landlord, a note deal, even a personal call — and have the coach run the chosen methodology (GUTS or Cardone) aligned to that goal, without any of the property/code-enforcement scaffolding.

---

## Why this is a clean addition (grounded in current code)

Today a single `play` value drives the whole coaching stack:

- `COACH_STAKES[play]` → the stakes text + crisis flag (`cellcoach.py` ~L210)
- `_play_to_intro_sub_step(play)` → intro posture (crisis/vacant/standard)
- `_build_fact_line(ctx)` → the opener's specific fact sentence
- `_build_staircase_block(step)` → injects verbatim property exemplars from `cc_staircase.json`
- `_node_coach(...)` → gets `ctx`, `persona_prompt`, `staircase_block`

All four are property-bound. Custom mode adds a **parallel branch** that keeps this untouched for the existing 11 plays and substitutes a **questionnaire-derived context** when `play == "CUSTOM"`.

**The core problem to solve:** the GUTS persona and every exemplar are real-estate-specific. For a non-property goal they mislead. Custom mode must run the *method* (staircase, moves, psychology, close discipline) with the real-estate *content* removed and replaced by the rep's answers.

---

## UX

### Entry point
Add to the setup `#play` dropdown (`cellcoach_ui.html` ~L369):
```html
<option value="CUSTOM">✦ Custom (any goal)</option>
```

### Behavior on select
When `#play` value === `CUSTOM`:
- **Hide** the property fields (`#owner`, `#caseId`, `#address`) — they're meaningless here.
- **Show** a `#customPanel` div with the questionnaire below.
- The methodology radio sets `personaId` directly (overrides the persona picker for this call).

### The questionnaire (`#customPanel`)
Six fields. First three required, rest optional. Kept short on purpose — this is the structure that makes the free-form intent usable.

| # | Field | id | Type | Required | Feeds |
|---|-------|-----|------|----------|-------|
| 1 | Methodology | `cpMethod` | radio: GUTS / Cardone | yes | `persona_id` |
| 2 | Who are you calling? | `cpWho` | text | yes | counterpart identity |
| 3 | What's the win for THIS call? | `cpGoal` | text | yes | the close/target |
| 4 | Your angle — why should they care? | `cpAngle` | text | no | the hook / value |
| 5 | Likely pushback | `cpPushback` | text | no | pre-loaded objection |
| 6 | Register | `cpTone` | select: Professional / Casual / Warm | no (default Professional) | tone control |

Placeholders should teach by example, e.g.:
- Who: `"a PE firm partner who sources distressed businesses"`
- Win: `"get them to send me their distressed-business leads"`
- Angle: `"I bring them clean off-market deals they don't have to dig for"`
- Pushback: `"we already have a sourcing team"`

### Payload
On start, when play is CUSTOM, send a `custom` object on **every** `/api/analyze` and `/api/train/*` call:
```js
custom: {
  method:   cpMethod.value,      // "guts" | "cardone"
  who:      cpWho.value,
  goal:     cpGoal.value,
  angle:    cpAngle.value,
  pushback: cpPushback.value,
  tone:     cpTone.value || "Professional"
}
```
Also set `personaId = (cpMethod === 'cardone') ? 'cardone' : 'guts_general'` for this session.

---

## Backend changes (`cellcoach.py`)

### 1. New stakes entry (nominal — real work is the branch)
```python
COACH_STAKES["CUSTOM"] = ("(custom goal — see custom context)", False)
```

### 2. Domain-general personas
The existing GUTS persona is property-bound. Add **method-only** variants that carry the staircase/moves/psychology with NO real-estate framing.

**v1 (fast):** a runtime **domain-override block** prepended to the existing persona when `play == CUSTOM`, e.g.:
```
DOMAIN OVERRIDE — IGNORE any real-estate / code-violation framing in the
doctrine below. This call is NOT about property. Apply ONLY the METHOD
(staircase, moves, psychology, close discipline) to the situation described
in CUSTOM CONTEXT. The rep's identity, goal, and the counterpart come from
CUSTOM CONTEXT, not from any property scenario.
```
This reuses the method content and ships in hours.

**v2 (quality):** author `guts_general` and `cardone_general` entries in `cc_personas.json` — clean, method-pure, no override needed. Recommended once v1 is validated.

### 3. Custom context builder
New helper:
```python
def _build_custom_ctx(custom):
    """Build the coach ctx from the rep's questionnaire instead of COACH_STAKES."""
    who   = (custom.get("who") or "the person on the other end").strip()
    goal  = (custom.get("goal") or "advance the relationship").strip()
    angle = (custom.get("angle") or "").strip()
    tone  = (custom.get("tone") or "Professional").strip()
    push  = (custom.get("pushback") or "").strip()
    return {
        "play": "CUSTOM",
        "custom_mode": True,
        "counterpart": who,
        "goal_for_this_call": goal,
        "your_angle": angle or "(let the questions surface it)",
        "register": tone,
        "anticipated_pushback": push or "(none stated)",
        "stakes_for_this_play": f"Custom goal: {goal}. Angle: {angle or 'TBD'}.",
        "crisis_situation": False,
        "crisis_rule": "N/A — custom goal, use judgment on tone.",
    }
```

### 4. Branch `ep_analyze` (and the opener + `ep_train_chat` ctx build)
At the top of the ongoing-pipeline section:
```python
custom = d.get("custom") or {}
is_custom = (play == "CUSTOM") and bool(custom)

if is_custom:
    ctx = _build_custom_ctx(custom)
    rep_identity = custom.get("who_am_i") or "the caller"   # optional field, else generic
    staircase_block = ""   # NO property exemplars in custom mode
else:
    ctx = { ...existing property ctx... }
    staircase_block = _build_staircase_block(current_step)
```
- **Persona:** `persona_id` arrives as `guts_general` / `cardone_general` (v2) or `guts` / `cardone` + override block (v1).
- **Node 1 (classifier):** unchanged — the staircase steps (intro→agenda→qualify→commit→close) are already domain-general. It classifies fine on any transcript.
- **Node 2 (signals):** unchanged — objection/intel extraction is generic.
- **Node 3 (coach):** gets custom `ctx`, general persona, empty `staircase_block`. The method carries it.
- **Node 3 gate:** unchanged, still applies.

### 5. Opener for custom (`_node_opener`)
When custom, skip `_build_fact_line` / property fact map. Generate a generic curiosity/authority opener from `angle` + `who`:
```python
if (d.get("play") == "CUSTOM") and d.get("custom"):
    cu = d["custom"]
    say_next = f"Hey — is this {cu.get('who','you')}? ..."  # method-appropriate greet + angle hook
```
Keep it a template (no LLM) so the opener stays instant.

---

## Frontend changes (`cellcoach_ui.html`)

1. Add the `CUSTOM` `<option>` (setup dropdown ~L369).
2. Add `#customPanel` markup with the six fields (hidden by default).
3. `#play` change handler: toggle property fields vs `#customPanel`; when CUSTOM, set `personaId` from `cpMethod`.
4. In `start()` and `startTraining()`: if play is CUSTOM, validate the 3 required fields before allowing start; build the `custom` payload object into `S.custom`.
5. In `analyze()`, `showOpeningLine()`, and `sendTrainChat()`: include `custom: S.custom` in the body when set.
6. Persist custom answers to `localStorage` (like `saveCtx`) so a day's intent survives a refresh.

---

## Methodology mapping

- **GUTS** → staircase + moves + doctor-not-salesman posture (already the house style).
- **Cardone** → the `cardone` persona (already in `DEFAULT_PERSONAS`). For custom, its general variant. Cardone leans harder/faster close, more assumptive — the persona already encodes this; just needs the property framing stripped the same way.

The methodology radio is the ONLY thing that swaps the persona. Everything else (staircase mechanics, gate, dedupe, cooldown) is method-agnostic and untouched.

---

## Scope discipline (v1 vs later)

**v1 — ship this:**
- CUSTOM option + questionnaire + payload
- `_build_custom_ctx` + runtime domain-override block
- Custom branch in `ep_analyze`, `_node_opener`, `ep_train_chat`
- Empty staircase_block for custom
- localStorage persistence

**Later — quality passes:**
- `guts_general` / `cardone_general` personas in `cc_personas.json` (drop the override)
- A tiny library of general exemplars per methodology (optional — method alone works without them)
- Voice dictation for the questionnaire (reuse AssemblyAI mic path)

---

## Verification

1. `python -c "import cellcoach; print('OK')"` after backend edits.
2. Custom text-training run with goal "get the date" using GUTS — confirm the coach never references property/code/city, follows the staircase, and coaches toward the stated win.
3. Same run with Cardone selected — confirm posture shifts (harder/assumptive close) while still domain-clean.
4. A property play (e.g. STR) run afterward — confirm the existing path is byte-for-byte unchanged (no regression).
5. Node 3 gate still fires on no-change turns in custom mode (watch the "holding current coaching" summary).

---

## Files touched

- `cellcoach.py` — `COACH_STAKES`, `_build_custom_ctx` (new), `_node_opener` branch, `ep_analyze` branch, `ep_train_chat` ctx branch, optional persona override block.
- `cellcoach_ui.html` — dropdown option, `#customPanel`, change handler, `start()`/`startTraining()` validation + payload, body inclusion in the three call sites, localStorage.
- `cc_personas.json` — (v2 only) `guts_general`, `cardone_general`.

No new dependencies. Stdlib only. Keys stay in `data/cc_config.json`.
