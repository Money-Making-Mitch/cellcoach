# CleanCall-AI → Domain-Agnostic Cold-Call Trainer
## Architecture & Flow Redesign

**Date:** 2026-07-17  
**Current state:** Cleaning company phone-rep trainer (homeowner books cleaning)  
**Target state:** Universal cold-call sales trainer (any industry, any pitch, rep drives discovery)

---

## Core Insight

In the cleaning version, the prospect KNOWS a cleaning-related call is coming. In the new version, the prospect knows NOTHING — they're receiving a genuine cold call. This forces the rep to:
1. Establish credibility without assumptions
2. Hook attention before pitching
3. Discover if the prospect is even a fit
4. Move the prospect from skeptical → interested → committed

The ElevenLabs prospect must react naturally to this dynamic — starting neutral/skeptical, gradually warming or hardening based on the rep's skill.

---

## UX Flow (Proposed)

### Step 1: Pre-Call Setup (New)
Before dialing, the rep answers a brief questionnaire:

| Field | What it's for | Example |
|-------|---------------|---------|
| **What are you selling?** | Industry + offering | "SaaS data platform for insurance brokers" / "Note-sourcing investor services" / "Roofing contractor" |
| **Your hook — why should they care?** | 30-second value prop (caller's angle) | "We help brokers close 40% more policies with AI workflows" / "We source off-market notes at 60% ARV" |
| **Who are you calling?** | Target role/persona | "Insurance broker owner-op" / "Real estate investor, 5+ properties" / "Facilities manager at a hospital" |
| **Objections you expect** | What they'll likely push back on | Cost / Timeline / Trust / Authority / "We already have a solution" |
| **Character you want to practice against** | Prospect personality | BUSY (short patience, high stakes) / SKEPTICAL (been burned, demands proof) / CURIOUS (open-minded, asks questions) / CAUTIOUS (wants to consult others) |

### Step 2: Session Starts
- **Rep dials** (or uses training mode)
- **Prospect is UNINFORMED** — system prompt knows none of the above
- **Rep delivers their cold intro** → prospect hears it for the first time
- **Prospect reacts naturally** based on personality + call quality

### Step 3: Coach Behavior
Same as Cell Coach today:
- Real-time coaching on rep's moves
- G.U.T.S./Cardone staircase (qualify → hook → commit → close)
- Flags premature pitches, poor posture, missed discovery
- Trains the rep to EARN interest, not assume it

---

## Character Model (Finalized)

Two layers, controlled separately:

**SKELETON (locked — the rep selects it, fully repeatable):**
- **Archetype** (5): Neutral, Skeptical, Busy, Curious, Cautious — *how* they express themselves
- **Valence** (2): Positive-lean vs Negative-lean — *which way they're pointed* at pickup

= 10 selectable characters. Picking one gives the same starting person every run.

| Archetype | Positive lean | Negative lean |
|-----------|---------------|---------------|
| Neutral | Open-minded — benefit of the doubt | Indifferent — needs a reason to care |
| Skeptical | Burned but hopeful — wants to believe you | Cynical — expects a scam |
| Busy | Fast but game — interested if you're quick | Annoyed — wants off the phone |
| Curious | Eager — asks real questions | Poking holes — curious to disqualify you |
| Cautious | Willing but careful — follows your lead | Deferring — looking to stall |

**SKIN (improvised fresh each run, but locked within the run):**
- **Grounded topic reality** — the prospect's real, specific relationship to whatever topic the caller reveals. Their situation, history, prior awareness, and emotion about it. This is the ONLY thing that varies run to run, and it's filtered through the fixed archetype+valence so it's always coherent, never random.

**Key principle — the only random thing is the unsolicited call itself.** Once the caller names the topic, the prospect adopts ONE believable grounded reality and holds it with genuine reasoning and emotion for the whole call. No flip-flopping. See the ElevenLabs prompt's "The Only Thing That's Random" section.

**Trajectory:** starting stance is locked; the prospect still warms or hardens based on the rep's skill. Same start every run, different finish = the rep's scorecard.

---

## Script Personas (Rep-Side Methodology Framework)

Two separate selection axes before a call starts:

| Axis | What it controls | Who it affects |
|------|-----------------|----------------|
| **Script Persona** (this section) | The methodology the COACH uses to guide the REP | Rep experience |
| **Character** (above section) | The personality the PROSPECT plays | Prospect behavior |

### What is a Script Persona?

A Script Persona is a structured coaching framework — the playbook the coach follows to evaluate and guide the rep. It defines:

1. **Staircase** — the ordered sequence of steps the rep must execute (e.g., Intro → Agenda → Qualification → Commitment → Play+Close)
2. **Step criteria** — what "done right" looks like for each step, so the coach knows when to advance
3. **Moves** — the techniques available at every step (stroke, nurture, redirection, takeaway, etc.)
4. **Rules** — non-negotiable behavioral constraints (e.g., "no presentation before qualification")
5. **Objection handling** — methodology-specific responses to common pushback
6. **Voice/tone doctrine** — how the rep should sound under this framework

The coach **tracks progress through the staircase in real time**: which steps are completed, which is active, what the rep needs to do next. This is the "checklist" the rep sees — the coach checks off steps as the rep executes them correctly.

### Available Script Personas

#### 1. Claude Diamond — G.U.T.S. (`guts`)

**Staircase:**
```
INTRO+AGENDA → QUALIFICATION → COMMITMENT → PLAY+CLOSE
```

**Step tracking:**

| Step | Coach checks for | Advance when |
|------|-----------------|--------------|
| **INTRO+AGENDA** | Calm factual opener, independent agency disclaimer, hook question ("You aware of that?"), permission ask, guilt-free exit ("cool to tell me no"), pre-commitment ("fair?") | Prospect has granted permission and engaged |
| **QUALIFICATION** | Discovery questions surfacing all 4 pillars: Need/Greed (1-10 scale), Money, Authority, Time. Doctor posture — questions, not presentations. Negative-phrased questions to pull positive answers. | All four pillars known + play direction identified |
| **COMMITMENT** | Isolate the one thing ("if I could only help with one"), hypothetical close ("say I could get that handled — what would you say?"), prospect names the finish line themselves | Prospect has stated what winning looks like + positive reaction to hypothetical |
| **PLAY+CLOSE** | Present ONE play (not a menu), move for TODAY, freedom close, specific callback time, explicit yes-or-no framing | Exact day/time locked, contact captured, yes-or-no answer |

**Moves (running constantly, flagged when used/missed):**
- STROKE — sincere recognition of legitimate pushback
- NURTURE — normalize the pain
- EMPATHY — match their actual register
- REDIRECTION — answer questions with questions, negative phrasing
- TAKEAWAY — pull back when they're hot or posturing

**Rules the coach enforces:**
- No presentation before qualification (flag PREMATURE PRESENTATION)
- Answer questions with questions
- Doctor posture — rep asks, prospect describes
- Never be first to name a price on a buy
- Freedom close on every commitment ask
- "I'll think about it" = failed close → isolate and re-close

**1-10 Need/Greed scale:** Coach tracks the prospect's emotional temperature throughout the call. Coaching adjusts based on where they are — a 3-4 needs more pain-surfacing questions, an 8-9-10 needs takeaways to prevent them from cooling off.

#### 2. Grant Cardone (`cardone`)

**Staircase:**
```
INTRO → HOOK+INTEREST → PRICE → OBJECTION HANDLING → CLOSE
```

**Step tracking:**

| Step | Coach checks for | Advance when |
|------|-----------------|--------------|
| **INTRO** | Self-intro first, ask for owner by name, independent agency line, case reference, hook question ("You aware of that?") | Prospect engaged, identity established |
| **HOOK+INTEREST** | Be interesting FIRST then flip to interested. Ask about them, their situation. Surface THEIR problem in their own words. | Prospect is talking about their situation |
| **PRICE** | Get the fee/offer out early and confidently. No mystery. Direct, transparent. | Price has been stated clearly |
| **OBJECTION HANDLING** | Cardone formula: LISTEN → ACKNOWLEDGE ("Got it.") → ISOLATE ("Other than that, anything else?") → MOVE IN DIRECTION of objection → JUSTIFY → CLOSE AGAIN | Each objection handled with the formula |
| **CLOSE** | One-call-close mindset. Always moving toward closing on THIS call. Freedom close (BYAF). Fear pairing (threat + solution in same breath). | Commitment locked or honest no received |

**Moves:**
- ACKNOWLEDGE — "Got it." Short, respectful, no argument
- ISOLATE — "Other than that, anything else stopping you?"
- MOVE IN DIRECTION — agree with the objection's logic, then reframe
- JUSTIFY — connect the offer to their stated problem
- FREEDOM CLOSE — "Totally your call — tell me no and I'm gone"
- FEAR PAIRING — never state a threat without the solution in the same breath

**Rules the coach enforces:**
- Answer objections with a QUESTION first (target: 54% of the time)
- Slow down on objections — short, calm responses
- ~55% rep talk ratio (don't over-question)
- "Not interested" = they lack information, not that the call is over
- Price early — mystery kills closes
- Scam headwind management — invite skepticism, offer proof
- One-call close — every call moves toward a decision TODAY

#### 3. Custom (`custom`)

No predefined staircase. The rep describes their goal and context via the questionnaire (same as Cell Coach Custom Play). The coach aligns whichever methodology they select (GUTS or Cardone) to the custom goal, stripping domain-specific content and applying only the METHOD.

Custom still tracks progress, but the steps are derived from the selected methodology mapped to the custom goal — not from a fixed property-play staircase.

### Progress Tracking UI

The coach card display shows:

```
┌─────────────────────────────────────────┐
│ ✓ INTRO+AGENDA                          │
│ ● QUALIFICATION  ← YOU ARE HERE         │
│   ✓ Need/Greed surfaced (7/10)          │
│   ✓ Money — has equity, no lien         │
│   ○ Authority — not yet asked           │
│   ○ Time — not yet asked                │
│ ○ COMMITMENT                            │
│ ○ PLAY+CLOSE                            │
├─────────────────────────────────────────┤
│ SAY NEXT: "You making this call on your │
│ own, or is there someone else you'd     │
│ want in on it?"                         │
│                                         │
│ WHY: Authority pillar still open —      │
│ qualify before advancing.               │
└─────────────────────────────────────────┘
```

The checklist is **live** — items check off as the coach detects the rep executing them. The rep sees exactly where they are, what they've done right, and what's next. This is what makes it a training tool, not just a suggestion engine.

### How It Works Technically

1. **Node 1 (classifier)** already detects what the prospect said — objection, question, agreement, stall, etc.
2. **Node 2 (signal detector)** already extracts intel — need level, money situation, authority, timeline, etc.
3. **NEW: Node 2.5 (step validator)** — takes the methodology's step criteria + current checklist state + latest signals, and determines:
   - Which checklist items are now satisfied
   - Whether the current step is complete (all criteria met)
   - Whether to advance `staircase_step`
   - What the rep did wrong (if anything) — premature presentation, skipped qualification, etc.
4. **Node 3 (coach)** receives the updated checklist and generates `say_next` that targets the next unchecked item.

Node 2.5 can run on gpt-4o-mini (it's a structured yes/no evaluation, not generation). The checklist state persists in the analysis response alongside `staircase_step`.

### Methodology-Specific Staircase Files

Each script persona gets its own staircase definition file:

```
cell_coach/
  cc_staircase_guts.json       ← GUTS steps, criteria, exemplars
  cc_staircase_cardone.json    ← Cardone steps, criteria, exemplars
  cc_staircase_custom.json     ← Minimal/generic steps for custom mode
```

These replace the current single `cc_staircase.json` (which is GUTS-only today). The backend loads the correct one based on `persona_id`.

### Staircase File Schema

```json
{
  "methodology": "guts",
  "display_name": "Claude Diamond — G.U.T.S.",
  "steps": {
    "intro_agenda": {
      "label": "INTRO + AGENDA",
      "order": 1,
      "goal": "Permission, roadmap, guilt-free exit, pre-commitment",
      "checklist": [
        {"id": "self_intro", "label": "Self-introduction", "detect": "rep stated name and agency"},
        {"id": "hook_question", "label": "Hook question", "detect": "rep asked 'you aware of that?' or equivalent"},
        {"id": "permission", "label": "Permission to continue", "detect": "prospect granted permission to talk"},
        {"id": "guilt_free", "label": "Guilt-free exit offered", "detect": "rep offered an easy out"},
        {"id": "pre_commit", "label": "Pre-commitment ('fair?')", "detect": "rep locked pre-commitment agreement"}
      ],
      "advance_when": "permission AND (guilt_free OR pre_commit)",
      "exemplars": ["..."]
    },
    "qualification": {
      "label": "QUALIFICATION",
      "order": 2,
      "goal": "Surface Need/Greed, Money, Authority, Time via questions",
      "checklist": [
        {"id": "need_greed", "label": "Need/Greed (1-10)", "detect": "prospect expressed pain level or desire"},
        {"id": "money", "label": "Money situation", "detect": "financial capacity discussed"},
        {"id": "authority", "label": "Decision-maker identified", "detect": "rep asked who decides"},
        {"id": "time", "label": "Timeline/deadline", "detect": "urgency or deadline surfaced"}
      ],
      "advance_when": "need_greed AND money AND authority AND time",
      "violations": [
        {"id": "premature_presentation", "detect": "rep explained program/process before all 4 pillars known", "severity": "critical"}
      ]
    }
  },
  "moves": {
    "stroke": "Sincere recognition of legitimate pushback",
    "nurture": "Normalize the pain",
    "redirection": "Answer questions with questions, negative phrasing",
    "takeaway": "Pull back when they're hot or posturing"
  },
  "rules": [
    "No presentation before qualification",
    "Doctor posture — rep asks, prospect describes",
    "Freedom close on every commitment ask"
  ]
}
```

---

## Technical Architecture

### Backend Changes

**New endpoint: `/api/train/context/setup`** (POST)
```json
{
  "offering": "SaaS data platform",
  "hook": "We help brokers close 40% more policies with AI",
  "target_role": "Insurance broker owner-op",
  "expected_objections": ["cost", "timeline", "already-have-solution"],
  "character": "SKEPTICAL",
  "persona_id": "coach_guts"  // which methodology
}
```

Returns: A **prospect brief** (not shown to prospect) that ElevenLabs uses internally:
```python
{
  "context": {
    "first_time_hearing": True,
    "character_type": "SKEPTICAL",
    "initial_stance": "neutral_to_guarded",
    "personality": "has been burned before, asks for proof, cautious about authority",
  },
  "behavioral_rules": [
    "Don't assume you know what this call is about",
    "React to vagueness with skepticism",
    "If they're clear + honest, gradually warm up",
    "Raise objections naturally (cost, trust, timeline, fit)",
  ]
}
```

**ElevenLabs system prompt update:**
- Remove all property/code-enforcement framing
- Add universal behavioral rules
- Emphasize: "You have no prior context. This is a cold call. React naturally."
- Personality arch: skeptical→interested (if earned) or skeptical→cold (if not)

**Coach persona update:**
- Same GUTS/Cardone methodology
- Updated to focus on: discovery before pitch, earning credibility, natural objection handling
- Remove property-specific exemplars (replace with domain-general ones from existing staircase)

### Frontend Changes

**Setup form (before dialing):**
- Add questionnaire fields (as above)
- Character selector (radio buttons: BUSY / SKEPTICAL / CURIOUS / CAUTIOUS / [NEUTRAL default])
- Save to `S.callContext` (different from `S.custom` — this is the caller's context, not a methodology override)

**Dial/start button:**
- Pass `callContext` to `/api/train/context/setup`
- Load the prospect brief into ElevenLabs system prompt
- Proceed with normal voice training flow

**Coach display:**
- Emphasize staircase position (intro → agenda → qualify → commit → close)
- Flag: "Rep jumped to pitch before qualifying" / "Rep earned enough to move forward"
- Show objection classification (cost? trust? fit? authority?)

---

## What Changes, What Doesn't

### ✓ No changes needed
- Cell Coach staircase (intro→agenda→qualify→commit→close) is universal
- G.U.T.S./Cardone methodology is universal
- Coach moves (stroke, nurture, redirection, takeaway) are universal
- Real-time transcript + analysis flow
- Node 1/2/3 coaching pipeline
- Filler filters, cooldowns, dedupe

### ✗ Changes needed
- ElevenLabs system prompt (property-specific → domain-agnostic)
- Staircase exemplars (property-specific → generic cold-call patterns)
- Coach persona training data (property + contractor/investor framing → pure methodology)
- Training scenario library (cleaning-company cleaning scenarios → move to historical archive; new scenarios are real cold-call genres)
- Setup flow (no scenario picker; instead: questionnaire + character picker)

---

## Scenario Library Redesign (v1)

Instead of:
- Residential cleaning booking
- Commercial carpet cleaning
- Window cleaning lead gen

Switch to:
- **SaaS cold outreach** (to busy CTO: "We automate your data pipeline")
- **Note sourcing** (to investor: "Off-market notes, 60% ARV, 30-day close")
- **Insurance/financial services** (to broker: "AI workflow → 40% more closings")
- **Roofing/contractor** (to homeowner: "We saw storm damage on satellite imagery, offers available")
- **Acquisition sourcing** (to PE/investor: "We source distressed businesses in your region")
- **Staffing/recruitment** (to hiring manager: "We've got three qualified engineers matching your JD")

Each scenario has:
- A prospect archetype (busy exec, budget owner-op, skeptical due diligence, etc.)
- A primary objection pattern (cost? timeline? trust? decision-maker? already-have-solution?)
- Dialogue trees showing natural cold-call realism (prospect didn't expect the call, doesn't know your company, may interrupt, may walk it back)

---

## Sequencing (MVP → v1.1 → v2)

### MVP (v1, this quarter)
- ✓ Universal ElevenLabs prompt (domain-agnostic, prospect uninformed)
- ✓ Pre-call questionnaire + character selector
- ✓ Coach uses existing G.U.T.S. staircase + generic exemplars
- ✗ Custom scenario library (not yet built; use placeholder "generic cold call")

### v1.1 (next quarter)
- ✓ Scenario library (SaaS, note sourcing, acquisition, etc.)
- ✓ Staircase exemplars updated for cold-call realism (not property-specific)
- ✓ Coach persona training data refined

### v2 (later)
- Voice mode for the pre-call questionnaire ("Tell me what you're selling in 30 seconds")
- Prospect archetype auto-selection based on caller's offering ("You said SaaS → we'll use a busy CTO")
- Analytics: which objections reps miss, which industries need better coaching

---

## Key Behavioral Differences (Rep's Job)

### Property trainer (old):
1. Rep picks scenario: "STR violation"
2. Prospect is primed: "I own a rental, I know I have an STR issue"
3. Rep's job: navigate a known problem to a solution

### Cold-call trainer (new):
1. Rep describes offering: "SaaS data platform for brokers"
2. Prospect is uninformed: "I have no idea what this call is about"
3. Rep's job: prove relevance, overcome skepticism, earn interest

**This is harder and more realistic.** The rep has to:
- Open with a hook (not assume context)
- Ask discovery questions (to find if prospect is even a fit)
- Handle "Who are you? How'd you get my number?" naturally
- Earn credibility before presenting
- Move from cold to warm through skill, not scenario luck

---

## Notes for Implementation

1. **ElevenLabs system prompt** should emphasize:
   - "You have no prior knowledge of what this call is about"
   - "You're hearing from a stranger for the first time"
   - "Your initial reaction is skeptical (it's a cold call)"
   - "Your warmth and openness depends entirely on how well they handle you"

2. **Coach exemplars** should reflect:
   - Real cold-call intros ("Hey [name], I know this is random, but...")
   - Discovery questions that *surface* pain ("Are you handling [X] in-house right now?")
   - Transparency on how the rep makes money
   - Earning permission before moving to next step

3. **Metrics worth tracking:**
   - What % of cold opens get past the "Who are you?" objection?
   - Which objections do reps tend to dodge vs. handle?
   - How many calls move from intro → agenda → qualify → commit (staircase health)?
   - Which industries/personas are reps strongest/weakest against?

4. **Keep the G.U.T.S. staircase.** It's already designed for this. The only change is:
   - INTRO now means "hook their attention and get permission to talk" (not "acknowledge their known problem")
   - AGENDA now means "get permission for discovery questions" (not "set roadmap for a known issue")
   - QUALIFY now means "surface if they're even a fit" (not "confirm property details")
   - COMMIT + CLOSE are unchanged

---

## Files to Update

| File | Change | Scope |
|------|--------|-------|
| `cellcoach_ui.html` | Add pre-call questionnaire, character selector | Frontend |
| `cellcoach.py` | New `/api/train/context/setup` endpoint, update coach ctx building, update persona instructions | Backend |
| `cc_scenarios.json` | Add cold-call scenarios (SaaS, note-sourcing, acquisition, etc.) | Content |
| `cc_staircase.json` | Add generic cold-call exemplars (replace property-specific ones) | Content |
| **ElevenLabs system prompt** | Complete rewrite (see next doc) | LLM prompt |
| `cc_personas.json` | Update GUTS/Cardone with universal language | Content |

