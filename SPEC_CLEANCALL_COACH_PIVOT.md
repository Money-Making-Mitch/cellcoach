# CleanCall-AI — Universal Cold-Call Trainer w/ Real-Time Coach
## Implementation Spec for Execution

**Date:** 2026-07-17  
**Scope:** Transform CleanCall-AI from a cleaning-company phone trainer into a domain-agnostic cold-call trainer with a real-time coaching panel, live staircase checklist, and 10-character ElevenLabs prospect system.

---

## What You're Working With

CleanCall-AI is a **Next.js 14 / TypeScript / Supabase** app. Key files:

| File | What it does |
|------|-------------|
| `src/lib/elevenlabs/connection.ts` | WebSocket to ElevenLabs. Already supports `conversation_config_override` to inject a dynamic prompt at call start. |
| `src/components/voice/VoiceCallInterface.tsx` | The active call UI component. Receives transcript events from ElevenLabs. |
| `src/app/dashboard/practice/active/[callId]/page.tsx` | Page that wraps VoiceCallInterface. Fetches call record, saves transcript at end. |
| `src/app/dashboard/practice/page.tsx` | Pre-call setup page. Where the user picks scenario + difficulty today. |
| `src/app/api/calls/[callId]/analyze/route.ts` | Post-call analysis endpoint. Runs after call ends. DO NOT break this — it still runs for post-call scoring. |
| `src/app/api/calls/start/route.ts` | Creates the call record + gets the ElevenLabs signed URL. |
| `src/lib/prompts/promptBuilder.ts` | Builds the ElevenLabs system prompt. Currently cleaning-company specific. |
| `src/lib/scenarios.ts` | Scenario definitions (cleaning scenarios). Being replaced. |
| `src/lib/analysis/callAnalyzer.ts` | Post-call analysis orchestrator. Leave intact. |

**Stack constraints:**
- TypeScript everywhere — no Python
- No new npm packages unless absolutely necessary (use existing deps)
- Keys/secrets stay in `.env.local` only — never hardcoded
- Existing Supabase schema: `calls` table has `scenario_type`, `transcript`, `status`, `score_overall`, etc. You'll add columns for coach data.

---

## What Gets Built

**5 deliverables, in order:**

1. **Pre-call setup UI** — Script Persona picker (GUTS / Cardone / Custom) + Character picker (5 archetypes × 2 valences)
2. **Universal ElevenLabs prospect prompt** — injected at call start via `conversation_config_override`
3. **Real-time coach API** — `/api/coach/analyze` endpoint (3-node pipeline: classify → extract → coach)
4. **Coach panel UI** — live checklist overlay alongside the call, coach on/off toggle
5. **Staircase data files** — `cc_staircase_guts.json` and `cc_staircase_cardone.json`

---

## 1. Pre-Call Setup UI

**File to modify:** `src/app/dashboard/practice/page.tsx`

Replace the current scenario/difficulty picker with:

```
┌─────────────────────────────────────────────┐
│  WHAT ARE YOU PRACTICING?                   │
│                                             │
│  Script Persona (your methodology):         │
│  ○ G.U.T.S. — Claude Diamond               │
│  ○ Cardone — Grant Cardone Method           │
│  ○ Custom (describe below)                  │
│                                             │
│  [if Custom selected, show:]                │
│  What are you selling? ___________________  │
│  Who are you calling?  ___________________  │
│  Your hook/angle?      ___________________  │
│  Expected pushback?    ___________________  │
│                                             │
│  Prospect Character:                        │
│  Archetype: [NEUTRAL▼] [SKEPTICAL] [BUSY]  │
│             [CURIOUS]  [CAUTIOUS]           │
│  Valence:   ○ Positive lean  ○ Negative lean│
│                                             │
│  Coach Panel:                               │
│  ○ ON (shows live checklist + say_next)     │
│  ○ OFF (pure practice — no guidance)        │
│                                             │
│  [Start Practice Call]                      │
└─────────────────────────────────────────────┘
```

**State to capture and pass to the call:**
```typescript
interface PracticeSetup {
  scriptPersona: 'guts' | 'cardone' | 'custom'
  custom?: {
    offering: string      // "what are you selling"
    targetRole: string    // "who are you calling"
    hook: string          // "your angle"
    expectedPushback: string
  }
  character: {
    archetype: 'neutral' | 'skeptical' | 'busy' | 'curious' | 'cautious'
    valence: 'positive' | 'negative'
  }
  coachEnabled: boolean
}
```

Pass `PracticeSetup` to the call start route via the POST body. Store it in the `calls` table as a `coach_config` JSONB column (see DB migration section).

---

## 2. Universal ElevenLabs Prospect Prompt

**File to modify:** `src/lib/prompts/promptBuilder.ts`

Add a new export:

```typescript
export function buildUniversalProspectPrompt(
  archetype: string,
  valence: string
): string
```

The full prospect prompt content is in:
`C:\Users\Admin\data_center\cell_coach\ELEVENLABS_PROSPECT_PROMPT_UNIVERSAL.md`

Read that file. Use its content verbatim as the base, then append the character-specific block below.

**Character injection** — append this to the base universal prompt based on `archetype + valence`:

```
CHARACTER SELECTION: {ARCHETYPE} / {VALENCE}

[NEUTRAL / POSITIVE]
You're open-minded. You don't know this caller but you'll give them a reasonable shot. 
You're not jumping at anything — you just don't have a strong reason to resist yet.
You might actually listen.

[NEUTRAL / NEGATIVE]
You're indifferent. You picked up but you could drop this call any moment.
You need a real reason to keep talking. Vague = dead.

[SKEPTICAL / POSITIVE]
You've been burned before by people like this, but you haven't totally given up.
If this person is honest and specific, you might warm up. You'll test them.

[SKEPTICAL / NEGATIVE]
You expect this to be a scam or a waste of time. You're braced for it.
You'll push back hard on everything. Prove it or you're gone.

[BUSY / POSITIVE]
You're slammed but if this is relevant and they're fast, you'll give them 60 seconds.
You interrupt long explanations. You don't do small talk.

[BUSY / NEGATIVE]
You're annoyed they called. Make it worth your time in the first sentence or you're hanging up.
Short patience. Zero fluff.

[CURIOUS / POSITIVE]
You're actually interested in new things. You'll ask real questions.
If the rep answers well, you keep going. You're not a pushover — you just like information.

[CURIOUS / NEGATIVE]
You ask questions to poke holes. You're curious in the way a prosecutor is curious.
You're looking for inconsistencies, not opportunities.

[CAUTIOUS / POSITIVE]
You want to help but you move slowly. You need to think, check with others, feel safe.
You'll go along if the rep leads carefully — but don't rush you.

[CAUTIOUS / NEGATIVE]
You're stalling. Every answer leads to another person you need to talk to or another thing 
you need to check. You're not saying no — you're avoiding yes indefinitely.
```

**Wire the prompt into the call start flow:**

In `src/app/api/calls/start/route.ts`, after building the signed URL, build the `configOverride`:

```typescript
import { buildUniversalProspectPrompt } from '@/lib/prompts/promptBuilder'

const prospectPrompt = buildUniversalProspectPrompt(
  setup.character.archetype,
  setup.character.valence
)

const configOverride: ConversationConfigOverride = {
  agent: {
    prompt: { prompt: prospectPrompt },
    first_message: 'Hello?'
  }
}
```

Pass `configOverride` back to the client in the response. The client passes it to `ElevenLabsConnection` constructor (already supports this via the existing `ConversationConfigOverride` interface).

---

## 3. Real-Time Coach API

**New file:** `src/app/api/coach/analyze/route.ts`

This is a POST endpoint called during an active call whenever the rep or prospect speaks. It runs a 3-node pipeline and returns a coaching card.

### Input
```typescript
interface CoachAnalyzeRequest {
  callId: string
  transcript: TranscriptEntry[]   // full transcript so far
  latestUtterance: string         // what was just said (rep or prospect)
  speakerRole: 'rep' | 'prospect'
  scriptPersona: 'guts' | 'cardone' | 'custom'
  custom?: CustomContext          // only if scriptPersona === 'custom'
  prior: PriorState               // state from last analyze call
}

interface PriorState {
  staircaseStep: string           // current step ID
  checklist: Record<string, boolean>  // which items are checked off
  sayNext: string                 // last say_next (for dedup)
  objections: string[]            // objections seen so far
  intel: IntelState               // extracted intel
}

interface IntelState {
  needGreedLevel: number | null   // 1-10
  moneyConfirmed: boolean | null
  authorityConfirmed: boolean | null
  timelineKnown: boolean | null
  decisionMakerIdentified: boolean | null
}
```

### Output
```typescript
interface CoachAnalyzeResponse {
  staircaseStep: string
  checklist: Record<string, boolean>
  sayNext: string
  altSuggestion: string
  nextAction: string
  violation: string | null          // e.g. "PREMATURE PRESENTATION"
  violationExplanation: string | null
  objectionDetected: string | null
  intel: IntelState
}
```

### Pipeline (3 nodes)

**Node 1 — Classify** (gpt-4o-mini, ~$0.0001/call)
```
Classify the latest utterance. Return JSON:
{
  "utterance_type": "objection" | "question" | "agreement" | "stall" | "statement" | "close_signal" | "filler",
  "objection_category": "cost" | "timing" | "trust" | "authority" | "competitor" | "not_interested" | null,
  "prospect_temp": "warming" | "cooling" | "neutral" | "hostile",
  "rep_violation": "premature_presentation" | "no_question_asked" | "argued_objection" | "gave_price_first_on_buy" | null
}
```

**Node 2 — Extract Intel** (gpt-4o-mini, ~$0.0001/call)
```
From the full transcript so far, extract what is CONFIRMED (not guessed). Return JSON:
{
  "need_greed_level": 1-10 or null,
  "money_confirmed": true/false/null,
  "authority_confirmed": true/false/null,
  "timeline_known": true/false/null,
  "decision_maker_identified": true/false/null,
  "play_direction": "contractor_referral" | "extension_filing" | "lease_option" | "cash_buy" | "custom" | null
}
```

**Node 2.5 — Step Validator** (local, no LLM)

Load the correct staircase JSON based on `scriptPersona`. Check each checklist item's `detect` criteria against Node 1 + Node 2 outputs + transcript. Return updated checklist and whether to advance the step.

```typescript
function validateStep(
  staircaseJson: StaircaseDefinition,
  currentStep: string,
  checklist: Record<string, boolean>,
  node1: Node1Output,
  node2: Node2Output,
  transcript: TranscriptEntry[]
): { checklist: Record<string, boolean>, advanceToStep: string | null, violation: string | null }
```

Detection rules (deterministic, no LLM):
- `self_intro`: rep transcript contains their name + "with" + organization
- `hook_question`: rep transcript contains "aware" or "know about" or "you hear"
- `permission`: prospect said any affirming response after rep's agenda
- `guilt_free`: rep transcript contains "cool to tell me no" or "totally your call" or "no obligation"
- `pre_commit`: rep transcript contains "fair?" or "sound good?" followed by prospect agreement
- `need_greed_surfaced`: node2.need_greed_level is not null
- `money_confirmed`: node2.money_confirmed is true
- `authority_confirmed`: node2.authority_confirmed is true
- `timeline_known`: node2.timeline_known is true
- `price_stated`: rep transcript contains a dollar amount ("$", "hundred", "thousand", "fee")
- `objection_acknowledged`: rep transcript contains "got it" or "I hear you" or "that makes sense" after an objection
- `freedom_close`: rep transcript contains "totally your call" or "you're free to" or "tell me no"
- `commitment_locked`: prospect said specific day/time for follow-up

Advance step when all `advance_when` criteria for the current step are true.

Flag violation if `node1.rep_violation` is not null AND the violation is defined in the current step's `violations` array.

**Node 3 — Coach** (gpt-4o, only when needed)

Gate: Skip Node 3 if:
- `staircaseStep` unchanged AND
- No new violation AND
- `checklist` unchanged AND
- `prior.sayNext` exists

When Node 3 runs:
```
You are a real-time cold-call coach running the {scriptPersona} methodology.

STAIRCASE POSITION: {currentStep} — {stepLabel}
GOAL: {stepGoal}
REMAINING CHECKLIST ITEMS: {uncheckedItems}
ACTIVE VIOLATIONS: {violation or none}
PROSPECT TEMPERATURE: {node1.prospect_temp}
DETECTED OBJECTION: {node1.objection_category or none}
LAST PROSPECT UTTERANCE: "{latestProspectUtterance}"

{if GUTS: paste sean_direct persona say_next rules}
{if Cardone: paste cardone persona say_next rules}
{if Custom: paste custom context + GUTS/Cardone rules stripped of domain framing}

Generate:
- say_next: 1-3 sentences the rep should say next. Natural, not scripted.
- alt_suggestion: 1 alternative approach if the first doesn't land.
- next_action: 1 sentence on what to accomplish with this next move.

Return JSON: { "say_next": "...", "alt_suggestion": "...", "next_action": "..." }
```

### Anti-spam gates (port from Cell Coach)

Add these in the route handler BEFORE calling Node 1:

```typescript
// 1. Filler filter — skip fillers entirely, return null
const FILLER_RE = /^(yeah|yep|okay|ok|sure|right|uh[- ]?huh|mm+[-\s]?hm+|alright|i see|got it|go ahead|sounds good|of course|absolutely|no problem|cool|great|fine|hm+|mhm|yup|nope|no)\.?[!]?$/i
if (FILLER_RE.test(latestUtterance.trim())) {
  return NextResponse.json({ skip: true, reason: 'filler' })
}

// 2. Short utterance filter — skip if <6 words and no objection keyword
const OBJECTION_KW = /lawyer|attorney|scam|not interested|don.t (call|contact)|remove|already.{0,15}(handle|deal|work)|lawsuit|fraud/i
const wordCount = latestUtterance.trim().split(/\s+/).length
if (wordCount < 6 && !OBJECTION_KW.test(latestUtterance)) {
  return NextResponse.json({ skip: true, reason: 'too_short' })
}
```

Client-side cooldown: the practice UI should not fire `/api/coach/analyze` more than once per 5 seconds. Track `lastAnalyzeAt` in component state.

---

## 4. Coach Panel UI

**New component:** `src/components/voice/CoachPanel.tsx`

Sits alongside `VoiceCallInterface` in the active call page. Receives coaching state as props. Only renders if `coachEnabled === true`.

```tsx
interface CoachPanelProps {
  scriptPersona: 'guts' | 'cardone' | 'custom'
  staircaseStep: string
  checklist: Record<string, boolean>
  sayNext: string
  altSuggestion: string
  nextAction: string
  violation: string | null
  violationExplanation: string | null
  isLoading: boolean
}
```

**Layout:**

```
┌─────────────────────────────────────────────┐
│  COACH — G.U.T.S.                    [OFF]  │
│                                             │
│  ✓ INTRO + AGENDA                           │
│  ● QUALIFICATION  ← YOU ARE HERE            │
│    ✓ Need/Greed surfaced (7/10)             │
│    ✓ Money situation confirmed              │
│    ○ Decision-maker identified  ← DO THIS  │
│    ○ Timeline surfaced                      │
│  ○ COMMITMENT                               │
│  ○ PLAY + CLOSE                             │
│  ─────────────────────────────────          │
│  ⚠ VIOLATION: Premature Presentation        │
│  You explained the program before asking    │
│  about authority. Pull back to discovery.   │
│  ─────────────────────────────────          │
│  SAY NEXT:                                  │
│  "You making this call on your own, or is   │
│   there someone else you'd want in on it?"  │
│                                             │
│  ALT: "Is there anyone else who typically   │
│   weighs in on decisions like this?"        │
│                                             │
│  GOAL: Get authority confirmed before       │
│  advancing to Commitment.                   │
└─────────────────────────────────────────────┘
```

**Styling notes:**
- ✓ = green checkmark for completed items
- ● = blue dot for active step
- ○ = gray circle for incomplete items
- ← DO THIS = highlight the next unchecked item
- Violation block = amber/orange background
- say_next block = slightly elevated card within the panel

**Coach panel toggle:** The [OFF] button in the header hides the panel mid-call (saves to localStorage so preference persists). Does NOT stop the API calls — just hides the UI. This lets reps practice unassisted but review coaching state if they want.

**Wiring into the active call page:**

In `src/app/dashboard/practice/active/[callId]/page.tsx`:

```typescript
// Load coach config from the call record
const [coachConfig, setCoachConfig] = useState<PracticeSetup | null>(null)
const [coachState, setCoachState] = useState<CoachAnalyzeResponse | null>(null)
const lastAnalyzeAt = useRef(0)

// In the transcript callback (fired by VoiceCallInterface):
const handleTranscript = useCallback(async (entry: TranscriptEntry) => {
  if (!coachConfig?.coachEnabled) return
  
  // Cooldown gate
  const now = Date.now()
  if (now - lastAnalyzeAt.current < 5000) return
  lastAnalyzeAt.current = now

  const response = await fetch('/api/coach/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'x-csrf-token': csrfToken },
    body: JSON.stringify({
      callId: params.callId,
      transcript: fullTranscript,
      latestUtterance: entry.text,
      speakerRole: entry.role === 'user' ? 'rep' : 'prospect',
      scriptPersona: coachConfig.scriptPersona,
      custom: coachConfig.custom,
      prior: coachState ? {
        staircaseStep: coachState.staircaseStep,
        checklist: coachState.checklist,
        sayNext: coachState.sayNext,
        objections: coachState.objections,
        intel: coachState.intel,
      } : null,
    })
  })
  
  const data = await response.json()
  if (!data.skip) setCoachState(data)
}, [coachConfig, coachState, csrfToken, fullTranscript])
```

Pass `handleTranscript` as a prop to `VoiceCallInterface`. That component already fires callbacks on transcript events — just swap in this handler.

---

## 5. Staircase Data Files

**New file:** `src/lib/coach/staircases/guts.json`

```json
{
  "methodology": "guts",
  "display_name": "Claude Diamond — G.U.T.S.",
  "steps": {
    "intro_agenda": {
      "label": "INTRO + AGENDA",
      "order": 1,
      "goal": "Get permission, give roadmap, offer guilt-free exit, lock pre-commitment",
      "checklist": [
        { "id": "self_intro", "label": "Self-introduction", "detect": "rep_name_and_org_in_transcript" },
        { "id": "hook_question", "label": "Hook question (You aware of that?)", "detect": "hook_question_in_transcript" },
        { "id": "permission", "label": "Permission to continue", "detect": "prospect_affirmed_after_hook" },
        { "id": "guilt_free", "label": "Guilt-free exit offered", "detect": "guilt_free_in_transcript" },
        { "id": "pre_commit", "label": "Pre-commitment locked (fair?)", "detect": "pre_commit_in_transcript" }
      ],
      "advance_when": "permission AND (guilt_free OR pre_commit)",
      "violations": [
        { "id": "premature_pitch", "detect": "benefit_statement_before_permission", "severity": "critical", "label": "PREMATURE PITCH" }
      ]
    },
    "qualification": {
      "label": "QUALIFICATION",
      "order": 2,
      "goal": "Surface Need/Greed, Money, Authority, and Timeline via questions — doctor posture only",
      "checklist": [
        { "id": "need_greed_surfaced", "label": "Need/Greed surfaced (1-10)", "detect": "need_greed_level_not_null" },
        { "id": "money_confirmed", "label": "Money situation confirmed", "detect": "money_confirmed_true" },
        { "id": "authority_confirmed", "label": "Decision-maker identified", "detect": "authority_confirmed_true" },
        { "id": "timeline_known", "label": "Timeline/urgency surfaced", "detect": "timeline_known_true" }
      ],
      "advance_when": "need_greed_surfaced AND money_confirmed AND authority_confirmed AND timeline_known",
      "violations": [
        { "id": "premature_presentation", "detect": "rep_explained_program_before_all_pillars", "severity": "critical", "label": "PREMATURE PRESENTATION" },
        { "id": "no_question_asked", "detect": "rep_made_statement_without_question", "severity": "warning", "label": "LOST THE BALL" }
      ]
    },
    "commitment": {
      "label": "COMMITMENT",
      "order": 3,
      "goal": "Isolate the one thing they care about. Get hypothetical close. Prospect names the finish line.",
      "checklist": [
        { "id": "isolated_priority", "label": "Isolated #1 priority", "detect": "rep_asked_one_thing_question" },
        { "id": "hypothetical_close", "label": "Hypothetical close attempted", "detect": "rep_asked_say_i_could_or_equivalent" },
        { "id": "prospect_named_win", "label": "Prospect named what winning looks like", "detect": "prospect_positive_response_to_hypothetical" }
      ],
      "advance_when": "isolated_priority AND hypothetical_close AND prospect_named_win"
    },
    "play_close": {
      "label": "PLAY + CLOSE",
      "order": 4,
      "goal": "Present ONE play. Lock a specific next step TODAY. Freedom close. Get explicit yes-or-no.",
      "checklist": [
        { "id": "one_play_presented", "label": "Single play presented (not a menu)", "detect": "single_play_in_transcript" },
        { "id": "today_close", "label": "Close for TODAY", "detect": "same_day_follow_up_proposed" },
        { "id": "freedom_close", "label": "Freedom close given", "detect": "freedom_close_in_transcript" },
        { "id": "explicit_yesno", "label": "Explicit yes-or-no framing", "detect": "yes_or_no_framing_in_transcript" }
      ],
      "advance_when": "one_play_presented AND (today_close OR freedom_close)",
      "violations": [
        { "id": "price_first_on_buy", "detect": "rep_named_price_before_prospect_on_buy", "severity": "critical", "label": "NAMED PRICE FIRST" },
        { "id": "menu_presented", "detect": "rep_offered_multiple_plays", "severity": "warning", "label": "MENU CLOSE (pick one)" }
      ]
    }
  },
  "moves": {
    "stroke": "Sincere recognition of legitimate pushback",
    "nurture": "Normalize the pain — 'a lot of owners in your spot deal with this'",
    "redirection": "Answer questions with questions. Negative phrasing to pull positive answers.",
    "takeaway": "Pull back when they're hot or posturing — 'honestly, maybe this isn't a fit'"
  }
}
```

**New file:** `src/lib/coach/staircases/cardone.json`

```json
{
  "methodology": "cardone",
  "display_name": "Grant Cardone Method",
  "steps": {
    "intro": {
      "label": "INTRO",
      "order": 1,
      "goal": "Establish identity, name the case, ask the hook question",
      "checklist": [
        { "id": "self_intro", "label": "Self-introduction (name + org)", "detect": "rep_name_and_org_in_transcript" },
        { "id": "asked_for_owner", "label": "Asked for owner by name", "detect": "rep_asked_for_name" },
        { "id": "hook_question", "label": "Hook question asked", "detect": "hook_question_in_transcript" },
        { "id": "prospect_engaged", "label": "Prospect engaged", "detect": "prospect_responded_not_hung_up" }
      ],
      "advance_when": "self_intro AND hook_question AND prospect_engaged"
    },
    "hook_interest": {
      "label": "HOOK + INTEREST",
      "order": 2,
      "goal": "Be interesting first, then get interested. Get them talking about their situation.",
      "checklist": [
        { "id": "rep_got_interesting", "label": "Rep led with something compelling", "detect": "rep_led_with_hook_not_pitch" },
        { "id": "prospect_talking", "label": "Prospect talking about their situation", "detect": "prospect_shared_context" }
      ],
      "advance_when": "prospect_talking"
    },
    "price": {
      "label": "PRICE",
      "order": 3,
      "goal": "State the fee/offer early, confidently, without mystery",
      "checklist": [
        { "id": "price_stated", "label": "Price/fee stated clearly", "detect": "price_stated" }
      ],
      "advance_when": "price_stated",
      "violations": [
        { "id": "price_stalling", "detect": "rep_avoided_price_when_asked", "severity": "critical", "label": "STALLING ON PRICE (mystery kills closes)" }
      ]
    },
    "objection_handling": {
      "label": "OBJECTION HANDLING",
      "order": 4,
      "goal": "For each objection: LISTEN → ACKNOWLEDGE → ISOLATE → MOVE → JUSTIFY → CLOSE AGAIN",
      "checklist": [
        { "id": "acknowledged", "label": "Acknowledged objection ('Got it.')", "detect": "objection_acknowledged" },
        { "id": "isolated", "label": "Isolated ('Other than that, anything else?')", "detect": "isolation_question_asked" },
        { "id": "moved_toward", "label": "Moved IN DIRECTION of objection", "detect": "rep_agreed_with_objection_logic" },
        { "id": "justified", "label": "Justified the offer", "detect": "rep_connected_offer_to_prospect_problem" },
        { "id": "closed_again", "label": "Closed again after handling", "detect": "close_attempt_after_objection" }
      ],
      "advance_when": "acknowledged AND isolated AND closed_again",
      "violations": [
        { "id": "re_pitched_on_objection", "detect": "rep_explained_more_instead_of_asking", "severity": "critical", "label": "RE-PITCH (ask a question instead)" },
        { "id": "argued_objection", "detect": "rep_contradicted_prospect_directly", "severity": "critical", "label": "ARGUED (never argue — redirect)" }
      ]
    },
    "close": {
      "label": "CLOSE",
      "order": 5,
      "goal": "One-call close. Lock commitment or get an honest no. Freedom close. No 'I'll think about it'.",
      "checklist": [
        { "id": "freedom_close", "label": "Freedom close used", "detect": "freedom_close_in_transcript" },
        { "id": "commitment_or_no", "label": "Commitment locked OR honest no received", "detect": "explicit_outcome_locked" }
      ],
      "advance_when": "freedom_close AND commitment_or_no",
      "violations": [
        { "id": "accepted_ill_think", "detect": "rep_accepted_think_about_it_without_isolating", "severity": "critical", "label": "ACCEPTED STALL (isolate and re-close)" }
      ]
    }
  },
  "moves": {
    "acknowledge": "Short, respectful: 'Got it.' — no argument",
    "isolate": "'Other than that, anything else stopping you?'",
    "move_in_direction": "Agree with the objection's logic, then reframe",
    "justify": "Connect the offer to their stated problem",
    "freedom_close": "'Totally your call — tell me no and I'm gone'"
  }
}
```

**New loader:** `src/lib/coach/loadStaircase.ts`

```typescript
import gutsStaircase from './staircases/guts.json'
import cardoneStaircase from './staircases/cardone.json'

export function loadStaircase(persona: 'guts' | 'cardone' | 'custom') {
  if (persona === 'cardone') return cardoneStaircase
  return gutsStaircase  // default for guts and custom
}
```

---

## 6. Database Migration

Add to Supabase — run in SQL editor or as a migration file:

```sql
-- Add coach config + coach state to calls table
ALTER TABLE calls
  ADD COLUMN IF NOT EXISTS coach_config JSONB,
  ADD COLUMN IF NOT EXISTS coach_enabled BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS script_persona TEXT,
  ADD COLUMN IF NOT EXISTS prospect_character TEXT,
  ADD COLUMN IF NOT EXISTS final_staircase_state JSONB,
  ADD COLUMN IF NOT EXISTS staircase_steps_completed INTEGER DEFAULT 0,
  ADD COLUMN IF NOT EXISTS violations_flagged TEXT[];

-- Index for filtering by persona
CREATE INDEX IF NOT EXISTS idx_calls_script_persona ON calls(script_persona);
```

Save `coach_config` (the full `PracticeSetup` object) to the call record at creation in `/api/calls/start/route.ts`.

Save `final_staircase_state` + `staircase_steps_completed` + `violations_flagged` when the call ends (in the call end handler in `VoiceCallInterface.tsx`).

---

## 7. Post-Call Scorecard Additions

**File to modify:** `src/app/dashboard/calls/[callId]/page.tsx`

After the existing score display, add a **Staircase Report** section IF `final_staircase_state` exists:

```
STAIRCASE PERFORMANCE — G.U.T.S.

Steps completed: 3/4
  ✓ Intro + Agenda
  ✓ Qualification
  ✓ Commitment
  ✗ Play + Close — not reached

Violations flagged:
  ⚠ PREMATURE PRESENTATION (2:14) — Explained the program before authority was confirmed
  ⚠ ACCEPTED STALL (4:02) — Accepted "I'll think about it" without isolating

Checklist completion by step:
  Intro+Agenda:     5/5 items ✓
  Qualification:    4/4 items ✓
  Commitment:       2/3 items (missed: prospect never named what winning looks like)
  Play+Close:       0/4 items (step not reached)
```

---

## Execution Order

Build in this order — each step is independently testable:

1. **DB migration** — run the SQL, verify columns exist
2. **Staircase JSON files** — create `src/lib/coach/staircases/guts.json` and `cardone.json`
3. **Staircase loader** — `src/lib/coach/loadStaircase.ts`
4. **Universal prospect prompt** — update `src/lib/prompts/promptBuilder.ts`, add `buildUniversalProspectPrompt()`
5. **Pre-call setup UI** — update `src/app/dashboard/practice/page.tsx`, add `PracticeSetup` state and picker UI
6. **Call start route** — update `/api/calls/start/route.ts` to save `coach_config` and return `configOverride`
7. **Coach analyze API** — create `/api/coach/analyze/route.ts` (3-node pipeline)
8. **Coach panel component** — create `src/components/voice/CoachPanel.tsx`
9. **Wire into active call page** — update `src/app/dashboard/practice/active/[callId]/page.tsx` to call analyze + render CoachPanel
10. **Post-call scorecard additions** — update `src/app/dashboard/calls/[callId]/page.tsx`

Test each step before moving to the next. The existing call/analysis/scoring flow must remain fully intact — this is additive only.

---

## Keys / Secrets

- OpenAI API key for Node 1/2/3 coach calls: use `process.env.OPENAI_API_KEY` (already in `.env.local`)
- ElevenLabs: already handled via signed URL in existing flow
- Never hardcode keys. Never log keys. Never put keys in client-side code.

---

## Files to NOT Touch

- `src/lib/analysis/callAnalyzer.ts` — post-call analysis, leave intact
- `src/app/api/calls/[callId]/analyze/route.ts` — post-call route, leave intact
- `src/lib/elevenlabs/connection.ts` — already works, don't modify
- Any auth, CSRF, or Supabase RLS logic
- `supabase/migrations/` — only add new migration, don't touch existing
