# GUTS MASTER BUILD PLAN — cell_coach Service-Mode Coaching Engine
**Date:** 2026-08-04 · **Source doctrine:** Claude Diamond G.U.T.S. conversation (1,063 messages, fully analyzed) + G.U.T.S. training transcripts
**Scope:** GUTS only. Cardone and Custom personas are deprecated from active use.

---

## 0. WHAT ALREADY EXISTS (verified in cellcoach.py, do not rebuild)

| Component | Status | Location |
|---|---|---|
| Staircase engine (steps + moves injected into coach prompts) | ✅ Working | `cc_staircase.json`, `_build_staircase_block()`, step classifier |
| Live coach node (per-transcript-turn coaching) | ✅ Working | `_node_coach()` |
| Persona system (JSON, editable, resettable) | ✅ Working | `cc_personas.json` — ships with Cardone only |
| Per-lead `play` field | ✅ Exists, underused | `imported_leads.play`, `calls.play` |
| Training mode + post-call grading | ✅ Working | `ep_train_coach`, `session_scores`, `TRAIN_GUARDRAILS` |
| Rep profile (weak/strong categories injected into prompts) | ✅ Working | `rep_profile` table, `_get_profile_context()` |
| Live transcription (dual-STT AssemblyAI) | ✅ Working | — |

**The gap is not the engine — it's that the engine has no GUTS playbooks, no signal-severity model, no pivot logic, and no valuation brain.**

---

## 1. BUSINESS FUNNEL (locked, from owner directive)

```
TOP OF FUNNEL — Risk & Compliance Bureau (RCB)
  Real service. Files city extensions (30/60/90 days) for $250 upfront.
  Then routes to vetted permit expediter or GC (referral fee backend).
  SCOPE HONESTY: we file extensions ONLY. We never claim to fix the violation.
  ETHICS RAIL: fire/flood/emergency victims are NEVER charged the $250 —
  those calls are referral-only (money comes from contractor side).

BOTTOM OF FUNNEL — Investment company (wholesale acquisitions)
  The actual endgame. Every compliance call is also a discovery call
  for motivated-seller signals. When severity is high, the rep pivots:
  lease option FIRST, cash offer SECOND (when equity is thin),
  cash-first when equity is fat. MAO = 70% × ARV − repairs − fee.
```

---

## 2. TARGET ARCHITECTURE — 5 layers

### Layer 1 — Signal & Severity Data Model (leads)
`imported_leads` currently stores ONE signal per row (`play`, `case_id`, `description`). Multi-signal stacking needs:

```
ALTER imported_leads ADD COLUMN signals TEXT;        -- JSON array: ["permit","311_noise","str_unlicensed","trash"]
ALTER imported_leads ADD COLUMN signal_count INT;    -- denormalized for fast queue sort
ALTER imported_leads ADD COLUMN severity TEXT;       -- LOW | MED | HIGH | CRITICAL
ALTER imported_leads ADD COLUMN arv REAL;            -- pre-computed valuation (Layer 4)
ALTER imported_leads ADD COLUMN mao REAL;            -- 0.70*arv - est_repairs - fee
ALTER imported_leads ADD COLUMN est_repairs REAL;
ALTER imported_leads ADD COLUMN equity_band TEXT;    -- FAT | THIN | UNKNOWN  (drives cash-first vs lease-first)
ALTER imported_leads ADD COLUMN occupancy TEXT;      -- absentee | owner_occupied | unknown (angle lock)
```

Ingestion change: when a CSV/lead import happens, group by address+owner and STACK all signals into one row. A lead with 3 violation types = one lead, `signal_count=3`, not three rows.

**Severity scoring (v1 rules, tune later):**
- 1 signal → LOW/MED → compliance play only
- 2 signals → HIGH → compliance play + coach arms the pivot question
- 3+ signals, or any foreclosure/auction signal → CRITICAL → coach treats wholesale as the primary objective, compliance as the door-opener

### Layer 2 — GUTS Playbooks (the 4 profiles)
New file `cc_playbooks.json` — one playbook per service mode. The dialer gets a **mode selector** (Permits & Violations / Wholesale / FMCSA / General). Selecting a mode loads that playbook into every coach prompt.

Each playbook is structured JSON, not a blob prompt:

```json
{
  "id": "permits_violations",
  "identity": "Sean calling from Risk and Compliance Bureau — an independent agency",
  "disclaimer_required": true,
  "opener_facts": ["county permit records", "violation type", "property address"],
  "interrupt_question": "Did you know the city had flagged you for that?",
  "bridge": "I figured you probably wouldn't have — that's actually the reason for my call.",
  "agenda_permission": "Would you mind if I ask you a few questions about your situation? And if there's nothing I can do to help, that's completely fine — just tell me no.",
  "qualification_tree": [...zero-awareness-safe question set...],
  "urgency_math": {"flag_age_days": 14, "fine_start": "day ~14", "compounding": "couple hundred/month"},
  "money_plays": ["extension_filing_250", "contractor_referral"],
  "ethics_rails": ["never charge fire/flood/emergency victims — referral only",
                    "we file extensions ONLY — never claim to fix the violation"],
  "pivot": {"trigger": "signal_count>=2 OR prospect expresses burnout/ overwhelm/'just want out'",
            "sequence": ["lease_option", "cash_offer"],
            "line": "Would you ever consider just getting out from under it?"},
  "objection_library": {"do_it_myself": "anything you say to the inspector can be used in your case..."},
  "close_mechanics": ["DocuSign consent on call OR same-day follow-up commitment",
                       "consent first → inspector diagnosis → THEN collect $250"]
}
```

**The four modes:**
1. **Permits & Violations** — RCB identity, $250 filing, extension urgency math, contractor referral, wholesale pivot armed by severity.
2. **Wholesale / Foreclosure** — investor identity (no RCB disclaimer), auction-date urgency, equity fork (cash-first if FAT, lease-option-first if THIN), MAO framing, debt-payoff + relocation-cash structure.
3. **FMCSA** — compliance identity for carriers; urgency = revenue lost per day parked; needs its own fact base (out-of-service orders, safety scores). **Placeholder until its doctrine pass is done — do not fake it.**
4. **General** — adaptive mode: staircase + moves + zero-awareness rules only, no service facts; the coach infers context from the live transcript and advises situationally.

### Layer 3 — Live Coach Directive Injection
`_node_coach()` already receives `step, signals, ctx, persona_prompt, staircase_block`. Extend the ctx payload per call with:

```json
"lead_intel": {
  "signals": [...], "signal_count": 3, "severity": "CRITICAL",
  "occupancy": "absentee", "playbook": "permits_violations",
  "arv": 325000, "mao": 219500, "equity_band": "FAT",
  "pivot_armed": true
}
```

Coach behavioral rules baked into the GUTS persona prompt (from the conversation — these are the *coaching* behaviors, not the call script):
- Tough critic, zero yes-man. Real debriefs: word swaps, buried price, skipped money/authority check, skipped Review step.
- Scripts render **line-by-line, blank line between sentences, never paragraphs, never stage directions inside scripts**.
- Stop-correct-rerun: name the broken beat, explain WHY, hand over the corrected line, reset from the top.
- Logic audit above all: wholesale never pays fair market; numbers must match the lead's ARV band; never ask absentee owners "how long have you lived there"; urgency math must not contradict itself.
- Zero-awareness rule: never ask the prospect questions that assume knowledge they don't have.
- Press emotional cracks 2–3× before moving on (redirect rule).
- Coach from transcript text only — never claim to hear tone; transcription artifacts (file/follow) are not rep errors.
- Drill detection: 6+ clean reps = move on; lines degrading under repetition = call a break.

### Layer 3b — THE DIAMOND LAYER (coach execution spec, from source material 2026-08-04)
The owner's #1 complaint about the current engine: **coach output is too long, talks over the prospect, tells instead of plants.** These rules fix execution, not structure. Verified against the Live G.U.T.S. Sales Call transcript, GUTS CD 2, and the Ego Roles mindmap:

**OUTPUT DISCIPLINE (hard constraints on every SAY THIS):**
- Max 1–2 short sentences per coach prompt during LIVE calls. A long SAY THIS is a failed SAY THIS — the rep can't deliver a paragraph while listening.
- Default coach posture is LISTEN, not TALK. If the prospect is talking and revealing, the correct coach output is silence or "let him finish — don't interrupt."
- After every rep question, the next move is a pause for the answer — coach never stacks two questions.
- Track talk ratio per call; flag when rep monologues (target: prospect talks more than rep during qualification).

**SEED-PLANTING MECHANICS (the prospect must think it's their idea):**
- NEVER ask for the order. The prospect gives YOU the order because they reached their own conclusion. "Everybody loves to buy; nobody wants to be sold."
- **Negative phrasing** — float the offer as its opposite: "you probably wouldn't be open to leasing it for a year first, would you?" Reflex disagreement works FOR the rep.
- **Mis-guess redirection** — deliberately under/over-estimate so they correct you with the truth: "you've probably got five, six months?" → "no, we close in May." Now THEY said the timeline.
- **Third-party pain stories** — "I had a friend who got killed carrying two mortgages." Emotion decides; logic justifies. People act to avoid pain or move to pleasure.
- **Needs-help positioning (Child ego state)** — "I'm a little embarrassed, I have your number here and I'm not sure why…" invites the prospect into the rescuer role. They do the work; defenses drop. Use ONLY when there's no hard data standing (per the thread: data-backed calls use the direct opener).
- **Get information, don't give information.** Qualify money, timeline, and authority EARLY (the Christmas-morning dentist: real need never negotiates). Love the word "no" — a fast no in minute 3 beats a slow no in week 3.
- Never present until qualified: need + money + timeline + authority all confirmed.
- 3–5 minute discipline: get to the point; don't negotiate price on a first call.

### Layer 4 — Real-Time ARV / Offer Engine
**Timing rule: compute at BRIEF (lead on screen), never mid-LIVE-call.** Live calls have no latency budget for API round-trips; the number must already be sitting in `lead_intel` when the phone rings. A manual "refresh valuation" button covers stale data.

**Source priority:**
1. **Internal data first** — the data_center stack already holds county property records with estimated values for ~7k+ properties (`STACK_DASHBOARD` data). Address match → instant, free, local.
2. **External fallback** — RentCast or ATTOM API for AVM + comps when the address isn't in local data. Cache every result keyed by address (30-day TTL) so repeat leads never re-hit the API.

**Offer math (GUTS wholesale doctrine):**
```
ARV  = comps/AVM for address
MAO  = 0.70 × ARV − est_repairs − target_assignment_fee (Austin band $8–18k)
OFFER RANGE shown to rep: [MAO − 5k] to [MAO + 5k] with equity band label
```
The coach shows the rep the range and the anchor ("open at $212k, ceiling $225k, they think it's worth $325k — let THEM name the first number").

**Never auto-blurt numbers** — the coach arms the rep with the range; the rep still runs the conversation ("what would you need to see to walk away?").

### Layer 5 — Training Mode alignment
Training scenarios (`session_scores.scenario_id`) get tagged with a playbook id so practice sessions drill the same playbook the rep will use live. Scenario generator uses the playbook's qualification tree + objection library, and the grader scores against GUTS criteria only (agenda earned, zero-awareness violations, pivot timing, price delivery, Review step present).

---

## 3. BOTTLENECKS & GAPS (honest list)

1. **ARV data coverage.** Internal stack data covers Austin metro properties but may not cover every lead address; external AVM costs per lookup (~$0.05–0.25) and has 1–3s latency → must be pre-computed, cached, and fail gracefully ("no valuation — run the conversation on their answers only").
2. **Repair estimates are the weak link in MAO.** v1 uses violation-type heuristics (structure=$8–15k, permit=$1–3k, fire=inspector-severity-driven). This is exactly why the GUTS thread established *inspector call first* — the app should treat est_repairs as provisional until the inspector diagnosis comes back.
3. **Signal stacking requires clean address+owner matching.** County data is dirty (CEDAR VILLA LTD vs Cedar Villa Ltd). Need normalization at ingest or multi-signal leads will silently split into singles and severity will undercount.
4. **FMCSA doctrine doesn't exist yet.** The playbook is a placeholder. Building it without its own training pass = the "bullshit ass script" problem.
5. **STT latency vs. pivot timing.** The pivot window (prospect says "I'm just done with it") is a 2–4 second moment. Coach prompts must be short enough to render a SAY THIS inside that window; long playbook JSON must be summarized into the prompt, not dumped.
6. **Consent/scope legal rails.** The $250 filing pitch must always include scope honesty ("we file the extension — we don't fix the violation") and the independent-agency disclaimer. These get enforced as hard rules in the playbook, not suggestions.

---

## 4. EXECUTION SEQUENCE

**Phase 1 — GUTS persona + playbook schema (foundation)**
1. Write `cc_playbooks.json` with the full Permits & Violations playbook (content exists — it's the Marcus/Susan script set from the GUTS thread) and the Wholesale/Foreclosure playbook (John auction-lead script set). Stub FMCSA and General.
2. Replace the shipped Cardone default persona with the GUTS coach persona (tough-critic behaviors + coaching rules from §Layer 3). Keep Cardone in the file but inactive.
3. Add the mode selector to the dialer UI; wire selection → playbook id → `_node_coach` ctx.
4. Verify: start a training session in Permits mode, confirm coach output uses RCB identity, line-by-line scripts, and the pivot rule fires on a 2-signal test lead.

**Phase 2 — Signal stacking + severity**
5. Schema migration (Layer 1 columns) + ingest-time stacking by normalized address+owner.
6. Severity scorer v1 + queue sort by severity.
7. Verify: import a multi-signal test CSV; confirm one stacked lead, correct severity, pivot_armed=true in coach ctx.

**Phase 3 — ARV engine**
8. Address matcher against internal stack data (est_value source) + `property_valuations` cache table.
9. External AVM fallback (RentCast/ATTOM key required from owner) + 30-day cache.
10. MAO calculator + BRIEF-state display (ARV, MAO range, equity band, anchor advice).
11. Verify: pick 5 known Austin addresses, compare engine output to reality, tune repair heuristics.

**Phase 4 — Training mode unification**
12. Tag scenarios with playbook ids; grader scores GUTS criteria; rep_profile weak categories map to GUTS steps (agenda, qualification, pivot timing, close).
13. Verify: full Marcus-permit-violation training run graded against the playbook.

**Phase 5 — FMCSA doctrine pass** (separate session, same method as this one: feed the FMCSA practice threads, extract doctrine, build playbook)
14. Not started — blocked on doctrine extraction.

**Phase 6 — Cleanup**
15. Remove the stale "Ray Delgado" test row (calls id 95, phone 7375106116) and any sticky_did pairing for it once the user confirms the voicemail retest.

---

## 5. LOCKED ARCHITECTURE — Persona Engine & Situational Logic (approved 2026-08-04)

Owner approved the following design via system directive. This governs Phase 1 implementation.

### 5a. 3-Layer Prompt Architecture (Challenge 1 — UI-editable persona)

The coach prompt is three stacked layers with different ownership:

1. **Harness (code-owned, never UI-editable).** `_NODE3_CONTRACT` + output caps (1–3 sentence SAY THIS), silence-by-default, STT-artifact tolerance, banned phrases, safety rails (never charge crisis victims). A pasted persona can never break this — it is appended after the persona block in `_node_coach`.
2. **Doctrine (100% UI-editable data).** The methodology: philosophy, tone, default posture, authority moments, core rules, debrief style. Lives in `cc_personas.json` as structured fields, compiled to `system_prompt` by `_compile_persona_prompt()`. Swap GUTS → Wolf of Wall Street = paste new doctrine in the Coach Training modal, save, select. Zero code.
3. **Playbook (UI-editable data, orthogonal axis).** What the call is about: Permits / Wholesale / FMCSA / General — scripts, $250 mechanics, signal-stack pivot logic, MAO math. Persona = HOW to coach; Playbook = WHAT the call is about. Any persona × any playbook.

**Source-of-truth rule:** if a persona record has a `doctrine` object, the doctrine is canonical and `system_prompt` is recompiled at load. Raw text editing requires explicit conversion to raw mode (UI button clears `doctrine`, keeps compiled text as starting point).

**Persona record schema:**
```json
{
  "<id>": {
    "name": "string",
    "built_in": true,
    "description": "one-liner shown in the UI list",
    "doctrine": {
      "identity": "who the rep is (may contain {rep_identity})",
      "philosophy": "the methodology core",
      "tone": "voice rules",
      "default_posture": "listener | balanced | driver",
      "debrief_style": "tough_critic | balanced | encouraging",
      "authority_moments": ["when to deploy authority, in doses"],
      "core_rules": ["hard doctrine rules"]
    },
    "tactic_matrix": [
      {
        "id": "snake_case",
        "phase": "opener | discovery | pain_press | bridge | objection | close | any",
        "prospect_state": "guarded | rushing | opening | engaged | skeptical | angry | stalling | any",
        "posture": "confused_helper | listener | authority | closer",
        "guidance": "what the coach pushes for in this cell",
        "example_lines": ["verbatim-speakable lines"]
      }
    ],
    "system_prompt": "compiled — auto-generated; raw text only for doctrine-less personas"
  }
}
```

### 5b. Situational Logic Engine (Challenge 2 — when to use which tactic)

**Two tiers:**

- **Tier 1 (Phase 1, ships now): LLM-evaluated matrix.** The full tactic matrix compiles into the coach prompt as a state→posture lookup table. The LLM classifies prospect state + call phase from the transcript and coaches from the matching cell. Zero new latency.
- **Tier 2 (Phase 2, deterministic State Evaluator).** A local heuristic layer (zero API) computes a call-state snapshot per prospect utterance — emotional state (guarded/opening/rushing/angry/skeptical/stalling), staircase phase, objection type, talk ratio, interruptions — and passes it as structured context into `_node_coach`. Deterministic overrides stay hardcoded where judgment is not allowed (e.g. rep talk-ratio over threshold FORCES a "stop talking, ask a question" nudge regardless of model output).

**Governing Diamond nuance for every matrix:** default posture is always Child/listener. Authority is deployed in doses — fact-drop, invited questions, diagnosis, price, close — then holstered. The coach must never leave the rep parked in authority mode.

**Tactic matrix is data, not code.** Stored per-persona in `tactic_matrix`, editable in the Coach Training UI, so live-call discoveries tune the matrix without touching Python.
