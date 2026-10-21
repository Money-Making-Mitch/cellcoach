# SPEC — Cell Coach: State Carry-Over + G.U.T.S. Exemplar Library
**For:** Claude Sonnet (implementer) · **Author:** Opus (plan) · **Date:** 2026-07-17
**Scope:** Two coupled features — C1 (per-turn state carry-over) and C2 (staircase exemplar library extracted from `conversations.json`, injected per active step). Nothing else. Do NOT touch Twilio, Phone Link, recording, scoring, or personas beyond what's listed here.

## Hard rules (from project owner — do not violate)
- Touch ONLY files inside `cell_coach/`. Never import from `lead_machine` or `data/` folders.
- API keys live ONLY in `C:\Users\Admin\data_center\data\cc_config.json` (or `cell_coach/cc_config.json`). Never commit, never upload, never print keys.
- No pip installs. Python stdlib only (the server already runs on stdlib `http.server`).
- Before editing, READ the actual function — line numbers below are anchors from 2026-07-17 and may drift.
- After each code change, verify the module imports: `python3 -c "import cellcoach; print('OK')"`. Do NOT assume; run it.

## Files you will touch
1. `cell_coach/conversations.json` — SOURCE DATA (read-only). Claude conversation export, ~520k tokens, single-line JSON. Do NOT try to Read it whole; parse it with a script (Step 1).
2. `cell_coach/cc_staircase.json` — NEW. The exemplar library you generate.
3. `cell_coach/cellcoach.py` — backend: `ep_analyze` + new loader + OUTPUT_CONTRACT.
4. `cell_coach/cellcoach_ui.html` — frontend: `analyze()`, `showOpeningLine()`, `showCoaching()`, state object `S`, and the training-mode analyze path.
5. `cell_coach/tests/` — NEW. Extraction sanity check + a small eval (Step 6).

---

## STEP 1 — Parse conversations.json and pull raw G.U.T.S. dialogue
`conversations.json` is an array of conversation objects. Shape (confirmed):
```
[ { "name": str, "summary": str, "chat_messages": [
      { "sender": "human"|"assistant", "text": str,
        "content": [ {"type":"text","text":str}, ... ], "attachments": [...] }, ... ] }, ... ]
```
The relevant conversations are named like **"Claude Diamond-G.U.T.S."**, **"Grant Cardone"**, **"Grant Cardone Cold Call Coach Prompt"**. The dialogue exemplars look like `"Mike, this is Claude..."`, `"You aware of that situation?"`, `"Listen, my name is Claude..."`, etc.

Write `tests/extract_dialogue.py` (stdlib `json` only) that:
- Loads conversations.json, iterates conversations, concatenates each message's `text` (fall back to joining `content[].text` where `type=="text"`).
- Writes `tests/guts_corpus.txt` — one file with `## <conversation name>` headers and the full human+assistant text under each, so you (Sonnet) can then read that corpus in slices with the Read tool. This is how you get around the file being too big to read directly.
- Print per-conversation message counts so you can confirm you captured the G.U.T.S. ones.

Then Read `guts_corpus.txt` in offset/limit slices and mine the actual exemplars. Use the OWNER'S real examples verbatim where they exist (he pasted canonical intros in chat — see his 6 intro examples: Mike/code-violations, Robert/structure, David/vacant, Jennifer/multi-violation, Robert/foreclosure-crisis, Sarah/unpermitted). Match their pattern for the other steps.

**Coverage honesty:** if the corpus doesn't contain clean exemplars for a given sub-step (likely for Commitment/Close), mark that sub-step `"source": "pattern-derived"` in the JSON rather than inventing a fake transcript quote. Disclose which sub-steps are derived vs. lifted in the completion notes.

---

## STEP 2 — Build cc_staircase.json (the exemplar library)
Structure — the coach loads ONLY the active step's block each turn, so keep each exemplar tight (2-3 per sub-step):

```json
{
  "version": 1,
  "steps": {
    "intro": {
      "label": "Intro (Agenda 1a)",
      "goal": "Name + agency + specific observed fact + ONE hook question. No agenda/roadmap language yet.",
      "advance_when": "Prospect engages past the hook (asks a question, acknowledges, or pushes back without hanging up).",
      "sub_steps": {
        "standard": {
          "guidance": "Calm, factual. One sentence of context, one hook question ('You aware of that?' / 'You got a minute?').",
          "exemplars": [
            {"situation":"single code violation","text":"Mike, this is Claude ... you aware of that situation?","source":"owner-verbatim"}
          ]
        },
        "multi_violation": { "guidance":"...", "exemplars":[ ... ] },
        "crisis": { "guidance":"Acknowledge stress FIRST. Never 'how are you.' Hook = 'you got a few minutes to talk?'","exemplars":[ ... ] }
      }
    },
    "agenda": { "label":"Agenda / roadmap (1b)","goal":"Permission + roadmap + guilt-free exit. Comes ONLY after intro engagement.","advance_when":"Prospect agrees to talk.","sub_steps":{ ... } },
    "qualification": {
      "label":"Qualification",
      "goal":"Surface all four pillars before any play: NEED/GREED, MONEY, AUTHORITY, TIME. Plus desired outcome.",
      "advance_when":"All four pillars have a value AND desired_outcome is known.",
      "sub_steps": {
        "need_greed": {"guidance":"Pain 1-10, emotional trigger. Negative-phrased redirection.","exemplars":[ ... ]},
        "money": {"guidance":"Can they fund a fix / is cash locked up. Never name a buy price first.","exemplars":[ ... ]},
        "authority": {"guidance":"Decide alone or need spouse/partner.","exemplars":[ ... ]},
        "time": {"guidance":"Deadline; what happens if nothing changes.","exemplars":[ ... ]},
        "disqualify": {"guidance":"When pillars fail, fire the prospect politely — this is a WIN.","exemplars":[ ... ]}
      }
    },
    "commitment": { "label":"Commitment","goal":"Hypothetical close — prospect names the finish line before any play.","advance_when":"Prospect states what they'd say yes to.","sub_steps":{ "hypothetical_close":{...} } },
    "play_close": { "label":"Play + Close","goal":"Present exactly ONE play qualification surfaced; lock specific day/time; freedom close; capture phone+email.","advance_when":"Callback locked or prospect fired.","sub_steps":{ "present_one_play":{...}, "lock_callback":{...}, "pin_think_about_it":{...} } }
  },
  "moves": {
    "stroke":"sincere recognition on legit pushback",
    "nurture":"normalize their pain",
    "redirection":"short answer + question; negative phrasing; OPPOSITE when attacked",
    "takeaway":"pull back when they're hot ('maybe this isn't a fit')"
  }
}
```
Step keys MUST match the values the model already emits in `staircase_step` so injection can key off it. Current schema emits `intro | qualification | play | commitment`. **Reconcile:** update OUTPUT_CONTRACT's `staircase_step` enum to exactly `intro | agenda | qualification | commitment | play_close` and make the library keys identical. (This is the one schema change — see Step 4.)

---

## STEP 3 — Frontend: carry state forward (C1)
`cellcoach_ui.html`.

3a. Add to `S` init (~line 1135): `lastAnalysis:null,`. Reset it to `null` everywhere the call/training resets `S.coachContext=''` (lines ~1272, ~1627, ~2011).

3b. In `showCoaching(a, isInstant)` (~line 1489): after rendering, if NOT an instant/objection card, store `S.lastAnalysis = a;`. (Guard: don't overwrite with instant-objection cards — those don't carry staircase state.)

3c. In `analyze()` (~line 1703) body object (~line 1708), add:
```js
prior_state: S.lastAnalysis ? {
  staircase_step: S.lastAnalysis.staircase_step,
  checklist:      S.lastAnalysis.checklist,
  prospect_intel: S.lastAnalysis.prospect_intel,
  play:           S.lastAnalysis.play
} : null
```

3d. `showOpeningLine()` (~line 1680) sends `opening:true` — leave `prior_state` null there (nothing precedes the opener).

3e. **Training mode uses the same `/api/analyze`** — confirm the training analyze path (around line ~2047+, the text/voice training onTranscript → analyze) also carries `S.lastAnalysis`. If training builds its own body, apply 3c there too. Verify by reading that block; do not assume it shares `analyze()`.

---

## STEP 4 — Backend: consume state + inject exemplars (C1 + C2)
`cellcoach.py`.

4a. Add a cached loader near the other loaders (~line 44-73):
```python
STAIRCASE_PATH = os.path.join(BASE, "cc_staircase.json")
_STAIRCASE_CACHE = None
def _load_staircase():
    global _STAIRCASE_CACHE
    if _STAIRCASE_CACHE is None:
        try:
            with open(STAIRCASE_PATH, encoding="utf-8") as f:
                _STAIRCASE_CACHE = json.load(f)
        except Exception:
            _STAIRCASE_CACHE = {"steps": {}, "moves": {}}
    return _STAIRCASE_CACHE
```

4b. In `ep_analyze(d)` (~line 1124): read `prior = d.get("prior_state") or {}`. Determine `current_step`:
- opening branch → `"intro"`.
- else → `prior.get("staircase_step")` if present, else infer as today (fallback).

4c. Build a `CURRENT CALL STATE` block for the user prompt (ongoing branch, ~line 1178) when `prior` is non-empty:
```
CURRENT CALL STATE (carried from the previous coaching turn — advance from here, do not restart):
  staircase_step: <prior step>
  checklist: <prior checklist>
  pillars_known: <derive from prospect_intel: which of need/money/authority/time have values>
  prospect_intel: <prior intel>
RULES:
  - Do NOT mark a checklist item false once true unless the prospect explicitly contradicts it.
  - Do NOT regress to an earlier step unless the prospect forced it (new objection reopens it).
  - If all four qualification pillars are known, move to commitment. If pillars FAIL, coach the disqualify/fire path.
```

4d. Inject ONLY the active step's exemplars. Pull `_load_staircase()["steps"][current_step]` (+ always include `moves`). Format its `goal`, `advance_when`, sub-steps' guidance and exemplars into the user prompt as:
```
ACTIVE STEP: <label>
GOAL: <goal>
ADVANCE WHEN: <advance_when>
APPROVED EXAMPLES for this step (imitate the PATTERN/voice; swap in the real name/agency/fact — never copy verbatim if details differ):
  - [<situation>] "<text>"
  ...
THE THREE MOVES: <moves>
```
Do NOT dump other steps. This keeps the prompt tight and is the whole point of C2.

4e. Update OUTPUT_CONTRACT (~line 411): set `staircase_step` enum to `intro | agenda | qualification | commitment | play_close`. Add one field: `"qualification_verdict": "pass | fail | undetermined"` (enables the disqualify path; harmless if unused). Update the opening-branch instruction (~line 1167) so `staircase_step` = `"intro"` still holds.

4f. Keep `OUTPUT_CONTRACT` JSON schema otherwise unchanged — the frontend depends on it. `checklist` keys stay `intro/qualified/play_selected/committed`.

---

## STEP 5 — Verify imports + smoke test
- `python3 -c "import cellcoach; print('import OK')"` after backend edits.
- `python3 -c "import json; json.load(open('cell_coach/cc_staircase.json')); print('json OK')"`.
- Start server, open UI, run a text-training session, confirm: opener shows intro-only (no agenda), and after 3-4 exchanges the checklist advances and does not flip back. Watch the network tab: `/api/analyze` body now contains `prior_state`.

## STEP 6 — Minimal eval harness (guards future edits)
Create `tests/eval_coach.py` (stdlib only): 8-10 frozen `prior_state` + transcript fixtures with assertions on the RETURNED JSON — e.g. "given intro done + prospect gave urgency, staircase_step advances to qualification and does not reset intro=false". It calls `ep_analyze` directly (import cellcoach), needs a real openai_key, so gate it behind an env flag and skip if absent. Print pass/fail per fixture. This is the safety net for every later prompt change.

---

## Definition of done
1. `cc_staircase.json` exists, valid JSON, covers all 5 steps with 2-3 exemplars per sub-step, sources labeled (verbatim vs derived).
2. Frontend sends `prior_state` on every non-opening analyze (call AND training paths).
3. Backend injects CURRENT CALL STATE + active-step exemplars only; step enum reconciled.
4. `import OK`, both JSON loads OK, smoke test shows monotonic step advance.
5. `tests/extract_dialogue.py` + `tests/eval_coach.py` present and runnable.
6. Completion notes disclose: which sub-steps are pattern-derived, and any exemplar the corpus couldn't supply.

## Out of scope (do NOT do)
Latency/streaming, scoring retries, auth, recording consent, enterprise multi-tenancy. Those are separate tickets.
