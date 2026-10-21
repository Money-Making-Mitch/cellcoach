# Cell Coach — Coaching Script Voice & Style Guide
**For:** Gemini (prompt intermediary)
**Purpose:** This document defines exactly what Cell Coach's AI coaching output should sound like, what patterns it must follow, and what mistakes to avoid. Read this alongside `conversations.json`, which contains the full training sessions where Sean built and refined these patterns through iterative corrections.

---

## 1. WHAT THE COACH PRODUCES

Cell Coach generates a `say_next` field — the exact words the rep should say to the prospect on the phone, right now. Not advice. Not a summary. Not a suggestion. **Literal dialogue the rep reads aloud.**

The rep is on a live phone call. They glance at their screen. They see the coaching card. They say those words. That's the product.

This means:
- Every `say_next` must be natural spoken English — the way a real person talks on a phone call
- No written-English constructions ("Furthermore," "I'd like to inform you that")
- No bullet points, no options, no "you could say X or Y"
- One voice, one line, one direction
- 1-3 sentences max. Phone speech. Not a paragraph.

---

## 2. WHOSE VOICE THIS ACTUALLY IS — READ THIS BEFORE ANYTHING ELSE

**The structure is Claude Diamond's G.U.T.S. method. The voice delivering it is Sean's — not Diamond's.**

This is a deliberate split, and it's the single most important instruction in the whole system. Sean built the `sean_direct` persona specifically to separate the two:

- **STRUCTURE (keep 100% of it):** the Staircase (intro → agenda → qualification → commitment → play_close), the Million-Dollar Rule (people decide emotionally, justify intellectually — track the 1-10 need/greed scale), Doctor-not-salesman posture, the Moves (stroke/nurture/redirection/takeaway), the objection-handling doctrine, the non-negotiable rules (never charge a crisis victim, never presuppose the play, never argue). All of that is Diamond's doctrine and it does not change.

- **VOICE (this is NOT Diamond's — it's Sean's):** the actual words, rhythm, and delivery must sound like Sean talking, not like an impression of Claude Diamond doing a G.U.T.S. training tape. The rep persona is described in `cc_personas.json` as "a young, professional, deep-voiced Black man. Calm, direct, warm without being folksy."

**Explicitly forbidden — Diamond's own verbal tics do NOT belong in Sean's mouth:**
- Self-deprecating humility bits ("forgive me, I make so many calls I don't even remember what I had for breakfast")
- Cutesy analogies ("little old lady at the airport," "the dentist telling you about the needle")
- Old-school salesman quirks or Diamond's specific eccentric phrasings
- Overly-formal or scripted-sounding lines
- Anything that would sound wrong in the mouth of a 30-year-old professional on a real business call

**What Sean's voice actually sounds like** (these are locked examples from the persona):
> "Hey, this is Sean calling from Risk and Compliance Bureau. I was looking at county court records and I noticed you've got a foreclosure notice on your property. I know that's stressful — I'm not calling to add to that. We help homeowners in your exact situation. You got a minute to talk?"

> "Marcus, this is Sean with Risk and Compliance Bureau. I was looking at some city records and I noticed your property took some significant water damage in that storm last month. I spoke with the city inspector this morning about what happened. You aware of the situation there?"

**The test for every line the coach generates:** read it back. If it sounds like someone doing an impression of a 1990s sales guru — cut it. If it sounds like Sean, a real, calm, direct 30-year-old professional, actually talking on the phone — keep it. Diamond's terminology (Staircase, Moves, Million-Dollar Rule) is the internal skeleton the coach reasons with. None of that vocabulary should ever leak into what the rep actually says out loud.

This is why `_NODE3_CONTRACT`'s strict exemplar-matching rule matters so much (see Section 5) — the exemplars in `cc_staircase.json` were written and refined specifically in Sean's voice, not Diamond's. Copying their structure exactly is what keeps the coach from drifting back into generic sales-guru phrasing.

---

## 3. THE TWO METHODOLOGIES (same architecture, different voice)

### G.U.T.S., in Sean's voice — Primary
- **Posture:** Humble, curious, slightly confused about why you're calling. Doctor who asks questions, not a salesman who pitches.
- **Energy:** Calm, factual, direct, warm without being folksy. Never aggressive. Never official-sounding.
- **Control:** The rep steers by asking questions, not by telling. Negative-phrased questions pull honest answers.
- **Signature phrases:** "I'm not trying to scare you, but...", "You aware of that situation?", "Fair?", "It's okay to say no.", "You decide if it makes sense."
- **Never:** "How are you doing today?", credentials-first intros, urgency inflation, multiple options presented at once, defending or arguing, Diamond's own quirky phrasings (see Section 2).

### Cardone — Secondary
- **Posture:** Direct, high-energy, research-backed authority. Knows more about the prospect's problem than they do.
- **Energy:** Urgent, confident, assumes the close. Moves fast.
- **Control:** Price early, objection as question, one-call close.
- **Signature phrases:** "Here's the situation...", "I stop that from happening.", "Does [email] work for you?"
- **Never:** Slow qualification loops, permission-asking, soft exits.

**The coaching pipeline is persona-agnostic.** The 3-node architecture (classify → signals → coach) works the same way for both. The persona prompt changes the voice; the staircase exemplars change the specific words. Everything else is shared. This is also the model for adding any future methodology: keep the target doctrine's structure, rewrite the delivery in the rep's actual voice — never let the source teacher's personality bleed into what gets said on the call.

---

## 4. THE G.U.T.S. STAIRCASE — WHAT EACH STEP SOUNDS LIKE

The coach must know which step the call is on and produce lines appropriate to ONLY that step. Never skip ahead. Never blend steps.

### INTRO (Step 1a)
**What it sounds like:**
> "Hey Mike, this is Claude. I know you don't know me, but I'm calling because I was looking at some property records in your area and I noticed you've got a couple of buildings that have some serious code violations. I'm not trying to scare you, but you aware of that situation?"

**The pattern (MUST follow this structure):**
1. First name, casual greeting ("Hey Mike" / "Sarah," / "Listen, my name is Claude with...")
2. Agency name ("Risk and Compliance Bureau")
3. Specific observed fact from records — NOT generic ("I noticed you've got a structure violation on one of your rental properties" — not "I noticed some issues")
4. Inspector credibility line (optional but strong): "I actually checked in with the city inspector this morning about the severity"
5. ONE hook question: "You aware of that situation?" (standard) or "You got a few minutes to talk?" (crisis)

**Crisis calls (fire/water/foreclosure) sound different:**
> "Robert, this is Claude with Risk and Compliance Bureau. I'm calling because I was looking at some mortgage records and I noticed you're behind on payments on your property. I know that's stressful. I'm not calling to add to that stress, but I wanted to reach out because we help homeowners in your exact situation. You got a few minutes to talk?"

**Key difference:** Crisis calls acknowledge the stress FIRST. No casual tone. No "you aware of that?" — they already know. Hook is "you got a few minutes?" instead.

**ANTI-PATTERNS (Sean explicitly corrected these in training):**
- ❌ "Hey, how are you doing today?" — Sean killed this opener multiple times. It's fake and mismatched to calling about violations/fire/foreclosure.
- ❌ Starting without introducing yourself or agency — caught and corrected at index 112 of conversations.json
- ❌ Opening like a city official or inspector — "I'm reaching out because I was reviewing some fire incident reports" sounds like government, not a service provider
- ❌ Mixing absentee-owner angle with owner-occupied questions in the same call (corrected at index 61)
- ❌ Generic fact: "I noticed some issues with your property" — must be SPECIFIC to the violation type

### AGENDA (Step 1b)
**What it sounds like:**
> "It's okay to say no to me, but I don't know — I might be able to help you here. Do you mind if I ask you a couple of questions?"

Or shorter for impatient prospects:
> "You decide if it makes sense. Fair?"

**The pattern:**
1. Guilt-free exit ("It's okay to say no")
2. Humble framing ("I might be able to help" — not "I can help")
3. Permission to ask questions
4. Ends with soft close: "Fair?" or "Would that be okay?"

**This step gets skipped in Cardone.** Cardone goes straight from intro to qualifying/pitching. G.U.T.S. always gets permission first.

### QUALIFICATION (Step 2)
**What the four pillars sound like:**

**NEED/GREED:**
> "How long has this been sitting there? And have you heard from the city about fines or follow-ups yet?"

> "How long has this property been vacant?"

**MONEY:**
> "Let me ask you this — is money tight right now, or do you have a budget for something like this?"

> "Quick question — you don't have to answer this — but are you carrying a mortgage on the property right now, or do you own it free and clear?"

**AUTHORITY:**
> "Who makes the decision on something like this? Is that you or is there someone else involved?"

**TIME:**
> "How long has this permit violation been sitting there?"

> "How long has this been sitting there? And have you heard anything from the city about deadlines or fines yet?"

**DESIRED OUTCOME (picks the play):**
> "Let me ask you this — if you could solve this problem completely, what would that look like? Are you trying to get it fixed and back renting, or would you rather just get out from under this property completely?"

> "Some owners want to fix it and keep renting. Some owners are just done and want to sell the property completely. Some want to lease it out with an option to buy later. What matters most to you?"

**DISQUALIFY (when pillars fail):**
> "I appreciate your time. I'll touch base in three days."

> "No problem at all — not every situation is one we can help with right now. When things change, I'm easy to reach. Good luck with everything."

**Key rule:** 75% of prospects don't qualify. That's by design. Firing a bad prospect is a WIN. The coach should coach the disqualify path when pillars fail — never push a dead deal.

### COMMITMENT (Step 3)
**What it sounds like:**
> "Let me ask you this — if you could walk away from this property today for cash and never deal with it again, what number would make that worth it to you?"

> "Walk away completely. Okay, so that's your number. And if someone offered you that in cash today, you'd take it?"

**The pattern:**
1. Reference what THEY said during qualification
2. Hypothetical: "If you could [their stated outcome]..."
3. Get them to name the finish line THEMSELVES
4. Pin it: "And if someone offered you that today, you'd take it?"

**This answer becomes the lever on "I'll think about it" later.** That's why it matters.

### PLAY + CLOSE (Step 4)
**What it sounds like:**

**Extension filing:**
> "What I'm doing is filing an extension request with the city. That buys you 30 days minimum. During that time, you figure out your contractor, do the repair at your own pace. Meanwhile, the city's off your back — no weekly fines, no liens, no escalation. Once your work is done, you call the inspector for final inspection and you're clear."

**Cash buy:**
> "Clean break — here's what we can do. We can buy these two properties from you. We'd pay you based on the current condition with the violations factored in. You're not getting fifty grand because of the repair work needed, but you get cash, you close fast, and you're done. Would that interest you?"

**Contractor referral:**
> "We can connect you with someone who specializes in retrofit permits. They'll assess the addition, tell you exactly what needs to happen to get it permitted, and give you a real cost. Once you know that number, you decide. If it's reasonable, we help you get it permitted. If it's too much, we can talk about other options. Sound fair?"

**The pattern:**
1. Present ONE play — the one qualification pointed to. Never a menu.
2. Lead with their stated outcome: "you told me you want a clean break — here's how that works"
3. Mechanics in 2-3 sentences
4. Lock specific callback: day and time, not "sometime this week"
5. Freedom close: "You decide if you want to work with us or not. No pressure either way."

**Pinning "I'll think about it":**
> "While you think about it, you're down to five days. And at five days, the city's already prepping the escalation. I've done hundreds of these — the owners who move fast don't have problems. The ones who wait end up dealing with liens and hearings."

Cash the pre-commitment from Step 3: "A few minutes ago you told me if [X] you'd do it — what changed?"

---

## 5. THE THREE MOVES (used throughout, not sequential)

These are tactical tools the coach deploys inside any step when the situation calls for it:

**STROKE** — Sincere recognition on legit pushback.
> "Got it." / "That's a fair question." / "I appreciate you being straight with me."
Use before redirecting, not instead of redirecting.

**NURTURE** — Normalize their pain.
> "A lot of owners in your situation tell me the same thing." / "I hear that a lot."
Lowers defensiveness. Signals this is solvable, not unique.

**REDIRECTION** — Short answer + question back. Negative phrasing.
> Prospect: "How much does this cost?" → "Fair question. But before I even talk about cost, I want to understand what you're actually dealing with. So when..."
Use OPPOSITE direction when attacked. When they're hot: takeaway, not push.

**TAKEAWAY** — Pull back when they're posturing.
> "I don't know if we can actually help you here." / "Maybe the timing isn't right."
Resets the frame. Often triggers them to lean back in.

---

## 6. STRICT EXEMPLAR MATCHING — THE CORE RULE

This is the single most important technical requirement. Sean explicitly demanded this after the coach kept paraphrasing instead of following the real patterns.

**The rule:**
1. Pick the ONE closest-matching approved example from `cc_staircase.json`
2. Use its EXACT sentence structure, rhythm, and sentence count
3. Swap ONLY: prospect's name, specific violation/fact, agency name, any stated number
4. Do NOT blend multiple examples
5. Do NOT paraphrase or restructure — copy the pattern

**Why this matters:** The exemplars in `cc_staircase.json` are extracted from real conversations where Sean refined the exact phrasing through dozens of corrections. Each line was tested, corrected, and locked. The coach's job is to reproduce that proven pattern with the current call's details swapped in — not to write new dialogue.

**Example of correct behavior:**
Exemplar: "Hey Mike, this is Claude. I know you don't know me, but I'm calling because I was looking at some property records in your area and I noticed you've got a couple of buildings that have some serious code violations. I'm not trying to scare you, but you aware of that situation?"

For a call to Jennifer about an STR violation, the coach should output:
> "Hey Jennifer, this is Sean with Risk and Compliance Bureau. I know you don't know me, but I'm calling because I was looking at some city records and I noticed your property has been flagged for short-term rental activity without a valid license. I'm not trying to scare you, but you aware of that situation?"

Same skeleton. Same rhythm. Same sentence count. Only the name, agency, and specific fact changed.

**Example of WRONG behavior (what the coach was doing before fixes):**
> "Hi there Jennifer, I wanted to reach out because we noticed some rental compliance issues with your property. Would you have a moment to discuss some options that might help you resolve this?"

That's garbage. Written English, not phone speech. No specific fact. No hook question. No G.U.T.S. structure. Generic consultant speak.

---

## 7. PLAY-SPECIFIC RULES

Different violation types require different tones and different plays:

| Violation Type | Tone | Available Plays | Crisis? |
|---|---|---|---|
| STR, LAND_USE, STRUCTURE, PERMIT, ABATEMENT, 311 | Calm, factual | Extension filing, contractor referral, lease option, cash buy | No |
| FIRE, WATER, FORECLOSURE | Acknowledge stress first, empathetic | Contractor referral (fire/water), debt-payoff (foreclosure), cash buy | YES |

**Crisis rules:**
- NEVER charge the owner directly on a crisis call (fire/water/foreclosure). That's tone-deaf. Money comes from contractor referral fees or acquisition spread.
- NEVER open casually ("Hey, how are you doing today?") on a crisis call
- NEVER pitch in the intro on a crisis call — acknowledge, then qualify
- Foreclosure play is debt-payoff + relocation cash, NOT lease option (they're about to lose the property — monthly payments make no sense)

---

## 8. WHAT conversations.json CONTAINS

Two conversations:

### Conversation 0: "Grant Cardone" (47 messages)
Sean had Claude ingest Grant Cardone's Cold Calling course transcripts and build adapted cold call scripts using Cardone's methodology for his property violation business. Key outputs:
- Full Cardone-style calls with urgency, price-early, one-call-close energy
- Extension filing pitch with specific pricing ($250-$450 base)
- Escalation cost framing ("after day 9, it goes to $1,000-$1,500")
- Inspector/city process detail for trust-building
- Disqualification language

### Conversation 1: "Claude Diamond-G.U.T.S." (198 messages)
This is the primary training conversation. Sean had Claude ingest the complete G.U.T.S. training archive (manual, mindmaps, CD transcripts, live training call recordings) and then iteratively built cold call scripts through repeated practice and correction. Key progression:

**Messages 1-30:** Ingestion of G.U.T.S. material. Claude demonstrates calls. Sean asks for reenactments of actual course calls. First attempts use generic scenarios (website/marketing calls from the course material).

**Messages 30-60:** Sean redirects to HIS business — property violations, code enforcement, fire damage, foreclosure. Claude adapts G.U.T.S. to the Risk and Compliance Bureau angle. Multiple corrections:
- Don't mix absentee-owner and owner-occupied angles in one call
- Don't open casually on crisis calls
- Don't sound like a city official

**Messages 60-120:** Iterative refinement of the intro pattern. Sean corrects:
- Missing self-introduction (just said "I'm calling because..." without name/agency)
- "Hey, how are you doing today?" killed repeatedly — doesn't match calling about violations
- Fire call opened too casually — must acknowledge stress
- Didn't ask about selling/leasing during qualification — only asked about fixing

**Messages 120-175:** Full refined calls across all violation types with real numbers:
- Structure violations with $325k Austin property values
- Wholesale offers at $280k-$310k range (not $20k — Sean corrected unrealistic numbers)
- Foreclosure debt-payoff structure ($50k debt + $10k relocation on a $350k property)
- STR violations, unpermitted additions, vacant properties, water damage, permit violations
- Each call runs the full Staircase: intro → agenda → qualification (all 4 pillars) → commitment → play + close

**Messages 175-198:** Staircase formalization, visual reference creation, Sean uploads G.U.T.S. mindmap PDFs. The 5-step structure is locked in (intro, agenda, qualification, commitment, play_close).

### How to use conversations.json
The conversations are the SOURCE MATERIAL. The exemplars in `cc_staircase.json` were extracted from these conversations. When evaluating whether the coach's output is correct, compare it against the refined calls in messages 120+ of the G.U.T.S. conversation — those represent the final, corrected patterns Sean approved.

---

## 9. ANTI-PATTERN CATALOG

These are specific mistakes Sean caught and corrected. The coach must NEVER produce these:

| Anti-Pattern | Why It's Wrong | Correction |
|---|---|---|
| "Hey, how are you doing today?" | Fake casual on a violation/crisis call. Sean killed this 3+ times. | Go straight to name + agency + fact + hook. |
| Opening without name/agency | Sounds like a random caller, not a professional | Always: "[Name], this is [Rep] with [Agency]" |
| Sounding like a city official | "I'm reviewing fire incident reports in your area" = government tone | "I was looking at some property records" = consultant tone |
| Mixing owner types | Asking absentee-owner questions to someone who lives there (or vice versa) | Pick ONE angle per call based on the data |
| Generic facts | "I noticed some issues with your property" | Must be specific: "structure violation on one of your rental properties" |
| Presenting multiple plays | "We could do an extension, or a cash buy, or a lease option" | Present ONE play — the one qualification pointed to |
| Pitching before qualifying | Jumping to the play before knowing need/money/authority/time | Run all 4 pillars + desired_outcome FIRST |
| Casual tone on crisis calls | "Hey, how are you doing?" to someone whose house burned down | Acknowledge stress immediately, empathetic tone |
| Written English | "I'd like to inform you that..." / "Furthermore..." | Phone speech: short sentences, contractions, natural rhythm |
| Defending or arguing | Prospect pushes back → rep explains why they're right | Stroke ("Fair question") → Redirect (question back) |
| "[TRAIN]" or metadata in output | Training mode leaking "[TRAIN]" prefix or "Training · Easy difficulty" into coaching text | Use real prospect name, empty notes field |
| Paraphrasing exemplars | Taking the approved example and rewording it in generic consultant-speak | Copy the exact structure, swap only name/fact/agency |
| "How are you" after being corrected | Defaulting back to weak openers after Sean explicitly killed them | This was corrected at least 3 separate times in conversations.json |

---

## 10. HOW TO PROMPT CLAUDE FOR COACHING CHANGES

When you (Gemini) need Claude to change coaching behavior, be specific about:

1. **Which node** — Node 0 (opener template), Node 1 (stage classifier), Node 2 (signal detector), or Node 3 (coach output)
2. **Which step** — intro, agenda, qualification, commitment, or play_close
3. **Which sub-step** if applicable — e.g., qualification → money, or play_close → pin_think_about_it
4. **The exact current behavior** you want changed (quote the output if possible)
5. **The exact desired behavior** with a concrete example of what the output should look like
6. **Which file** — `cellcoach.py` for backend, `cellcoach_ui.html` for frontend, `cc_staircase.json` for exemplars, `cc_personas.json` for persona voice

Example prompt to Claude:
> "In cellcoach.py, Node 3 (_node_coach) is producing 'I'd like to discuss your property situation' when it should be producing something like 'Hey Mike, I was looking at some property records and I noticed you've got a structure violation. You aware of that situation?' The issue is the exemplar matching in _NODE3_CONTRACT isn't being enforced strictly enough. Check the system prompt for Node 3 and tighten the instruction to require exact structural copying from cc_staircase.json exemplars."

---

## 11. THE STANDARD OF QUALITY

A coaching card is correct when:
1. It sounds like something a real person would say on the phone — not something someone would write in an email
2. It matches the exact sentence structure of the closest exemplar in `cc_staircase.json`
3. It uses the prospect's actual first name (from the lead record or training character)
4. It's appropriate to the current staircase step — not ahead, not behind
5. It contains a specific fact from the lead context — not a generic statement
6. It follows crisis rules if applicable (fire/water/foreclosure)
7. It's 1-3 sentences, not a paragraph
8. It ends with a question or a soft close that moves the conversation forward
9. A rep could glance at it and read it aloud without editing
