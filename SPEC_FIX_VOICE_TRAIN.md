# FIX PLAN — Voice Train Mode: call drops after "Hello?" + coach card never appears

Two confirmed bugs in `cellcoach_ui.html`, plus one hardening task and one UX gap.
No backend (`cellcoach.py`) changes required except optional item 4.

---

## Bug 1 (CRITICAL, breaks ALL coaching — live calls and training): malformed analyze URL

**Location:** `cellcoach_ui.html`, inside `async function analyze()` (~line 1632)

**Current (broken):**
```javascript
const res = await fetch('\api\analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
```

`'\api\analyze'` — backslash escapes collapse to the string `apianalyze`, producing a
relative fetch to `/apianalyze` → 404 → `res.json()` parses the 404 body or throws →
catch block → "coach unreachable" → no SAY THIS card, ever.

**Fix:**
```javascript
const res = await fetch('/api/analyze',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
```

**Verify:** grep the whole file for `'\api` and `"\api` — fix ALL occurrences (there may
be more than one; any fetch URL containing a backslash is wrong).

---

## Bug 2 (CRITICAL, kills voice session after first message): disallowed ElevenLabs override

**Location:** `cellcoach_ui.html`, `ElevenLabsConnection.connect()`, inside `ws.onopen` (~line 2181)

**Current (broken):**
```javascript
init.custom_llm_extra_body = {temperature: 0.85};
```

The agent's Security tab does NOT have the "Custom LLM extra body" override enabled.
ElevenLabs plays the first message (no LLM needed), then terminates the conversation on
the first real turn when the disallowed override is applied. Symptom matches exactly:
connection succeeds → "Hello?" plays → user speaks → call drops.

**Fix:** DELETE that line entirely. Do not replace it. Prospect temperament variation
already comes from the scenario systemPrompt override.

---

## Bug 2b (same failure class): unconditional tts voice override

**Location:** same `ws.onopen` block (~line 2179)

```javascript
...(this.voiceId ? {tts:{voice_id:this.voiceId}} : {})
```

The "Voice" override toggle is OFF on the agent. If `elevenlabs_voice_id_male/female`
are set in `cc_config.json`, this kills the session the same way as Bug 2.

**Fix (choose based on config state):**
1. Check `cc_config.json`. If voice IDs are blank → leave code as-is (it already gates on
   truthiness), just add a comment warning that Voice override must be enabled on the
   agent before setting these config keys.
2. If voice IDs ARE set → tell the user (Sean) to enable the "Voice" toggle under
   Agent → Settings → Security → Overrides and re-Publish, OR blank the config values.
   Do not silently drop the feature.

---

## Hardening: surface the real close reason

**Location:** `ws.onclose` handler in `ElevenLabsConnection`

Already improved (checks `_gotMetadata`), but extend the mid-call path: when the close
happens AFTER metadata (the Bug 2 case), the current message is generic
("Connection closed unexpectedly"). Change to include `ev.code` and `ev.reason`
verbatim, and add a hint: "If the call drops right after the first message, an override
sent by this app may not be enabled on the ElevenLabs agent (Security tab → Overrides)."

Also add `console.log('[ElevenLabs] close', ev.code, ev.reason)` unconditionally.

---

## UX gap: no opener coaching before the prospect speaks

User expectation: the SAY THIS card should give the rep their opening line BEFORE/AT the
prospect's "Hello?" — the coach currently only fires after a prospect transcript event.

**Fix (frontend only, in `startVoiceTraining()` and text-mode start in `startTraining()`):**
Immediately after the session starts (before any transcript arrives), call
`showCoaching()` with an instant opener card built from the scenario:

```javascript
showCoaching({
  say_next: buildOpenerHint(),   // see below
  objection: null,
  coach_type: 'instant'
}, true);
```

`buildOpenerHint()` — small helper. Uses `trainSession.play_context` to pick register:
- If play_context is FIRE or FORECLOSURE (crisis): return a crisis-posture opener per
  G.U.T.S. doctrine, e.g.:
  "Crisis call — acknowledge the stress first, never casual. Try: 'Hi, [their name]? I'm
  [rep]. First — I'm really sorry about what happened with the property. I'm not with
  the city; do you have a minute?'"
- Otherwise: humble-curious standard opener, e.g.:
  "Open humble and curious, never official. Try: 'Hi, is this [name]? This is [rep] —
  I came across something on your property on [street] I was hoping to ask you about.
  Got a quick minute? It's okay to say no.'"
Use `trainSession.prospect_name` if present. Keep it 1-3 sentences.

---

## Execution order
1. Bug 1 (one-line fix + grep sweep) — restores ALL coaching.
2. Bug 2 (delete one line) — stops the voice drop.
3. Bug 2b (inspect config, then act per branch above).
4. Hardening (onclose message).
5. Opener card (new helper + two call sites).

## Verification checklist
- [ ] `grep -n "\\\\api" cellcoach_ui.html` returns nothing
- [ ] `grep -n "custom_llm_extra_body" cellcoach_ui.html` returns nothing
- [ ] Restart server, run a TEXT training session: coach card appears after each prospect line
- [ ] Run a VOICE training session: connection survives past the first user turn
- [ ] SAY THIS opener card visible immediately when the session starts, before "Hello?"
- [ ] Run a normal live-call analyze (or curl POST /api/analyze) to confirm Bug 1 fix didn't regress live mode
- [ ] Check browser console for `[ElevenLabs] close` logs — code should be 1000 on manual end

## Do NOT
- Do not touch `cc_scenarios.json`, the persona text, or backend train endpoints.
- Do not re-add any conversation_config_override fields beyond agent.prompt.prompt,
  agent.first_message, and (config-gated) tts.voice_id.
- Do not "fix" the ScriptProcessor mic pipeline — it is working.
