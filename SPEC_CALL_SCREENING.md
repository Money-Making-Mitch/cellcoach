# CELL COACH — Call Screening / Voicemail Handling
## Spec for executing model — implement exactly, do not improvise design

### PROBLEM
iPhone (and carrier/third-party) call screening — Live Voicemail, "who's calling"
spam screeners, robo-screening apps — intercepts a call before, or instead of, the
real prospect answering. The screener's TTS prompt, or the prospect's short guarded
reply to the screener, gets transcribed into the PROSPECT lane exactly like real
speech. Today the coach treats it as real conversation: it can mark intro/
qualification as done, or worse select a play, based on a robot or a three-word
screening reply. When the actual human then picks up, the coach is coaching for a
stage of the call that hasn't happened yet — the rep's opener gets skipped because
the checklist already thinks they're past it.

### HARD RULES (same as always)
- Touch only `cellcoach.py` and `cellcoach_ui.html` in `cell_coach/`.
- No pip installs, no new JS libraries, no build step.
- Don't touch the setup/cockpit view or anything unrelated to live coaching state.
- Full raw transcript must still be stored for the call record/summary — screening
  detection changes what feeds the COACH, not what gets logged.

### DESIGN: two layers, because pattern-matching alone isn't reliable enough

**Layer 1 — passive auto-detection (best-effort, zero added latency, client-side).**
Catches the common, recognizable cases instantly, same mechanism as the existing
`OBJECTIONS_GLOBAL` instant-match system.

**Layer 2 — manual one-tap reset (the reliable fallback).**
Screener phrasing varies too much to catch every case. The rep needs an
always-visible button to instantly wipe false progress the moment they hear a real
human say hello for real. This is the layer that actually has to work 100% of the
time; Layer 1 is a convenience on top of it.

---

## PART 1 — Two-lane transcript model (frontend, cellcoach_ui.html)

Today `S.transcript` is one string sent both to the DB (`call_end`) and to the coach
(`/api/analyze`). Split it:

- `S.transcript` — unchanged. Full raw log of everything, both speakers, in order.
  Still what gets saved to `cellcoach.db` on disposition. Still what's shown in the
  transcript panel (all bubbles, including screening ones, so the rep can see what
  happened — never hide anything from the rep, only from the coach's *state logic*).
- `S.coachContext` — NEW. The slice of transcript actually fed to `/api/analyze` for
  staircase/checklist purposes. Starts equal to `S.transcript` logic (append normally)
  but:
  - Lines detected as screening (Layer 1) are NOT appended to `S.coachContext`
    (they ARE still appended to `S.transcript` and still rendered as a bubble).
  - Hitting the manual reset button (Layer 2) clears `S.coachContext` entirely,
    regardless of what's in it — full restart for coaching purposes only.

In `analyze()`, change the request body's `transcript` field from `S.transcript` to
`S.coachContext`. Everything else about the analyze call is unchanged.

In `addTranscriptLine(speaker, text)`, add a third parameter `isScreening=false`.
When true: still push into `S.transcriptLines` and `S.transcript` (unchanged
behavior), still render the bubble, but render it with an added CSS class
`screening` and do NOT append to `S.coachContext`. When false (normal case):
append to `S.coachContext` exactly as `S.transcript` does today (same string
format, `"REP: "` / `"PROSPECT: "` prefix).

---

## PART 2 — Screening detection (frontend)

Add a new pattern bank, same shape as `OBJECTIONS_GLOBAL`, placed right above it:

```js
const SCREENING_PATTERNS = [
  /who'?s calling|state your name|say who'?s calling|purpose of (your |this )?call|reason for (your |this )?call/i,
  /may be spam|spam.?likely|robocall|this call (may|might) be/i,
  /not available right now|leave a message after the|record your message|at the tone|please leave your (name|number|message)/i,
  /press \d to|press pound|press the pound key/i,   // IVR/voicemail menu artifacts
];

function isScreeningText(text){
  return SCREENING_PATTERNS.some(re => re.test(text));
}
```

Wire it into BOTH places a prospect turn currently gets processed — the two
`ws.onmessage` handlers (`openSocket` for REP is irrelevant; the PROSPECT-side
socket in `openProspectSocket`, and the equivalent handling inside `openSocket`
when `label==='PROSPECT'` in the Phone Link path). Concretely, wherever the code
currently does:

```js
addTranscriptLine(label==='REP'?'rep':'prospect', m.transcript);
if(label==='PROSPECT'){
  S.lastProspect = m.transcript;
  checkInstant(m.transcript);
  scheduleAnalyze();
}
```

change to:

```js
const screening = label==='PROSPECT' && isScreeningText(m.transcript);
addTranscriptLine(label==='REP'?'rep':'prospect', m.transcript, screening);
if(label==='PROSPECT'){
  if(screening){
    showScreeningCard();
  } else {
    S.lastProspect = m.transcript;
    checkInstant(m.transcript);
    scheduleAnalyze();
  }
}
```

Apply the same change in `openProspectSocket`'s end-of-turn branch (the Twilio /
system-audio prospect socket) — same logic, same `screening` check before deciding
whether to call `checkInstant`/`scheduleAnalyze` or `showScreeningCard()`.

Do NOT run screening detection on partial (mid-sentence) transcripts — only on
`end_of_turn` finalized turns. Partials stay exactly as they are today.

## PART 3 — Screening coach card (frontend, instant, no GPT call)

```js
function showScreeningCard(){
  showCoaching({
    say_next: "Sounds automated — state your name and company plainly, then wait for a live pickup before running your opener.",
    objection: null,
    coach_type: 'screening'
  }, true);  // reuse the isInstant=true path — instant border flash, no GPT latency
}
```

Add a CSS class `.coach-badge.screening` (pick a distinct color not already used —
e.g. a muted purple `background:#2d1b4e;color:#c4b5fd`) so it's visually distinct
from a real instant objection rebuttal (gold) — the rep should be able to tell at a
glance "this was a screener, not a real answer."

Add `.msg.screening` in the transcript panel CSS: dashed 1px border in the muted
purple, small `🤖` prefix or corner label, so scrolling back the rep can see exactly
which lines were auto-flagged as non-real.

## PART 4 — Manual reset button (frontend, Layer 2 — the important one)

Add a small always-visible button in the live view's coach column, above the
checklist card (`.checklist-card`):

```html
<button id="btnFalseStart" class="ghost-btn" style="width:100%;margin-bottom:2px;color:var(--gold);border-color:var(--gold)"
  onclick="resetStaircase()">🔄 False start — real person just picked up</button>
```

```js
function resetStaircase(){
  S.coachContext = '';
  S.lastProspect = '';
  renderChecklist({intro:false, qualified:false, play_selected:false, committed:false});
  $('intelCard').style.display = 'none';
  $('coachWaiting').style.display = 'block';
  $('coachWaiting').textContent = 'Reset — waiting for the real conversation to start…';
  $('coachWaiting').style.color = 'var(--dim)';
  $('sayCard').classList.remove('show');
  // Visual confirmation the reset landed, not just a silent no-op
  const btn = $('btnFalseStart');
  const orig = btn.textContent;
  btn.textContent = '✓ Reset — coaching restarted';
  setTimeout(() => { btn.textContent = orig; }, 1500);
}
```

Must work at any point in the call, any number of times, with zero confirmation
dialog — this has to be a single tap under pressure mid-call, not a modal.

Initialize `S.coachContext = ''` alongside the existing `S.transcript = ''` reset in
`start()`.

## PART 5 — Backend defense-in-depth (cellcoach.py)

Even with client-side filtering, add a prompt-level backstop in case a screening
line ever slips through (e.g. a pattern Layer 1 doesn't catch, but is still weird/
short/non-conversational). Add this fixed rule to `OUTPUT_CONTRACT` (not to
individual personas — it must apply regardless of which persona is active, same
reasoning as the rest of OUTPUT_CONTRACT):

Insert into the `OUTPUT_CONTRACT` string, after the existing "Never invent fines...
truthful." bullet and before "Respond ONLY with valid JSON":

```
"- If the transcript so far looks like it could be an automated call screener or "
"voicemail system rather than a real back-and-forth with the property owner "
"(e.g. a single short instruction-like line with no natural conversational "
"follow-up), do NOT mark checklist steps complete and do NOT select a play based "
"on it — treat the checklist as still at its prior state and coach the rep to "
"wait for a live human.\n"
```

No other backend changes required — `ep_analyze` already just relays whatever
`transcript` string it's given; sending it `S.coachContext` instead of the full
transcript is a frontend-only change (Part 1).

## PART 6 — VERIFICATION CHECKLIST
1. Simulate: manually type/paste a fake end-of-turn message matching each
   `SCREENING_PATTERNS` regex into the PROSPECT socket handler (temporarily, via
   console) and confirm: transcript bubble renders with `.screening` styling,
   `S.coachContext` does NOT grow, `S.transcript` DOES grow, `scheduleAnalyze()` is
   NOT called, the purple screening coach card appears instantly.
2. Confirm a NORMAL prospect line (no pattern match) still updates `S.coachContext`,
   still calls `checkInstant`/`scheduleAnalyze`, exactly as before this change —
   this feature must not regress the normal coaching path.
3. Click "🔄 False start" mid-call with existing checklist progress showing 3/4 —
   confirm checklist visually resets to 0/4, intel card hides, `S.coachContext`
   is empty, and the NEXT real prospect turn after the reset drives a fresh
   `/api/analyze` call with only post-reset content as context.
4. Confirm `S.transcript` (and therefore what gets saved via `/api/call_end` and
   shown in Past Calls / used for the post-call summary) is UNCHANGED by any of
   this — screening lines and pre-reset content must still be in the permanent
   record even though they were excluded from live coaching.
5. Confirm partial (non-final) transcripts are never run through
   `isScreeningText` — only finalized (`end_of_turn`) turns.
6. `python -m py_compile cellcoach.py` passes after the OUTPUT_CONTRACT edit.

## OUT OF SCOPE
- No changes to setup/cockpit view, sources, CSV import, recording, or persona
  management — this spec is scoped entirely to the live coaching screen.
- No attempt to detect screening from AUDIO characteristics (tone, robotic pitch,
  silence gaps) — text-pattern matching only, per the "zero added latency,
  client-side" constraint. Audio-based detection would need a different pipeline
  and is a bigger, separate project if the text patterns prove insufficient.
- Do not try to auto-resume/redial after voicemail — out of scope, this spec only
  stops false coaching state, it doesn't manage the call itself.
