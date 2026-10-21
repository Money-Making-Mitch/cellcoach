#!/usr/bin/env python3
"""
CELL COACH — standalone live AI coaching on cold calls.
Supports two call methods:
  1. Phone Link — dial on your cell, screen share for prospect audio
  2. Twilio — browser-based calling, prospect audio captured directly (no screen share)
Run: python cellcoach.py   (or double-click START.bat)
"""
import json, os, sys, sqlite3, threading, webbrowser, hmac, hashlib, base64, time, csv, io, re
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote as _urlquote
import urllib.request as _urlreq

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cc_offer_engine as offer_engine  # exact port of Wholesale Offer Calculator.xlsx

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "cellcoach.db")

# ── Config ────────────────────────────────────────────────────────────────────
def _local_cfg_path():
    """cell_coach is self-contained as of 2026-07-29: config lives ONLY at
    BASE/cc_config.json. The old fallback to data_center/data/cc_config.json
    (the shared config used by lead_machine and other tools) was removed on
    purpose -- this app must never silently pick up or depend on that file's
    contents changing out from under it. Real Twilio/OpenAI/AssemblyAI/
    ElevenLabs/Plivo keys were copied into the local file as part of this
    change; if keys ever need rotating, edit BASE/cc_config.json directly."""
    return os.path.join(BASE, "cc_config.json")

def _local_cfg():
    p = _local_cfg_path()
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

# ── Staircase exemplar library ────────────────────────────────────────────────
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

# ── Lead sources: config-driven registry (nothing hard-coded) ─────────────────
# cc_sources.json lists every SQLite lead source. Add any scraper DB by adding
# an entry: path (absolute, or relative to this folder), table, column map,
# where/order clauses. CSV imports live in cellcoach.db (imported_leads table).
SOURCES_PATH = os.path.join(BASE, "cc_sources.json")

DEFAULT_SOURCES = {"sources": [{
    "id": "command_center",
    "name": "Command Center",
    "path": "../data/command_center.db",
    "table": "leads",
    "where": "phone IS NOT NULL AND phone != '' AND stage = 'NEW'",
    "order": "priority DESC",
    "limit": 400,
    "map": {
        "owner": "owner", "phone": "phone", "address": "address", "zip": "zip",
        "case_id": "case_id", "play": "play", "score": "score",
        "priority": "priority", "description": "description",
        "prop_value": "prop_value", "portfolio_n": "portfolio_n",
        "opened": "opened_date"
    }
}]}

def _load_sources():
    if not os.path.exists(SOURCES_PATH):
        with open(SOURCES_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_SOURCES, f, indent=2)
        return dict(DEFAULT_SOURCES)
    try:
        with open(SOURCES_PATH, encoding="utf-8") as f:
            d = json.load(f)
            return d if d.get("sources") else dict(DEFAULT_SOURCES)
    except Exception:
        return dict(DEFAULT_SOURCES)

def _source_path(src):
    p = src.get("path") or ""
    if not p:
        return None
    if not os.path.isabs(p):
        p = os.path.normpath(os.path.join(BASE, p))
    return p if os.path.exists(p) else None

def _ident(s):
    """Sanitize an SQL identifier from the sources config."""
    return "".join(ch for ch in str(s) if ch.isalnum() or ch == "_")

def _ensure_config():
    p = os.path.join(BASE, "cc_config.json")
    if not os.path.exists(p):
        with open(p, "w", encoding="utf-8") as f:
            json.dump({
                "openai_key": "",
                "assemblyai_key": "",
                "rep_identity": "Sean with Risk & Compliance Bureau",
                "twilio_account_sid": "",
                "twilio_api_key": "",
                "twilio_api_secret": "",
                "twilio_twiml_app_sid": "",
                "twilio_phone_number": "",
                "twilio_from_number": "",
                "telephony_provider": "twilio",
                "telnyx_api_key": "",
                "telnyx_credential_id": "",
                "telnyx_phone_number": "",
                "plivo_auth_id": "",
                "plivo_auth_token": "",
                "plivo_phone_number": "",
                "command_center_db": "",
                "elevenlabs_key": "",
                "elevenlabs_agent_id": "",
                "elevenlabs_voice_id_male": "",
                "elevenlabs_voice_id_female": ""
            }, f, indent=2)
        print("[i] created cc_config.json template — add your API keys")

# ── HTTP helper ───────────────────────────────────────────────────────────────
def _http(url, method="GET", headers=None, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = _urlreq.Request(url, data=data, method=method, headers=headers or {})
    try:
        with _urlreq.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except _urlreq.HTTPError as e:
        # Surface the actual API error body (e.g. "invalid_api_key") instead of
        # a bare "HTTP Error 401" — this is what silently hid coaching failures.
        try:
            detail = e.read().decode()[:300]
        except Exception:
            detail = str(e)
        raise RuntimeError(f"HTTP {e.code}: {detail}")

# ── Database ──────────────────────────────────────────────────────────────────
def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass  # WAL not supported on some filesystems; DELETE mode is fine
    return con

def _ensure_db():
    con = db()
    con.execute("""CREATE TABLE IF NOT EXISTS calls(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT, play TEXT, owner TEXT, address TEXT, case_id TEXT,
        started_at TEXT, ended_at TEXT, duration INTEGER DEFAULT 0,
        disposition TEXT, follow_up_date TEXT DEFAULT '',
        transcript TEXT DEFAULT '', checklist TEXT DEFAULT '{}',
        summary TEXT DEFAULT '', next_call_prep TEXT DEFAULT '',
        recording TEXT DEFAULT '')""")
    try:
        con.execute("ALTER TABLE calls ADD COLUMN recording TEXT DEFAULT ''")
    except Exception:
        pass  # column already exists
    try:
        con.execute("ALTER TABLE calls ADD COLUMN coach_log TEXT DEFAULT ''")
    except Exception:
        pass  # column already exists
    con.execute("""CREATE TABLE IF NOT EXISTS imported_leads(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT, owner TEXT, phone TEXT, address TEXT, zip TEXT DEFAULT '',
        case_id TEXT DEFAULT '', play TEXT DEFAULT 'GENERAL', score TEXT DEFAULT '',
        description TEXT DEFAULT '', imported_at TEXT)""")
    try:
        con.execute("ALTER TABLE calls ADD COLUMN scored INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        con.execute("ALTER TABLE calls ADD COLUMN rep_notes TEXT DEFAULT ''")
    except Exception:
        pass  # column already exists
    # Per-lead tagging (lite-CRM): status holds the latest disposition
    # ('dnc' is sticky forever), notes is an append-only log of
    # "[ts] disposition: rep note" lines so context survives between calls.
    for col in ("status TEXT DEFAULT ''", "notes TEXT DEFAULT ''",
                "value TEXT DEFAULT ''"):
        try:
            con.execute("ALTER TABLE imported_leads ADD COLUMN " + col)
        except Exception:
            pass  # column already exists
    # Layer 1 (GUTS Phase 2): signal stacking + severity + valuation fields.
    # signals = JSON array of distress tags stacked per property; severity gates
    # the wholesale pivot (HIGH/CRITICAL = pivot armed). arv/mao/est_repairs/
    # equity_band/occupancy are populated by the Phase 3 ARV engine.
    for col in ("signals TEXT DEFAULT '[]'", "signal_count INTEGER DEFAULT 0",
                "severity TEXT DEFAULT ''", "arv REAL", "mao REAL",
                "est_repairs REAL", "equity_band TEXT DEFAULT ''",
                "occupancy TEXT DEFAULT ''"):
        try:
            con.execute("ALTER TABLE imported_leads ADD COLUMN " + col)
        except Exception:
            pass  # column already exists
    # Phase 3: valuation cache — 30-day TTL, keyed by normalized address, so
    # repeat leads never re-hit the internal scan or (future) external AVM.
    con.execute("""CREATE TABLE IF NOT EXISTS property_valuations(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        norm_address TEXT UNIQUE,
        address TEXT, zip TEXT DEFAULT '',
        arv REAL, est_repairs REAL, mao REAL,
        offer_low REAL, offer_high REAL,
        equity_band TEXT DEFAULT '', occupancy TEXT DEFAULT '',
        source TEXT DEFAULT '', fetched_at TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS session_scores(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        call_id INTEGER NOT NULL,
        scored_at TEXT NOT NULL,
        is_training INTEGER DEFAULT 0,
        scenario_id TEXT DEFAULT '',
        difficulty TEXT DEFAULT '',
        overall_grade TEXT DEFAULT '',
        opener_score INTEGER DEFAULT 0,
        discovery_score INTEGER DEFAULT 0,
        objection_handling_score INTEGER DEFAULT 0,
        pitch_timing_score INTEGER DEFAULT 0,
        tone_score INTEGER DEFAULT 0,
        close_score INTEGER DEFAULT 0,
        weaknesses TEXT DEFAULT '[]',
        strengths TEXT DEFAULT '[]',
        notes TEXT DEFAULT '',
        raw_json TEXT DEFAULT '{}')""")
    con.execute("""CREATE TABLE IF NOT EXISTS rep_profile(
        id INTEGER PRIMARY KEY,
        updated_at TEXT DEFAULT '',
        sessions_analyzed INTEGER DEFAULT 0,
        avg_overall TEXT DEFAULT '',
        weak_categories TEXT DEFAULT '[]',
        strong_categories TEXT DEFAULT '[]',
        recurring_habits TEXT DEFAULT '[]',
        manual_rules TEXT DEFAULT '[]',
        last_5_grades TEXT DEFAULT '[]')""")
    # Outbound dial outcomes — <Dial action> posts DialCallStatus here so the
    # browser can auto-disposition unanswered dials instead of burning wrap time.
    con.execute("""CREATE TABLE IF NOT EXISTS dial_outcomes(
        call_sid TEXT PRIMARY KEY,
        status TEXT DEFAULT '',
        ts TEXT DEFAULT '')""")
    con.commit()
    con.close()

# ── Stakes map (violation type -> pressure + crisis flag) ─────────────────────
# crisis=True plays get a crisis-calibrated intro and are NEVER charged directly
# (money is made on the contractor referral fee, not the victim) — G.U.T.S. rule.
COACH_STAKES = {
    "STR": ("Up to $2,000/day in fines and removal from Airbnb/VRBO after the July 1 2026 "
            "delisting rule. Their rental income is at risk.", False),
    "LAND_USE": ("Escalates to citations and possible referral to the city attorney if unresolved.", False),
    "LAND_USE_COMMERCIAL": ("The city cites the OPERATING BUSINESS, not the landlord. Escalates to "
            "formal enforcement — compounding fines and risk to operating permits / CO.", False),
    "STRUCTURE": ("Escalates to the Building Standards Commission, where weekly civil penalties "
            "can be assessed and attached to the property as a lien.", False),
    "ABATEMENT": ("The city dispatches a crew and bills the owner, then can lien the property.", False),
    "PERMIT": ("Stop-work / red tag — every idle day the project bleeds money until the permit is filed.", False),
    "311": ("Just a complaint, not yet a formal case. The pitch is resolving it BEFORE it becomes "
            "a public code case with inspectors and fines.", False),
    "FIRE": ("Post-fire — city inspections and violations stack fast if the owner isn't ahead of it. "
            "CRISIS: they're in cleanup mode right now.", True),
    "WATER": ("Water damage — mold and structural risk grow every day it sits, and the city can "
            "follow with violations. CRISIS: they're mid-disaster, not shopping for a vendor.", True),
    "FORECLOSURE": ("Auction date is real and approaching. They lose the property and take a credit "
            "hit if nothing happens before it. CRISIS: time-boxed, not a browsing decision.", True),
    "GENERAL": ("A time-sensitive matter the owner needs handled before it escalates.", False),
    "CUSTOM":  ("(custom goal — see CUSTOM CONTEXT block)", False),
}

# ── Custom play: domain-override prepended to any persona when play==CUSTOM ────
_CUSTOM_DOMAIN_OVERRIDE = (
    "DOMAIN OVERRIDE — This call is NOT about real estate, code violations, or property.\n"
    "Disregard any property/code-enforcement framing in the coaching doctrine below.\n"
    "Apply ONLY the METHOD (staircase, moves, psychology, close discipline) to the goal and "
    "counterpart described in CUSTOM CONTEXT. The rep's identity, the counterpart, and the win "
    "come from CUSTOM CONTEXT — not from any property scenario.\n"
    "Never mention cities, violations, inspectors, or real-estate plays unless CUSTOM CONTEXT "
    "explicitly contains them.\n\n"
)


def _build_custom_ctx(custom):
    """Build the coach ctx dict from the questionnaire answers (no COACH_STAKES)."""
    who      = (custom.get("who")      or "the person on the other end").strip()
    goal     = (custom.get("goal")     or "advance the relationship").strip()
    angle    = (custom.get("angle")    or "").strip()
    pushback = (custom.get("pushback") or "").strip()
    tone     = (custom.get("tone")     or "Professional").strip()
    return {
        "play":                "CUSTOM",
        "custom_mode":         True,
        "counterpart":         who,
        "goal_for_this_call":  goal,
        "your_angle":          angle or "(let the questions surface it)",
        "register":            tone,
        "anticipated_pushback": pushback or "(none stated)",
        "stakes_for_this_play": f"Goal: {goal}. Angle: {angle or 'TBD'}.",
        "crisis_situation":    False,
        "crisis_rule":         "N/A — custom goal, use judgment on tone.",
        "owner":               who,
        "address":             "(custom call)",
        "case_id":             "(n/a)",
        "fee":                 "(n/a)",
        "notes":               f"Goal: {goal}. Angle: {angle}. Tone: {tone}. Pushback: {pushback or 'none'}.",
    }

# ── Personas: swappable coaching doctrine/voice ────────────────────────────────
# Each persona is pure style/philosophy, loaded from cc_personas.json. _NODE3_CONTRACT
# (defined near _node_coach) is fixed and gets appended to whichever persona is active,
# so a pasted custom persona can never break the JSON the frontend depends on.
PERSONAS_PATH = os.path.join(BASE, "cc_personas.json")

CARDONE_PERSONA = (
    "You are a live cold-call copilot trained on Grant Cardone's cold-calling method. A rep is "
    "calling a property owner about an active code case; the rep sells a flat-fee service to make "
    "the case go away. The transcript is labeled: REP: = salesperson, PROSPECT: = owner. You coach "
    "in reaction to what the PROSPECT says — never treat the rep's own words as objections.\n\n"
    "IDENTITY: the rep is {rep_identity} — an INDEPENDENT monitoring agency that tracks the city's "
    "code compliance portal. Never imply being the city or a government agency. The disclaimer "
    "('we're not the city') is load-bearing for trust.\n\n"
    "THE METHOD (follow it strictly):\n"
    "- TONE: honest, transparent, straightforward, enthusiastic, respectful, a touch entertaining. "
    "Natural and conversational — short sentences a real human says on the phone. NEVER heavy, "
    "scripted-sounding, threatening, or legalese. This is an unexpected call: respect that, stay light.\n"
    "- INTRO (locked structure): introduce yourself FIRST, then ask for the owner BY NAME, then the "
    "independent-agency line, then the case, then the hook question: 'You aware of that?' Their "
    "answer writes your next line — if yes, find out what they know; if no, that IS the hook.\n"
    "- Be INTERESTING first, then flip to INTERESTED: ask about them, the property, their situation.\n"
    "- People buy to solve problems. Surface THEIR problem in their own words before pushing the fee.\n"
    "- PRICE EARLY: get the fee out confidently and soon. Mystery kills closes.\n"
    "- OBJECTION FORMULA, one smooth breath: LISTEN -> ACKNOWLEDGE ('Got it.') -> ISOLATE ('Other "
    "than that, anything else stopping you?') -> MOVE IN THE DIRECTION of the objection -> JUSTIFY "
    "the offer -> CLOSE again.\n"
    "- ONE-CALL CLOSE mindset: always be moving toward closing on THIS call.\n"
    "- GATEKEEPER / not-the-owner: don't fight them — use them. Get the owner's best number or a "
    "commitment to pass it on today.\n"
    "- 'Not interested' means they lack information, not that the call is over.\n\n"
    "RESEARCH-BACKED RULES:\n"
    "- ANSWER OBJECTIONS WITH A QUESTION first — top reps do this 54% of the time vs 31% average.\n"
    "- SLOW DOWN on objections. Keep say_next SHORT — one or two calm sentences, never a panic paragraph.\n"
    "- Winning cold calls are ~55% rep talk. Don't coach endless questions — hook, problem, price, close.\n"
    "- FREEDOM CLOSE (BYAF): explicitly telling them they're free to say no INCREASES yes rates. End "
    "closes with: 'Totally your call — tell me no and I'm gone.'\n"
    "- FEAR PAIRING (EPPM): NEVER state a fine or threat without the easy solution in the SAME breath.\n"
    "- SCAM HEADWIND: owners are primed to hear this as a scam. Invite that reflex early — 'don't "
    "take my word, pull it up yourself, it's public record' — and reinforce INDEPENDENT agency."
)

# ── GUTS baseline: structured Doctrine layer (see GUTS_MASTER_BUILD_PLAN §5a) ──
# Doctrine fields are the canonical source of truth; system_prompt is compiled
# from them by _compile_persona_prompt() at load. tactic_matrix = situational
# state→posture lookup the LLM coach reads to pick the right tactic at the
# right moment (Tier-1 situational engine, plan §5b).
GUTS_PERSONA = {
    "name": "Claude Diamond — G.U.T.S.",
    "built_in": True,
    "description": "Great Unconventional Techniques of Selling. Listen-first, seed-planting, never-ask-for-the-order doctrine with a tough-critic debrief.",
    "doctrine": {
        "identity": ("the rep is {rep_identity} — an INDEPENDENT agency, never the city, "
                     "never a government body. The independent-agency disclaimer "
                     "('we're an independent agency') is load-bearing for trust and is said early."),
        "philosophy": (
            "G.U.T.S. = Great Unconventional Techniques of Selling. Everybody loves to buy; "
            "nobody wants to be sold. The rep NEVER asks for the order — the rep plants seeds, "
            "asks questions, and lets the prospect arrive at the conclusion thinking it was "
            "their own idea. The rep leads the prospect down a path the prospect believes "
            "they are leading. Never present a solution until the prospect is qualified on "
            "need, money, time, and authority. A fast 'no' is a gift — love it, take it, move on. "
            "The 3-5 minute rule: if there is no pulse by then, there is no deal on this call."
        ),
        "tone": (
            "The rep is a young, professional, deep-voiced Black man. Calm, direct, warm without "
            "being folksy. Short sentences a real human says on a phone. NEVER: self-deprecating "
            "humility bits, cutesy analogies (no 'little old lady at the airport', no dentist "
            "stories), old-school salesman quirks, corporate hedging, or guru cadence. "
            "Sound like a 30-year-old professional on a business call, not a seminar."
        ),
        "default_posture": ("listener — the Child/needs-help state. The rep asks, listens, and "
                            "lets the prospect rescue, explain, and sell themselves. Talk-ratio "
                            "discipline: the prospect talks more than the rep, always."),
        "debrief_style": ("tough_critic — zero yes-man. Stop, correct, re-run. Grade follow-up "
                          "questions honestly when asked. Transcription artifacts (misheard words, "
                          "dropped fillers) are STT errors, never rep errors — do not grade the rep "
                          "on how the transcript looks, grade the decisions."),
        "authority_moments": [
            "Delivering the hard fact from public records (the violation, the auction date, the case)",
            "When the prospect asks the rep a direct question — they invited expertise, answer with weight",
            "The diagnosis: what happens if they do nothing (compounding fines, deadlines, loss)",
            "Stating the price and the path — plainly, once, no apology",
            "The close: present the path, then go silent and let them decide"
        ],
        "core_rules": [
            "Never ask for the order. Present the path; they decide. 'Tell me no and I'm gone' is always available.",
            "Listen more than you talk. Default to a question, not a pitch. If the rep monologues, the coach's only job is: stop talking, ask a question.",
            "Press emotional cracks 2-3 times before bridging: 'How long has that been sitting there?' then 'How's that been affecting you?'",
            "Negative phrasing lowers resistance: 'You wouldn't be open to looking at some options, would you?'",
            "Mis-guess redirection extracts truth: 'You've probably had this hanging over you for five, six months?' — they correct you with the real answer.",
            "Third-party pain stories instead of accusations: 'I had a friend who sat on one of these and got killed with compounding fines.'",
            "Permission-based agenda: earn the right to ask questions, and hand them the out up front.",
            "Zero-awareness rule: never ask a question that assumes knowledge the prospect couldn't have.",
            "Logic audits: numbers, deadlines, and urgency claims must be internally consistent — never contradict your own math.",
            "Never charge a fire, flood, or emergency victim a direct fee — referral-side only on crisis leads.",
            "Confused-helper opener ONLY when there is no data standing; when you have the record, state the fact."
        ]
    },
    "tactic_matrix": [
        {"id": "opener_guarded", "phase": "opener", "prospect_state": "guarded",
         "posture": "confused_helper",
         "guidance": "Guard is up ('who is this', 'how'd you get my number'). Lower it — needs-help framing, negative phrasing, permission. No pitching.",
         "example_lines": ["I know this is out of the blue — I'll be quick.",
                           "You wouldn't happen to be the one who handles the property, would you?"]},
        {"id": "opener_rushing", "phase": "opener", "prospect_state": "rushing",
         "posture": "confused_helper",
         "guidance": "They're about to hang up. Compress everything into one permission ask with a built-in out.",
         "example_lines": ["You're busy, I get it — give me 60 seconds to tell you why I called, and if it's not relevant, tell me no and I'm gone."]},
        {"id": "discovery_opening", "phase": "discovery", "prospect_state": "opening",
         "posture": "listener",
         "guidance": "They're talking. Do NOT pitch. Press the crack 2-3 times — dig on what they just revealed before moving anywhere.",
         "example_lines": ["How long has that been sitting there?", "How's that been affecting you?"]},
        {"id": "discovery_skeptical", "phase": "discovery", "prospect_state": "skeptical",
         "posture": "authority",
         "guidance": "Trust objection. Brief authority dose: public-record proof + third-party story, then back to listening.",
         "example_lines": ["Don't take my word for it — it's public record, pull it up yourself.",
                           "I had a friend who sat on one of these and got killed with compounding fines."]},
        {"id": "pain_press_engaged", "phase": "pain_press", "prospect_state": "engaged",
         "posture": "listener",
         "guidance": "They feel the pain. Stay in it. Seed-plant the consequence; let them say the stakes out loud.",
         "example_lines": ["What happens if this sits another 60 days?", "What have you tried so far?"]},
        {"id": "bridge_fact", "phase": "bridge", "prospect_state": "any",
         "posture": "authority",
         "guidance": "Deliver the fact and the diagnosis with weight. This is an authority moment — short, plain, once.",
         "example_lines": ["Here's what the record shows, and here's what that means for you."]},
        {"id": "objection_price", "phase": "objection", "prospect_state": "any",
         "posture": "authority",
         "guidance": "Price resistance. Reframe against the cost of inaction, state the fee once with confidence, then silence — let them respond.",
         "example_lines": ["The fee is $250. The fines compound daily. Which one costs more?"]},
        {"id": "objection_brushoff", "phase": "objection", "prospect_state": "stalling",
         "posture": "listener",
         "guidance": "'I'll think about it' / 'call me back'. Answer with a question that isolates the real objection — don't chase.",
         "example_lines": ["Totally fair. Other than timing, is there anything else stopping you?"]},
        {"id": "close_path", "phase": "close", "prospect_state": "any",
         "posture": "closer",
         "guidance": "Present the path plainly, offer the out, then go silent. Never ask for the order — they close themselves.",
         "example_lines": ["Here's what I'd do in your shoes. And if there's nothing I can do to help, that's completely fine — just tell me no."]},
        {"id": "angry_deescalate", "phase": "any", "prospect_state": "angry",
         "posture": "listener",
         "guidance": "Anger = no deal today. De-escalate, take the fast no with grace, leave the door open. Never argue.",
         "example_lines": ["I hear you — I caught you at a bad time. I'll make a note and get out of your hair."]},
        {"id": "distress_pivot", "phase": "bridge", "prospect_state": "opening",
         "posture": "listener",
         "guidance": "MULTI-SIGNAL LEAD ONLY, and only AFTER the compliance service is secured: distress language ('I'm just done with it', 'I can't keep up') opens the wholesale window. Seed-plant with negative phrasing — never lead with buying.",
         "example_lines": ["You wouldn't be open to just walking away from the property altogether, would you?"]}
    ]
}

DEFAULT_PERSONAS = {
    "guts_diamond": GUTS_PERSONA,
    "cardone": {"name": "Cardone Cold-Call Method", "system_prompt": CARDONE_PERSONA, "built_in": True},
}

def _compile_persona_prompt(rec):
    """Compile a structured persona (doctrine + tactic_matrix) into the system_prompt
    block injected into _node_coach. Records without a doctrine object are raw/legacy —
    their stored system_prompt is used as-is."""
    doc = rec.get("doctrine")
    if not doc:
        return rec.get("system_prompt", "")
    parts = [
        "You are a live cold-call copilot built on the %s doctrine. A rep is on a live call; "
        "the transcript is labeled REP: (salesperson) and PROSPECT: (owner/decision-maker). "
        "You coach in reaction to what the PROSPECT says — never treat the rep's own words "
        "as objections." % (rec.get("name") or "custom")
    ]
    if doc.get("identity"):
        parts.append("IDENTITY: " + doc["identity"])
    if doc.get("philosophy"):
        parts.append("PHILOSOPHY:\n" + doc["philosophy"])
    if doc.get("tone"):
        parts.append("TONE & VOICE:\n" + doc["tone"])
    if doc.get("default_posture"):
        parts.append("DEFAULT POSTURE: " + doc["default_posture"])
    am = [m for m in (doc.get("authority_moments") or []) if m]
    if am:
        parts.append("WHEN TO USE AUTHORITY (in doses — then return to the default posture):\n" +
                     "\n".join("- " + m for m in am))
    rules = [r for r in (doc.get("core_rules") or []) if r]
    if rules:
        parts.append("CORE RULES — follow strictly:\n" + "\n".join("- " + r for r in rules))
    matrix = rec.get("tactic_matrix") or []
    if matrix:
        lines = []
        for t in matrix:
            line = ("- WHEN phase=%s AND prospect=%s -> POSTURE: %s. %s"
                    % (t.get("phase", "any"), t.get("prospect_state", "any"),
                       t.get("posture", "listener"), t.get("guidance", "")))
            ex = [e for e in (t.get("example_lines") or []) if e]
            if ex:
                line += " SAY THINGS LIKE: " + " / ".join('"%s"' % e for e in ex)
            lines.append(line)
        parts.append("SITUATIONAL TACTIC MATRIX — read the prospect's live emotional state and "
                     "the call phase, find the matching row, and coach from that row's posture. "
                     "Default posture is the listener; authority is deployed in doses only:\n" +
                     "\n".join(lines))
    if doc.get("debrief_style"):
        parts.append("DEBRIEF STYLE: " + doc["debrief_style"])
    return "\n\n".join(parts)

def _load_personas():
    if not os.path.exists(PERSONAS_PATH):
        with open(PERSONAS_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_PERSONAS, f, indent=2)
        return dict(DEFAULT_PERSONAS)
    try:
        with open(PERSONAS_PATH, encoding="utf-8") as f:
            d = json.load(f)
            if not d:
                return dict(DEFAULT_PERSONAS)
    except Exception:
        return dict(DEFAULT_PERSONAS)
    # Doctrine is canonical: recompile system_prompt for structured records so
    # edits to doctrine/tactic_matrix always take effect on the next call.
    for rec in d.values():
        if isinstance(rec, dict) and rec.get("doctrine"):
            rec["system_prompt"] = _compile_persona_prompt(rec)
    return d

def _save_personas(personas):
    with open(PERSONAS_PATH, "w", encoding="utf-8") as f:
        json.dump(personas, f, indent=2)

def ep_personas_list():
    personas = _load_personas()
    return {"personas": [{"id": k, "name": v.get("name", k),
                          "built_in": bool(v.get("built_in")),
                          "description": v.get("description", ""),
                          "doctrine": v.get("doctrine"),
                          "tactic_matrix": v.get("tactic_matrix") or [],
                          "system_prompt": v.get("system_prompt", "")}
                          for k, v in personas.items()]}

def ep_persona_reset(pid):
    """Restore a built-in persona to its shipped default."""
    if pid not in DEFAULT_PERSONAS:
        return {"error": "no shipped default exists for this persona"}
    personas = _load_personas()
    personas[pid] = dict(DEFAULT_PERSONAS[pid])
    _save_personas(personas)
    return {"ok": True}

def ep_persona_save(d):
    name = (d.get("name") or "").strip()
    prompt = (d.get("system_prompt") or "").strip()
    doctrine = d.get("doctrine")
    if doctrine is not None and not isinstance(doctrine, dict):
        return {"error": "doctrine must be an object"}
    matrix = d.get("tactic_matrix")
    if matrix is not None and not isinstance(matrix, list):
        return {"error": "tactic_matrix must be a list"}
    if not name or (not prompt and not doctrine):
        return {"error": "name plus either doctrine or system_prompt are required"}
    pid = (d.get("id") or "").strip()
    if not pid:
        pid = "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_")[:40] or "persona"
    personas = _load_personas()
    old = personas.get(pid, {})
    rec = {"name": name, "built_in": bool(old.get("built_in"))}
    rec["description"] = (d.get("description") or "").strip()
    if doctrine:
        # normalize doctrine lists (UI sends strings or lists)
        for k in ("authority_moments", "core_rules"):
            v = doctrine.get(k)
            if isinstance(v, str):
                doctrine[k] = [ln.strip() for ln in v.splitlines() if ln.strip()]
        rec["doctrine"] = doctrine
        rec["tactic_matrix"] = [t for t in (matrix or []) if isinstance(t, dict)]
        rec["system_prompt"] = _compile_persona_prompt(rec)
    else:
        rec["doctrine"] = None
        rec["tactic_matrix"] = []
        rec["system_prompt"] = prompt
    personas[pid] = rec
    _save_personas(personas)
    return {"ok": True, "id": pid}

def ep_persona_delete(pid):
    personas = _load_personas()
    if pid in personas:
        if personas[pid].get("built_in"):
            return {"error": "can't delete a built-in persona"}
        del personas[pid]
        _save_personas(personas)
    return {"ok": True}

# ── Playbooks: WHAT the call is about (orthogonal to persona = HOW to coach) ──
# Permits / Wholesale / FMCSA / General — identity, mission, money play, pivot
# triggers. Compiled by _build_playbook_block() and injected into the coach ctx.
PLAYBOOKS_PATH = os.path.join(BASE, "cc_playbooks.json")

def _load_playbooks():
    try:
        with open(PLAYBOOKS_PATH, encoding="utf-8") as f:
            d = json.load(f)
            if d:
                return d
    except Exception:
        pass
    return {"general": {"name": "General (Adaptive)", "stub": True,
                        "description": "Fallback — cc_playbooks.json missing.",
                        "identity": "Adaptive.", "mission": "Qualify on need, money, time, authority."}}

def _build_playbook_block(pb):
    """Compile a playbook record into the prompt block injected into coach ctx."""
    if not pb:
        return ""
    lines = ["PLAYBOOK: %s" % (pb.get("name") or "custom")]
    if pb.get("stub"):
        lines.append("STATUS: STUB — doctrine not built yet. Coach with adaptive GUTS "
                     "fundamentals only and treat every suggestion as provisional.")
    for label, key in (("IDENTITY", "identity"), ("MISSION", "mission")):
        if pb.get(key):
            lines.append("%s: %s" % (label, pb[key]))
    intro = pb.get("intro_structure") or []
    if intro:
        lines.append("LOCKED INTRO STRUCTURE:\n" + "\n".join("  " + s for s in intro))
    if pb.get("bridge_after_interrupt"):
        lines.append("LOCKED BRIDGE (the line after the interrupt question lands):\n  \""
                     + pb["bridge_after_interrupt"] + "\"")
    arc = pb.get("call_arc") or []
    if arc:
        lines.append("LOCKED CALL ARC (the full call map, in order — the rep's voice comes from "
                     "these exact lines; jump forward or back as the prospect's answers require, "
                     "never force the order):")
        for b in arc:
            when = (" [when: %s]" % b["when"]) if b.get("when") else ""
            lines.append("  <%s>%s" % (b.get("beat", "beat"), when))
            for ln in (b.get("lines") or []):
                lines.append("    " + ln)
    qd = pb.get("question_doctrine") or {}
    if qd:
        lines.append("QUESTION DOCTRINE (locked from live G.U.T.S. training — follow it exactly):")
        if qd.get("lane_rule"):
            lines.append("  lane rule: " + qd["lane_rule"])
        seq = qd.get("locked_sequence") or []
        if seq:
            lines.append("  locked qualification sequence:\n" + "\n".join("    " + s for s in seq))
        for k in ("presupposition_ban", "one_question_rule", "follow_up_rule", "signal_listen"):
            if qd.get(k):
                lines.append("  %s: %s" % (k.replace("_", " "), qd[k]))
    mp = pb.get("money_play") or {}
    if mp:
        lines.append("MONEY PLAY:")
        for k, v in mp.items():
            lines.append("  %s: %s" % (k.replace("_", " "), v))
    ef = pb.get("equity_fork") or {}
    if ef:
        lines.append("EQUITY FORK:")
        for k, v in ef.items():
            lines.append("  %s: %s" % (k.replace("_", " "), v))
    om = pb.get("offer_math") or {}
    if om:
        lines.append("OFFER MATH:")
        for k, v in om.items():
            lines.append("  %s: %s" % (k.replace("_", " "), v))
    if pb.get("urgency_math"):
        lines.append("URGENCY MATH: " + pb["urgency_math"])
    pr = pb.get("pivot_rule") or {}
    if pr:
        lines.append("WHOLESALE PIVOT RULE:")
        lines.append("  gate: " + str(pr.get("gate", "")))
        tl = pr.get("trigger_language") or []
        if tl:
            lines.append("  trigger language: " + " | ".join('"%s"' % t for t in tl))
        lines.append("  move: " + str(pr.get("move", "")))
    ar = pb.get("awareness_rules") or []
    if ar:
        lines.append("AWARENESS RULES:\n" + "\n".join("  - " + r for r in ar))
    return "\n".join(lines)

def ep_playbooks_list():
    pbs = _load_playbooks()
    return {"playbooks": [{"id": k, "name": v.get("name", k),
                           "description": v.get("description", ""),
                           "stub": bool(v.get("stub"))}
                          for k, v in pbs.items()]}

# ── ARV engine & MAO calculator (GUTS Phase 3) ───────────────────────────────
# Source priority: (1) 30-day cache in cellcoach.db, (2) internal command_center
# leads table (free, local), (3) external AVM (RentCast/ATTOM — stubbed until a
# key lands in cc_config.json). Computed at BRIEF state only, never mid-call.
COMMAND_CENTER_DB = os.path.join(os.path.dirname(BASE), "data", "command_center.db")
VALUATION_TTL_DAYS = 30

# Repair heuristics v1 — violation-type driven, MAX of matched signals (not sum,
# avoids double-counting overlapping damage). Provisional until inspector
# diagnosis (per plan §3 bottleneck #2).
_REPAIR_BY_SIGNAL = {
    "fire": 40000, "water": 20000, "vacancy": 12000, "code": 10000,
    "foreclosure": 8000, "probate": 8000, "trash": 3000, "permit": 2000,
    "str": 0, "n311": 0, "tax": 0,
}

def _est_repairs(signals):
    if not signals:
        return 5000
    return max((_REPAIR_BY_SIGNAL.get(s, 5000) for s in signals), default=5000)

def _assignment_fee(arv):
    """Austin wholesale fee band $8-18k, scaled to deal size."""
    if arv >= 500000:
        return 18000
    if arv >= 250000:
        return 12000
    return 8000

def _mao_calc(arv, est_repairs):
    """GUTS wholesale doctrine: MAO = 0.70 x ARV - est_repairs - assignment fee.
    Offer range shown to the rep is MAO +/- $5k."""
    fee = _assignment_fee(arv)
    mao = 0.70 * arv - est_repairs - fee
    return {"mao": round(mao), "offer_low": round(mao - 5000),
            "offer_high": round(mao + 5000), "assignment_fee": fee}

def _sane_value(v):
    """Dollars, plausibility-checked (rejects sentinel/garbage like 1 or 2^31-1)."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if 50000 <= v <= 20000000 else None

def _arv_from_row(est_value, prop_value):
    """prop_value is dollars (dirty — filter). est_value is THOUSANDS (the
    datacenter2 unit bug family: 350.0 means $350k)."""
    pv = _sane_value(prop_value)
    if pv:
        return pv, "prop_value"
    try:
        ev = float(est_value)
    except (TypeError, ValueError):
        return None, None
    if 100 <= ev <= 5000:  # thousands, plausible Austin band $100k-$5M
        return ev * 1000, "est_value_x1000"
    return None, None

def _internal_valuation(address, zip_):
    """Match a normalized address against command_center.leads (8.5k Austin props)."""
    if not os.path.exists(COMMAND_CENTER_DB) or not address.strip():
        return None
    norm_target = _norm_address(address)
    if not norm_target:
        return None
    house = norm_target.split(" ", 1)[0]
    try:
        con = sqlite3.connect(COMMAND_CENTER_DB)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT address, zip, owner, est_value, prop_value, est_equity, "
            "est_mortgage_balance, absentee, land_use FROM leads WHERE address LIKE ?",
            (house + " %",)).fetchall()
        con.close()
    except Exception:
        return None
    for r in rows:
        if _norm_address(r["address"]) != norm_target:
            continue
        arv, val_source = _arv_from_row(r["est_value"], r["prop_value"])
        if not arv:
            continue
        ab = (r["absentee"] or "").upper()
        occupancy = ("owner_occupied" if ab == "OWNER_OCC"
                     else "absentee" if ab else "unknown")
        equity, mortgage = None, None
        try:
            equity = float(r["est_equity"]) if r["est_equity"] not in (None, "") else None
            mortgage = float(r["est_mortgage_balance"]) if r["est_mortgage_balance"] not in (None, "") else None
        except (TypeError, ValueError):
            pass
        if equity is not None and arv:
            ratio = equity / arv
            equity_band = "fat" if ratio >= 0.5 else ("workable" if ratio >= 0.25 else "thin")
        elif mortgage is not None and arv:
            ratio = 1 - (mortgage / arv)
            equity_band = "fat" if ratio >= 0.5 else ("workable" if ratio >= 0.25 else "thin")
        else:
            equity_band = "unknown"
        return {"arv": round(arv), "source": "internal:" + val_source,
                "zip": r["zip"] or zip_ or "", "owner_on_record": r["owner"] or "",
                "equity_band": equity_band, "occupancy": occupancy,
                "land_use": r["land_use"] or ""}
    return None

def _external_valuation(address, zip_):
    """RentCast/ATTOM fallback — STUB. Activates when a key lands in cc_config.json
    (rentcast_key or attom_key). Until then: clean miss, no fake numbers."""
    return None

def ep_valuation(qs):
    """GET /api/valuation?address=...&zip=...&signals=code,trash — BRIEF-state
    valuation: cache -> internal -> external stub. Never blocks a call."""
    address = (qs.get("address", [""])[0] or "").strip()
    zip_ = (qs.get("zip", [""])[0] or "").strip()
    signals = [s for s in (qs.get("signals", [""])[0] or "").split(",") if s]
    if not address:
        return {"available": False, "reason": "no address"}
    norm = _norm_address(address)

    con = db()
    row = con.execute("SELECT * FROM property_valuations WHERE norm_address=?",
                      (norm,)).fetchone()
    if row and row["fetched_at"]:
        try:
            age = (datetime.now() - datetime.strptime(row["fetched_at"], "%Y-%m-%d %H:%M:%S")).days
        except Exception:
            age = VALUATION_TTL_DAYS + 1
        if age < VALUATION_TTL_DAYS:
            con.close()
            return {"available": bool(row["arv"]), "cached": True,
                    "address": row["address"], "zip": row["zip"] or "",
                    "arv": row["arv"], "est_repairs": row["est_repairs"],
                    "mao": row["mao"], "offer_low": row["offer_low"],
                    "offer_high": row["offer_high"], "equity_band": row["equity_band"],
                    "occupancy": row["occupancy"], "source": row["source"]}

    hit = _internal_valuation(address, zip_)
    source = "internal"
    if not hit:
        hit = _external_valuation(address, zip_)
        source = "external"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if hit and hit.get("arv"):
        repairs = _est_repairs(signals)
        # Wholesale Offer Calculator (Cash Offer sheet) is the canonical math:
        # ((0.95*ARV) - 0.10*ARV investor return - repairs - $30k profit) / 1.01
        m = offer_engine.cash_offer(hit["arv"], repairs)
        con.execute("""INSERT OR REPLACE INTO property_valuations
            (norm_address, address, zip, arv, est_repairs, mao, offer_low, offer_high,
             equity_band, occupancy, source, fetched_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (norm, address, hit.get("zip") or zip_, hit["arv"], repairs, m["mao"],
             m["offer_low"], m["offer_high"], hit.get("equity_band", "unknown"),
             hit.get("occupancy", "unknown"), hit["source"], now))
        con.commit()
        con.close()
        return {"available": True, "cached": False, "address": address,
                "zip": hit.get("zip") or zip_, "arv": hit["arv"],
                "est_repairs": repairs, "desired_profit": m["desired_profit"],
                "mao": m["mao"], "offer_low": m["offer_low"], "offer_high": m["offer_high"],
                "equity_band": hit.get("equity_band", "unknown"),
                "occupancy": hit.get("occupancy", "unknown"),
                "owner_on_record": hit.get("owner_on_record", ""),
                "source": hit["source"]}
    # graceful miss — cache the miss too so we don't re-scan per call
    con.execute("""INSERT OR REPLACE INTO property_valuations
        (norm_address, address, zip, arv, est_repairs, mao, offer_low, offer_high,
         equity_band, occupancy, source, fetched_at)
        VALUES(?,?,?,NULL,NULL,NULL,NULL,NULL,'','',?,?)""",
        (norm, address, zip_, source + ":miss", now))
    con.commit()
    con.close()
    return {"available": False, "reason": "no valuation on record — run the "
            "conversation on their answers only", "address": address}

# ── Train Mode: scenario engine ───────────────────────────────────────────────
SCENARIOS_PATH = os.path.join(BASE, "cc_scenarios.json")

# Appended to every scenario's systemPrompt (text + voice) so the prospect LLM
# stays natural and never breaks character, regardless of what's in cc_scenarios.json.
TRAIN_GUARDRAILS = (
    "\n\nCHARACTER RULES — never break these:\n"
    "- You are a real property owner on a phone call, not an AI assistant. Never acknowledge "
    "you are role-playing, never break character, never speak like a customer-service bot.\n"
    "- If the caller says something confusing, off-script, or seems to be testing you, react the "
    "way the character actually would — confusion, a flat 'what?', mild annoyance, asking them to "
    "repeat themselves. Do NOT respond with a meta apology like 'you're right, I jumped to "
    "conclusions' or 'my apologies for the confusion' — that's an AI tic, not something a real "
    "person says on a phone call.\n"
    "- Keep responses SHORT: 1 to 3 sentences, like a real phone call, not a monologue.\n"
    "- Don't volunteer your whole situation unprompted — make the caller earn information through "
    "good questions.\n"
    "- Speak like a real person on the phone: contractions, occasional trailing off, natural "
    "pauses — not polished or overly formal phrasing.\n"
    "- Never end the call yourself, never say goodbye first, never hang up.\n"
)


# Rotating name pools so the rep never gets used to saying the same prospect
# name. Gender is independent of difficulty — the rep picks male/female/random
# on the setup screen, and any difficulty tier can be either gender.
NAME_BANK = {
    "male": [
        "Marcus", "Gerald", "Kevin", "James", "Robert", "Thomas", "Victor", "Derek",
        "Raymond", "Michael", "David", "Anthony", "Steven", "Brian", "Eric", "Jason",
        "Justin", "Brandon", "Gregory", "Patrick", "Timothy", "Jeffrey", "Ryan", "Nathan", "Aaron",
    ],
    "female": [
        "Denise", "Lisa", "Patricia", "Carmen", "Angela", "Sandra", "Jennifer", "Michelle",
        "Amanda", "Melissa", "Stephanie", "Rebecca", "Laura", "Kimberly", "Amy", "Cynthia",
        "Kathleen", "Diane", "Julie", "Joyce", "Victoria", "Cheryl", "Sharon", "Teresa", "Gloria",
    ],
}

def _resolve_gender(pref):
    """pref is 'male' | 'female' | 'random' | anything else -> coin flip."""
    import random
    if pref in ("male", "female"):
        return pref
    return random.choice(["male", "female"])

def _random_name(gender):
    import random
    pool = NAME_BANK.get(gender) or NAME_BANK["male"]
    return random.choice(pool)

def _voice_id_for_gender(cfg, gender):
    if gender == "female":
        return (cfg.get("elevenlabs_voice_id_female") or "").strip()
    return (cfg.get("elevenlabs_voice_id_male") or "").strip()

def _load_scenarios():
    if not os.path.exists(SCENARIOS_PATH):
        return {}
    try:
        with open(SCENARIOS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _get_scenario(scenario_id):
    return _load_scenarios().get(scenario_id)

def _get_elevenlabs_signed_url(agent_id, api_key):
    """Get a short-lived signed WebSocket URL from ElevenLabs (API key never sent to client)."""
    url = f"https://api.elevenlabs.io/v1/convai/conversation/get-signed-url?agent_id={agent_id}"
    r = _http(url, "GET", {"xi-api-key": api_key})
    signed = r.get("signed_url")
    if not signed:
        raise RuntimeError("ElevenLabs returned no signed_url")
    return signed

def ep_elevenlabs_voices():
    """List voices on this ElevenLabs account so the two training voice_ids can be identified."""
    c = _local_cfg()
    el_key = c.get("elevenlabs_key", "").strip()
    if not el_key:
        return {"error": "elevenlabs_key required in cc_config.json"}
    try:
        r = _http("https://api.elevenlabs.io/v1/voices", "GET", {"xi-api-key": el_key})
    except Exception as e:
        return {"error": f"ElevenLabs voices fetch failed: {e}"}
    out = []
    for v in r.get("voices", []):
        out.append({
            "voice_id": v.get("voice_id"),
            "name": v.get("name"),
            "gender": (v.get("labels") or {}).get("gender", ""),
            "accent": (v.get("labels") or {}).get("accent", ""),
        })
    return {"voices": out,
            "configured_male": c.get("elevenlabs_voice_id_male", ""),
            "configured_female": c.get("elevenlabs_voice_id_female", "")}

def ep_set_train_voices(d):
    """Look up voice_ids by NAME (never exposes raw IDs to the client) and save them to cc_config.json."""
    c = _local_cfg()
    el_key = c.get("elevenlabs_key", "").strip()
    if not el_key:
        return {"error": "elevenlabs_key required in cc_config.json"}
    male_name = (d.get("male_name") or "").strip().lower()
    female_name = (d.get("female_name") or "").strip().lower()
    if not male_name or not female_name:
        return {"error": "male_name and female_name required"}

    try:
        r = _http("https://api.elevenlabs.io/v1/voices", "GET", {"xi-api-key": el_key})
    except Exception as e:
        return {"error": f"ElevenLabs voices fetch failed: {e}"}

    def _find(target):
        for v in r.get("voices", []):
            if target in (v.get("name") or "").strip().lower():
                return v.get("voice_id")
        return None

    male_id = _find(male_name)
    female_id = _find(female_name)
    if not male_id:
        return {"error": f"no voice matching '{male_name}' found in your ElevenLabs account"}
    if not female_id:
        return {"error": f"no voice matching '{female_name}' found in your ElevenLabs account"}

    path = _local_cfg_path()
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        cfg = {}
    cfg["elevenlabs_voice_id_male"] = male_id
    cfg["elevenlabs_voice_id_female"] = female_id
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

    return {"ok": True, "male_id_set": True, "female_id_set": True}

# ── Train Mode endpoints ───────────────────────────────────────────────────────

def ep_train_scenarios():
    """Return the full scenario bank for the UI picker."""
    scenarios = _load_scenarios()
    out = {}
    for sid, s in scenarios.items():
        diffs = {}
        for d, cfg in s.get("difficulties", {}).items():
            diffs[d] = {
                "label": cfg.get("label", d),
                "firstMessage": cfg.get("firstMessage", "Hello?"),
                "objections": cfg.get("objections", []),
                "imperfections": cfg.get("imperfections", {}),
            }
        out[sid] = {
            "id": sid,
            "name": s.get("name", sid),
            "description": s.get("description", ""),
            "play_context": s.get("play_context", ""),
            "playbook_id": s.get("playbook_id", ""),
            "difficulties": diffs,
        }
    return {"scenarios": out}

def ep_train_preview_character(scenario_id, difficulty, gender_pref="random"):
    """Lightweight, no-DB preview of the gender + a random name for the setup screen.
    Gender is fully independent of difficulty — driven by the rep's Male/Female/Random pick."""
    scenario = _get_scenario(scenario_id)
    if not scenario:
        return {"error": f"unknown scenario: {scenario_id}"}
    diff_cfg = scenario.get("difficulties", {}).get(difficulty)
    if not diff_cfg:
        return {"error": f"unknown difficulty: {difficulty}"}
    gender = _resolve_gender(gender_pref)
    return {"gender": gender, "prospect_name": _random_name(gender)}

def ep_train_start(d):
    """Create a training session record. Returns session_id + scenario config."""
    scenario_id = (d.get("scenario_id") or "").strip()
    difficulty = (d.get("difficulty") or "easy").strip()
    mode = (d.get("mode") or "text").strip()  # "text" | "voice"

    scenario = _get_scenario(scenario_id)
    if not scenario:
        return {"error": f"unknown scenario: {scenario_id}"}
    diff_cfg = scenario.get("difficulties", {}).get(difficulty)
    if not diff_cfg:
        return {"error": f"unknown difficulty: {difficulty}"}

    # Gender is independent of difficulty (rep picks Male/Female/Random on the setup
    # screen). Honor the exact name+gender already previewed/rerolled there if valid;
    # otherwise resolve fresh from the gender preference.
    requested_gender = (d.get("gender") or "").strip()
    requested_name = (d.get("prospect_name") or "").strip()
    if requested_gender in ("male", "female") and requested_name in NAME_BANK.get(requested_gender, []):
        gender = requested_gender
        prospect_name = requested_name
    else:
        gender = _resolve_gender((d.get("gender_pref") or "random").strip())
        prospect_name = _random_name(gender)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    con = db()
    cur = con.execute(
        "INSERT INTO calls(phone, play, owner, address, case_id, started_at, disposition) "
        "VALUES(?,?,?,?,?,?,?)",
        ("", scenario_id, f"[TRAIN] {scenario.get('name', scenario_id)} ({prospect_name})",
         "", "", now, f"train_{mode}"))
    session_id = cur.lastrowid
    con.commit()
    con.close()

    return {
        "session_id": session_id,
        "scenario_id": scenario_id,
        "scenario_name": scenario.get("name", scenario_id),
        "play_context": scenario.get("play_context", "GENERAL"),
        "difficulty": difficulty,
        "difficulty_label": diff_cfg.get("label", difficulty),
        "gender": gender,
        "prospect_name": prospect_name,
        "system_prompt": diff_cfg.get("systemPrompt", "").replace("{name}", prospect_name),
        "first_message": diff_cfg.get("firstMessage", "Hello?"),
        "imperfections": diff_cfg.get("imperfections", {}),
    }

def ep_train_chat(d):
    """Text mode Step 1 ONLY: generate the prospect's next line and return immediately.

    Coaching (Node 1+2+3) is handled by the separate ep_train_coach endpoint, fired by
    the frontend as a non-blocking background call so the conversation never waits on
    the ~1.5-2s coach pipeline. See ep_train_coach below.
    """
    c = _local_cfg()
    key = c.get("openai_key")
    if not key:
        return {"error": "no openai_key in cc_config.json"}

    rep_line = (d.get("rep_line") or "").strip()
    history = d.get("history") or []      # list of {role: "rep"|"prospect", text: str}
    scenario_id = (d.get("scenario_id") or "").strip()
    difficulty = (d.get("difficulty") or "easy").strip()
    prospect_name = (d.get("prospect_name") or "").strip()
    gender = (d.get("gender") or "").strip()

    scenario = _get_scenario(scenario_id)
    if not scenario:
        return {"error": f"unknown scenario: {scenario_id}"}
    diff_cfg = scenario.get("difficulties", {}).get(difficulty, {})
    if not prospect_name:
        prospect_name = _random_name(_resolve_gender(gender))
    prospect_sys = (diff_cfg.get("systemPrompt", "You are a property owner named {name}. Respond naturally.")
                    .replace("{name}", prospect_name) + TRAIN_GUARDRAILS)

    # ── Step 1: Generate prospect's next line ──────────────────────────────────
    prospect_messages = [{"role": "system", "content": prospect_sys}]
    for turn in history:
        gpt_role = "assistant" if turn.get("role") == "prospect" else "user"
        prospect_messages.append({"role": gpt_role, "content": turn.get("text", "")})
    if rep_line:
        prospect_messages.append({"role": "user", "content": rep_line})

    try:
        r = _http("https://api.openai.com/v1/chat/completions", "POST",
                  {"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                  {"model": "gpt-4o-mini", "temperature": 0.7, "max_tokens": 150,
                   "messages": prospect_messages})
        prospect_line = r["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return {"error": f"prospect LLM failed: {e}"}

    return {"prospect_line": prospect_line}


def ep_train_coach(d):
    """Text mode Step 2: run the 3-node coaching pipeline on the growing transcript.

    Fired by the frontend as a background call immediately after ep_train_chat returns
    the prospect_line, so it never blocks the conversation from advancing. Expects the
    full transcript (including the just-generated prospect_line) and prior_state.
    """
    c = _local_cfg()
    key = c.get("openai_key")
    if not key:
        return {"error": "no openai_key in cc_config.json"}

    rep_line = (d.get("rep_line") or "").strip()
    history = d.get("history") or []      # list of {role: "rep"|"prospect", text: str}
    play_context = (d.get("play_context") or "GENERAL").strip()
    prospect_name = (d.get("prospect_name") or "").strip()
    prospect_line = (d.get("prospect_line") or "").strip()

    # Opening turn = the rep's first message (the name-check, e.g. "Hey, is this Mike?").
    # The history array already contains this turn (frontend pushes it before sending),
    # so count REP-role entries rather than checking for emptiness. On the true opening
    # turn there's exactly one — this current one. The frontend discards coach_analysis
    # here in favor of the deterministic _node_opener paragraph fired separately via
    # showOpeningLine(), so skip the expensive Node 1→2→3 pipeline entirely below.
    rep_turns_so_far = sum(1 for t in history if (t.get("role") or "").strip().lower() == "rep")
    is_opening_turn = rep_turns_so_far <= 1

    if is_opening_turn:
        return {
            "coach_analysis": {
                "objection": None,
                "say_next": "",
                "alt_suggestion": None,
                "context_line": "Opening turn — full opener handled separately by showOpeningLine().",
                "coach_type": "rapport",
                "staircase_step": "intro",
                "qualification_verdict": "undetermined",
                "play": None,
                "checklist": {"intro": False, "qualified": False, "play_selected": False, "committed": False},
                "next_action": "",
                "summary": "Opening turn — coach pipeline skipped to save tokens.",
                "temperature": "neutral",
                "prospect_intel": {
                    "properties_owned": None, "urgency": None,
                    "awareness": None, "decision_maker": None, "desired_outcome": None, "stated_number": None
                }
            }
        }

    # Build transcript string for coach
    transcript_lines = []
    for turn in history:
        role = "REP" if turn.get("role") == "rep" else "PROSPECT"
        transcript_lines.append(f"{role}: {turn.get('text', '')}")
    if rep_line:
        transcript_lines.append(f"REP: {rep_line}")
    transcript = "\n".join(transcript_lines)
    full_transcript = transcript + (f"\nPROSPECT: {prospect_line}" if prospect_line else "")

    rep_identity = c.get("rep_identity", "Sean with Risk & Compliance Bureau")
    personas = _load_personas()
    persona_id = d.get("persona_id") or "guts_diamond"
    persona = personas.get(persona_id) or personas.get("guts_diamond") or next(iter(personas.values()))
    playbooks = _load_playbooks()
    pb_id = (d.get("playbook_id") or "").strip()
    if not pb_id:
        # Scenario is the authority when the client didn't pick a mode — a
        # Marcus permit drill always grades/coaches against the permits playbook.
        scen = _get_scenario((d.get("scenario_id") or "").strip()) or {}
        pb_id = (scen.get("playbook_id") or "").strip()
    playbook_block = _build_playbook_block(playbooks.get(pb_id) or {})

    # Custom play: domain-override + questionnaire ctx; else normal property ctx
    custom = d.get("custom") or {}
    is_custom_train = (play_context.upper() == "CUSTOM") and bool(custom)
    if is_custom_train:
        ctx = _build_custom_ctx(custom)
        rep_identity_resolved = _parse_rep_identity(rep_identity)[0]
        persona_prompt = _CUSTOM_DOMAIN_OVERRIDE + persona["system_prompt"]
        staircase_block = ""
    else:
        play_upper = play_context.upper().split(",")[0].strip()
        stakes_text, is_crisis = COACH_STAKES.get(play_upper, COACH_STAKES["GENERAL"])
        ctx = {
            "play": play_upper,
            "stakes_for_this_play": stakes_text,
            "crisis_situation": is_crisis,
            "crisis_rule": ("YES — crisis. NEVER charge the owner directly. "
                            "Contractor-referral or debt-payoff play only." if is_crisis
                            else "No — standard violation, direct fees ok."),
            "owner": prospect_name or "(unknown)",
            "address": "(simulated)",
            "case_id": "(simulated)",
            "fee": "(not set)",
            "notes": "",
            "active_playbook": playbook_block or "(none selected — coach from persona doctrine alone)",
        }
        # Training scenarios are single-signal leads by definition — the wholesale pivot
        # gate starts CLOSED on every drill unless the prospect volunteers distress language.
        ctx["signal_intel"] = {
            "signals": [], "signal_count": 1, "severity": "MED",
            "pivot_armed": (
                "YES — this is a WHOLESALE acquisition drill. The entire call IS the "
                "wholesale conversation: repair interview, anchoring, and the offer flow "
                "are all in bounds. The rep still never names the first number until the "
                "playbook's offer beat is earned."
                if pb_id == "wholesale" else
                "NO — training scenario, single-signal lead. Compliance play only; "
                "do NOT pivot to wholesale unless the prospect volunteers distress "
                "language ('I'm just done with it', 'I can't keep up', 'I just want out')."),
        }
        # Prospect-corrected fact base (same mechanism as live calls)
        fact_override = (d.get("fact_override") or "").strip()
        if fact_override:
            ctx["corrected_fact"] = (
                fact_override + "  — the prospect corrected the record. Use THIS fact for the "
                "urgency math, the pitch, and any referral language, NOT the original scenario fact."
            )
        rep_identity_resolved = rep_identity
        persona_prompt = persona["system_prompt"]
        staircase_block = None  # resolved below after classification

    prior = d.get("prior_state") or {}

    # Rep performance profile — same wire as live calls: training grades steer
    # the drill coach too, so weaknesses get drilled in practice AND on the phone.
    if not is_custom_train:
        _profile_block = _get_profile_context()
        if _profile_block:
            ctx["rep_profile"] = _profile_block

    # Node 1+2 merged: stage classification + signal detection in one call
    prior_intel = prior.get("prospect_intel") or {}
    analysis = _node_analyze(full_transcript, prospect_line, prior, key)
    current_step = analysis.get("staircase_step") or (prior.get("staircase_step") or "intro")
    stage = analysis
    signals = analysis
    new_intel = analysis.get("prospect_intel") or {}
    signals["prospect_intel"] = {
        k: (new_intel.get(k) or prior_intel.get(k))
        for k in ("properties_owned", "urgency", "awareness", "decision_maker", "desired_outcome", "stated_number")
    }

    # Node 3: Generate coaching line
    if staircase_block is None:
        staircase_block = _build_staircase_block(current_step)

    # Live underwriting in training: same condition-merge as live calls. ARV comes
    # from the scenario (wholesale drills) when present — otherwise no numbers.
    prior_cond = prior.get("condition_intel") or {}
    merged_cond = dict(prior_cond)
    for _k, _v in (signals.get("condition_intel") or {}).items():
        if _v is not None:
            merged_cond[_k] = _v
    signals["condition_intel"] = merged_cond
    if not is_custom_train:
        scen_now = _get_scenario((d.get("scenario_id") or "").strip()) or {}
        _arv = scen_now.get("arv") or (scen_now.get("valuation") or {}).get("arv")
        _wholesale_mode = (pb_id == "wholesale")
        if _arv and (_wholesale_mode or _pivot_armed_yes(ctx)):
            _ob = offer_engine.offer_block(_arv, merged_cond)
            if _ob:
                ctx["offer_engine"] = _ob

    coach_model = (c.get("coach_model") or "gpt-4o").strip() or "gpt-4o"
    coach_out = _node_coach(current_step, signals, ctx, rep_identity_resolved,
                            persona_prompt, staircase_block, key,
                            model=coach_model,
                            prior_say_next=prior.get("say_next"),
                            transcript_tail=(full_transcript or "")[-1200:])
    # Hard pivot gate — same enforcement as live calls
    if not is_custom_train and not _pivot_armed_yes(ctx) and _PIVOT_PHRASES_RE.search(coach_out.get("say_next") or ""):
        coach_out = _node_coach(current_step, signals, ctx, rep_identity_resolved,
                                persona_prompt, staircase_block, key,
                                model=coach_model,
                                prior_say_next=prior.get("say_next"),
                                transcript_tail=(full_transcript or "")[-1200:],
                                extra_note=("The wholesale pivot gate is CLOSED on this call — the "
                                            "prospect has shown no distress language and this is not an "
                                            "armed multi-signal lead. No selling, cash offers, or 'getting "
                                            "out from under the property' language. Coach the compliance "
                                            "play only."))

    # Merge into standard shape
    coach_analysis = {
        "objection":            signals.get("objection"),
        "say_next":             coach_out.get("say_next", ""),
        "alt_suggestion":       coach_out.get("alt_suggestion"),
        "context_line":         signals.get("context_line", ""),
        "coach_type":           coach_out.get("coach_type", "discovery"),
        "staircase_step":       current_step,
        "qualification_verdict": stage.get("qualification_verdict", "undetermined"),
        "play":                 coach_out.get("play"),
        "checklist":            stage.get("checklist") or {
                                    "intro": False, "qualified": False,
                                    "play_selected": False, "committed": False
                                },
        "next_action":          coach_out.get("next_action", ""),
        "summary":              coach_out.get("summary", ""),
        "temperature":          signals.get("temperature", "neutral"),
        "rep_misquote":         signals.get("rep_misquote"),
        "prospect_contradiction": signals.get("prospect_contradiction"),
        "fact_correction":      signals.get("fact_correction"),
        "condition_intel":      signals.get("condition_intel") or {},
        "offer_engine":         ctx.get("offer_engine"),
        "prospect_intel":       signals.get("prospect_intel") or {}
    }

    return {"coach_analysis": coach_analysis}

def ep_train_credentials(session_id):
    """Voice mode: return ElevenLabs signed URL + scenario persona for this session."""
    c = _local_cfg()
    el_key = c.get("elevenlabs_key", "").strip()
    el_agent = c.get("elevenlabs_agent_id", "").strip()
    if not el_key or not el_agent:
        return {"error": "elevenlabs_key and elevenlabs_agent_id required in cc_config.json"}

    if not session_id:
        return {"error": "session_id required"}

    # Look up the session to get scenario/difficulty
    con = db()
    row = con.execute("SELECT * FROM calls WHERE id=?", (int(session_id),)).fetchone()
    con.close()
    if not row:
        return {"error": "session not found"}

    scenario_id = row["play"]  # we stored scenario_id in play column
    # difficulty is in owner field as "[TRAIN] name" — we need to re-derive from scenario_id
    # For voice mode, difficulty is passed separately by the client
    scenario = _get_scenario(scenario_id)
    if not scenario:
        return {"error": f"scenario not found: {scenario_id}"}

    try:
        signed_url = _get_elevenlabs_signed_url(el_agent, el_key)
    except Exception as e:
        return {"error": f"ElevenLabs signed URL failed: {e}"}

    return {"signed_url": signed_url, "agent_id": el_agent}

def ep_train_credentials_full(d):
    """Voice mode: return ElevenLabs signed URL with scenario persona injected."""
    c = _local_cfg()
    el_key = c.get("elevenlabs_key", "").strip()
    el_agent = c.get("elevenlabs_agent_id", "").strip()
    if not el_key or not el_agent:
        return {"error": "elevenlabs_key and elevenlabs_agent_id required in cc_config.json"}

    scenario_id = (d.get("scenario_id") or "").strip()
    difficulty = (d.get("difficulty") or "easy").strip()
    prospect_name = (d.get("prospect_name") or "").strip()
    gender = (d.get("gender") or "").strip()

    scenario = _get_scenario(scenario_id)
    if not scenario:
        return {"error": f"unknown scenario: {scenario_id}"}
    diff_cfg = scenario.get("difficulties", {}).get(difficulty, {})
    if gender not in ("male", "female"):
        gender = _resolve_gender("random")
    if not prospect_name:
        prospect_name = _random_name(gender)
    # Only send voice_id if elevenlabs_voice_override_enabled is true in config.
    # The ElevenLabs agent Security tab → Overrides → "Voice ID" toggle MUST be ON
    # before this is set — sending a voice_id without that toggle causes an immediate
    # clean close (code 1000) after conversation_initiation_metadata, no audio plays.
    voice_id = _voice_id_for_gender(c, gender) if c.get("elevenlabs_voice_override_enabled") else ""

    try:
        signed_url = _get_elevenlabs_signed_url(el_agent, el_key)
    except Exception as e:
        return {"error": f"ElevenLabs signed URL failed: {e}"}

    return {
        "signed_url": signed_url,
        "agent_id": el_agent,
        "system_prompt": diff_cfg.get("systemPrompt", "").replace("{name}", prospect_name) + TRAIN_GUARDRAILS,
        "first_message": diff_cfg.get("firstMessage", "Hello?"),
        "voice_id": voice_id,
        "gender": gender,
        "prospect_name": prospect_name,
    }

def ep_train_end(d):
    """Save final transcript + coach log to the training session record."""
    session_id = d.get("session_id")
    if not session_id:
        return {"error": "session_id required"}
    transcript = (d.get("transcript") or "").strip()
    coach_log = d.get("coach_log") or ""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Calculate duration from started_at
    con = db()
    row = con.execute("SELECT started_at FROM calls WHERE id=?", (int(session_id),)).fetchone()
    dur = 0
    if row:
        try:
            started = row["started_at"]
            s = datetime.strptime(started, "%Y-%m-%d %H:%M:%S")
            dur = max(0, int((datetime.now() - s).total_seconds()))
        except Exception:
            pass
    con.execute(
        "UPDATE calls SET ended_at=?, duration=?, transcript=?, coach_log=? WHERE id=?",
        (now, dur, transcript,
         coach_log if isinstance(coach_log, str) else json.dumps(coach_log),
         int(session_id)))
    con.commit()
    con.close()
    # Fire post-call AI summary + scoring in background
    if transcript:
        threading.Thread(target=_post_call_ai, args=(int(session_id),), daemon=True).start()
        threading.Thread(target=_score_session, args=(int(session_id),), daemon=True).start()
    return {"ok": True, "session_id": session_id}

# ── Endpoints ─────────────────────────────────────────────────────────────────
def _call_history_index():
    """normalized phone -> {count, last_dispo, last_ymd, fu_ymd} from local call log.
    last_ymd/fu_ymd feed the ranked-queue port: called-today exclusion,
    2-day touch cadence, and callback-due resurfacing (datacenter2 rankQueue)."""
    hist = {}
    try:
        lc = db()
        for r in lc.execute("SELECT phone, disposition, started_at, follow_up_date "
                            "FROM calls WHERE phone != '' ORDER BY id ASC"):
            k = _normalize_phone(r["phone"])
            if not k:
                continue
            e = hist.get(k) or {"count": 0, "last_dispo": "", "last_ymd": "", "fu_ymd": ""}
            e["count"] += 1
            e["last_dispo"] = r["disposition"] or ""
            ymd = (r["started_at"] or "")[:10]
            if ymd:
                e["last_ymd"] = ymd
            fu = (r["follow_up_date"] or "").strip()[:10]
            if fu:
                e["fu_ymd"] = fu
            hist[k] = e
        lc.close()
    except Exception:
        pass
    return hist

# ── Ranked dial queue (port of datacenter2 lib/dialer/dialerQueue.ts) ──────
# Faithful to the original's bucket ladder, reduced to the fields this app
# actually persists (no wealthTier/portfolio/strLicense here, so the
# time-of-day tier boost and those base-score factors are intentionally
# absent rather than faked).
def _rank_queue(leads, today=None):
    """Pure decision logic: scores, buckets, sorts queue leads. No DB calls."""
    today = today or datetime.now().strftime("%Y-%m-%d")
    try:
        today_d = datetime.strptime(today, "%Y-%m-%d")
    except Exception:
        today_d = datetime.now()
    ranked = []
    for l in leads:
        fu = (l.get("fu_ymd") or "")
        # Called-today exclusion — BUT a due callback always wins: an inbound
        # callback (or a manually set follow-up) dated today must resurface to
        # the top even though the number was already touched today.
        if (l.get("last_ymd") or "") == today and not (fu and fu <= today):
            continue  # already dialed today -- never burn the same number twice
        base = 100  # every lead reaching this point has a phone
        # Signal-stack severity outranks everything except a due callback:
        # multi-signal distressed properties are where the wholesale pivot lives.
        sev = (l.get("severity") or "").upper()
        base += {"CRITICAL": 400, "HIGH": 200, "MED": 50}.get(sev, 0)
        sc = (l.get("score") or "").upper()
        if sc == "HIGH":
            base += 50
        elif sc == "MEDIUM":
            base += 25
        try:
            v = float(re.sub(r"[^\d.]", "", str(l.get("_value_raw") or "")) or 0)
            base += min(v / 10, 150)
        except Exception:
            pass
        last_ymd = (l.get("last_ymd") or "")
        days_since = None
        if last_ymd:
            try:
                days_since = (today_d - datetime.strptime(last_ymd, "%Y-%m-%d")).days
            except Exception:
                days_since = None
        never_called = not last_ymd
        if fu and fu <= today:
            pri, reason = 1000 + base, "callback_due"
        elif days_since is not None and days_since >= 2:
            pri, reason = 500 + base, "touch_cadence_due"
        elif sc == "HIGH" and never_called:
            pri, reason = 300 + base, "hot_untouched"
        elif (l.get("imported_ymd") or "") == today:
            pri, reason = 200 + base, "new_today_with_phone"
        elif never_called:
            pri, reason = 100 + base, "untouched_with_phone"
        else:
            pri, reason = 40 + base, "generic"
        l["priority"] = round(pri, 1)
        l["reason"] = reason
        l.pop("_value_raw", None)
        ranked.append(l)
    ranked.sort(key=lambda x: -x["priority"])
    return ranked

# Institutional/government scrub -- reps should never burn dials on city hall,
# universities, or state authorities (directive ported from datacenter2's
# buildLeadWhere exclusion set).
_INSTITUTIONAL_PAT = re.compile(
    r"UNIVERSITY OF|STATE OF|CITY OF|COUNTY OF|SCHOOL DISTRICT|\bISD\b|"
    r"AUTHORITY|DEPARTMENT OF|DEPT OF|FEDERAL|UNITED STATES|GOVERNMENT|"
    r"MUNICIPAL|APPRAISAL DISTRICT|HOSPITAL DISTRICT|TEXAS A&M", re.I)

def _is_institutional(owner):
    return bool(_INSTITUTIONAL_PAT.search(owner or ""))

def _fmt_value(pv):
    if not pv:
        return ""
    try:
        n = float(pv)
        return ("$%.0fk" % (n / 1000)) if n >= 1000 else ("$%.0f" % n)
    except Exception:
        return str(pv)

def ep_sources():
    """Every dialable lead source: configured SQLite DBs + imported CSV lists."""
    out = []
    for src in _load_sources().get("sources", []):
        p = _source_path(src)
        n = 0
        if p:
            try:
                con = sqlite3.connect("file:" + p.replace("\\", "/") + "?mode=ro", uri=True, timeout=3)
                q = "SELECT COUNT(*) FROM " + _ident(src.get("table", ""))
                if src.get("where"):
                    q += " WHERE " + src["where"]
                n = con.execute(q).fetchone()[0]
                con.close()
            except Exception:
                p = None
        out.append({"id": src.get("id"), "name": src.get("name", src.get("id")),
                    "type": "sqlite", "available": bool(p), "count": n})
    try:
        con = db()
        for r in con.execute("SELECT source, COUNT(*) FROM imported_leads GROUP BY source ORDER BY MAX(id) DESC"):
            out.append({"id": "csv:" + r[0], "name": r[0], "type": "csv",
                        "available": True, "count": r[1]})
        con.close()
    except Exception:
        pass
    return {"sources": out}

def _queue_from_sqlite(src):
    p = _source_path(src)
    if not p:
        return {"available": False, "leads": [], "error": "source DB not found: " + str(src.get("path"))}
    m = src.get("map", {})
    if "phone" not in m:
        return {"available": False, "leads": [], "error": "source map must include a 'phone' column"}
    fields = list(m.items())  # (out_name, column)
    sel = ", ".join(_ident(col) + " AS " + _ident(out) for out, col in fields)
    q = "SELECT " + sel + " FROM " + _ident(src.get("table", ""))
    if src.get("where"):
        q += " WHERE " + src["where"]
    if src.get("order"):
        q += " ORDER BY " + src["order"]
    q += " LIMIT " + str(int(src.get("limit", 400)))
    try:
        con = sqlite3.connect("file:" + p.replace("\\", "/") + "?mode=ro", uri=True, timeout=3)
        con.row_factory = sqlite3.Row
        rows = con.execute(q).fetchall()
        con.close()
    except Exception as e:
        return {"available": False, "leads": [], "error": str(e)[:200]}
    hist = _call_history_index()
    leads = []
    scrubbed = 0
    for r in rows:
        d = dict(r)
        phone = str(d.get("phone") or "")
        if not phone.strip():
            continue
        if _is_institutional(str(d.get("owner") or "")):
            scrubbed += 1
            continue  # government/institutional -- never dial city hall
        h = hist.get(_normalize_phone(phone)) or {}
        if h.get("last_dispo") == "dnc":
            continue  # DNC is a permanent scrub -- never surface this number again
        leads.append({
            "owner": str(d.get("owner") or ""), "phone": phone,
            "address": str(d.get("address") or ""), "zip": str(d.get("zip") or ""),
            "case_id": str(d.get("case_id") or ""),
            "play": str(d.get("play") or "GENERAL"),
            "score": str(d.get("score") or ""),
            "priority": d.get("priority") or 0,
            "prop_value": _fmt_value(d.get("prop_value")),
            "_value_raw": d.get("prop_value"),
            "portfolio_n": d.get("portfolio_n") or 0,
            "description": str(d.get("description") or ""),
            "opened": str(d.get("opened") or ""),
            "call_count": h.get("count", 0), "last_disposition": h.get("last_dispo", ""),
            "last_ymd": h.get("last_ymd", ""), "fu_ymd": h.get("fu_ymd", ""),
        })
    leads = _rank_queue(leads)
    return {"available": True, "leads": leads, "scrubbed_institutional": scrubbed}

def _queue_from_import(source_name):
    con = db()
    rows = con.execute("SELECT * FROM imported_leads WHERE source=? ORDER BY id ASC",
                       (source_name,)).fetchall()
    con.close()
    hist = _call_history_index()
    leads = []
    scrubbed = 0
    for r in rows:
        if _is_institutional(r["owner"] or ""):
            scrubbed += 1
            continue  # government/institutional -- never dial city hall
        h = hist.get(_normalize_phone(r["phone"] or "")) or {}
        status = r["status"] or ""
        if h.get("last_dispo") == "dnc" or status == "dnc":
            continue  # DNC is a permanent scrub -- never surface this number again
        leads.append({
            "owner": r["owner"] or "", "phone": r["phone"] or "",
            "address": r["address"] or "", "zip": r["zip"] or "",
            "case_id": r["case_id"] or "", "play": r["play"] or "GENERAL",
            "score": r["score"] or "", "priority": 0,
            "prop_value": r["value"] or "",
            "_value_raw": r["value"] or "",
            "portfolio_n": 0, "description": r["description"] or "", "opened": "",
            "status": status, "lead_notes": r["notes"] or "",
            "signals": json.loads(r["signals"] or "[]"),
            "signal_count": r["signal_count"] or 0,
            "severity": r["severity"] or "",
            "call_count": h.get("count", 0), "last_disposition": h.get("last_dispo", ""),
            "last_ymd": h.get("last_ymd", ""), "fu_ymd": h.get("fu_ymd", ""),
            "imported_ymd": (r["imported_at"] or "")[:10],
        })
    leads = _rank_queue(leads)
    return {"available": True, "leads": leads, "scrubbed_institutional": scrubbed}

def ep_queue(qs):
    source = (qs.get("source", [""])[0] or "").strip()
    if source.startswith("csv:"):
        return _queue_from_import(source[4:])
    cfg = _load_sources().get("sources", [])
    src = None
    if source:
        src = next((s for s in cfg if s.get("id") == source), None)
    if src is None and cfg:
        src = cfg[0]
    if src is None:
        return {"available": False, "leads": [], "error": "no sources configured"}
    return _queue_from_sqlite(src)

# ── Signal stacking & severity (GUTS Phase 2) ─────────────────────────────────
# One property = one lead row. Multiple violations against the same normalized
# address+owner stack into the signals[] array instead of duplicate rows, and
# the stack depth drives severity — which arms the wholesale pivot.
_SIGNAL_TAXONOMY = [
    ("foreclosure", ["FORECLOSURE", "AUCTION", "TRUSTEE SALE", "SHERIFF SALE",
                     "LIS PENDENS", "PRE-FORECLOSURE", "PRE FORECLOSURE",
                     "NOTICE OF DEFAULT"]),
    ("fire",        ["FIRE DAMAGE", "FIRE", "BURN"]),
    ("water",       ["WATER DAMAGE", "FLOOD"]),
    ("str",         ["SHORT TERM RENTAL", "SHORT-TERM RENTAL", "STR", "AIRBNB", "HOT FILING"]),
    ("permit",      ["UNPERMITTED", "PERMIT", "STOP WORK", "STOP-WORK"]),
    ("code",        ["CODE VIOLATION", "CODE", "VIOLATION", "CITATION"]),
    ("n311",        ["311", "NOISE COMPLAINT", "COMPLAINT"]),
    ("trash",       ["TRASH", "DEBRIS", "ABATEMENT", "JUNK", "WEED", "OVERGROWN"]),
    ("tax",         ["TAX LIEN", "DELINQUENT TAX", "TAX DELINQUENT", "BACK TAXES"]),
    ("vacancy",     ["VACANT", "VACANCY", "ABANDONED", "BOARDED"]),
    ("probate",     ["PROBATE", "ESTATE", "DECEASED", "HEIR"]),
]
_SIGNAL_PATTERNS = [
    (tag, re.compile(r"\b(?:" + "|".join(re.escape(k) for k in kws) + r")\b", re.I))
    for tag, kws in _SIGNAL_TAXONOMY
]

def _classify_signals(*texts):
    """Return ordered unique distress-signal tags found in the given text blobs."""
    blob = " ".join(t for t in texts if t)
    if not blob.strip():
        return []
    return [tag for tag, pat in _SIGNAL_PATTERNS if pat.search(blob)]

def _severity_for(signals):
    """Severity scorer v1 (locked in GUTS_MASTER_BUILD_PLAN):
    3+ signals OR any foreclosure/auction signal = CRITICAL (wholesale primary);
    2 signals = HIGH (compliance + pivot armed); 1 = MED; 0 = LOW."""
    n = len(signals)
    if n >= 3 or "foreclosure" in signals:
        return "CRITICAL"
    if n == 2:
        return "HIGH"
    if n == 1:
        return "MED"
    return "LOW"

_ADDR_CANON = {
    "STREET": "ST", "AVENUE": "AVE", "ROAD": "RD", "DRIVE": "DR", "LANE": "LN",
    "COURT": "CT", "BOULEVARD": "BLVD", "PLACE": "PL", "TERRACE": "TER",
    "CIRCLE": "CIR", "HIGHWAY": "HWY", "PARKWAY": "PKWY", "TRAIL": "TRL",
    "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
    "SUITE": "STE", "APARTMENT": "APT", "UNIT": "STE",
}

def _norm_address(a):
    """Uppercase, strip punctuation, canonicalize suffixes/directionals so
    '123 Main Street', '123 Main St.', and '123 main st' stack into one lead."""
    a = re.sub(r"[.,#]", " ", (a or "").upper())
    a = re.sub(r"\s+", " ", a).strip()
    return " ".join(_ADDR_CANON.get(w, w) for w in a.split())

def _norm_owner(o):
    """Case/punctuation-insensitive owner key with entity suffixes stripped so
    'CEDAR VILLA LTD', 'Cedar Villa Ltd.' and 'Cedar Villa' stack together."""
    o = re.sub(r"[.,]", "", (o or "").upper())
    o = re.sub(r"\s+", " ", o).strip()
    for suf in (" LLC", " LTD", " INC", " CORP", " CORPORATION", " LP", " LLP",
                " CO", " COMPANY", " TRUST", " ET AL", " ET UX"):
        if o.endswith(suf):
            o = o[:-len(suf)].strip()
    return o

# ── CSV import (Targetron / Apollo / any export with a phone column) ─────────
_PHONE_HEADERS = ["phone", "mobile", "mobile phone", "cell", "cell phone",
                  "work direct phone", "direct phone", "phone number", "phone_number",
                  "telephone", "primary phone", "phone 1", "phone1", "contact number",
                  "corporate phone", "company phone"]
_NAME_HEADERS = ["name", "full name", "full_name", "contact", "contact name",
                 "owner", "owner name", "contact_name"]
_FIRST_HEADERS = ["first name", "first_name", "firstname"]
_LAST_HEADERS = ["last name", "last_name", "lastname"]
_COMPANY_HEADERS = ["company", "company name", "company_name", "organization",
                    "business", "business name", "business_name"]
_ADDR_HEADERS = ["address", "full address", "full_address", "street",
                 "street address", "street_address", "mailing address",
                 "property address", "company address", "location"]
_ZIP_HEADERS = ["zip", "zip code", "zipcode", "postal code", "postal_code", "postcode"]
_DESC_HEADERS = ["title", "industry", "category", "type", "website", "site", "description"]
_VALUE_HEADERS = ["value", "est value", "est_value", "estimated value", "estimated_value",
                  "property value", "property_value", "avm", "price", "amount",
                  "deal value", "assessed value", "assessed_value", "market value"]
_NOTES_HEADERS = ["notes", "note", "comments", "comment", "memo", "remarks"]

def _find_col(headers, candidates):
    for cand in candidates:
        for i, h in enumerate(headers):
            if h == cand:
                return i
    for cand in candidates:
        for i, h in enumerate(headers):
            if cand in h:
                return i
    return -1

def ep_import_csv(d):
    name = (d.get("name") or "").strip() or "Imported list"
    text = d.get("csv_text") or ""
    if not text.strip():
        return {"error": "empty CSV"}
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except Exception as e:
        return {"error": "CSV parse failed: " + str(e)[:150]}
    if len(rows) < 2:
        return {"error": "CSV needs a header row plus at least one data row"}
    headers = [h.strip().lower() for h in rows[0]]
    ci_phone = _find_col(headers, _PHONE_HEADERS)
    if ci_phone < 0:
        # fallback: first column in the first data row that looks like a phone
        for i, cell in enumerate(rows[1]):
            if len(re.sub(r"\D", "", cell)) >= 10:
                ci_phone = i
                break
    ci_name = _find_col(headers, _NAME_HEADERS)
    ci_first = _find_col(headers, _FIRST_HEADERS)
    ci_last = _find_col(headers, _LAST_HEADERS)
    ci_co = _find_col(headers, _COMPANY_HEADERS)
    ci_addr = _find_col(headers, _ADDR_HEADERS)
    ci_zip = _find_col(headers, _ZIP_HEADERS)
    ci_value = _find_col(headers, _VALUE_HEADERS)
    ci_notes = _find_col(headers, _NOTES_HEADERS)
    ci_desc = [i for i in (_find_col(headers, [h]) for h in _DESC_HEADERS) if i >= 0]
    # Caller-confirmed column mapping (2-step import UI) overrides auto-detect.
    override = d.get("mapping") or {}
    def col_of(key, auto):
        h = (override.get(key) or "").strip().lower()
        if not h:
            return auto
        try:
            return headers.index(h)
        except ValueError:
            return auto
    ci_phone = col_of("phone", ci_phone)
    ci_name = col_of("owner", ci_name)
    ci_addr = col_of("address", ci_addr)
    ci_value = col_of("value", ci_value)
    ci_notes = col_of("notes", ci_notes)
    if override.get("owner"):
        ci_first = ci_last = ci_co = -1  # single confirmed owner column wins
    def _auto_map():
        return {"phone": headers[ci_phone] if ci_phone >= 0 else "",
                "owner": (headers[ci_name] if ci_name >= 0 else
                          (headers[ci_first] + "+" + headers[ci_last]) if ci_first >= 0 and ci_last >= 0 else
                          headers[ci_co] if ci_co >= 0 else ""),
                "address": headers[ci_addr] if ci_addr >= 0 else "",
                "value": headers[ci_value] if ci_value >= 0 else "",
                "notes": headers[ci_notes] if ci_notes >= 0 else ""}
    if d.get("preview"):
        # Step 1 of the 2-step import: no DB writes, just report what we see
        # so the rep can confirm the column mapping before ingesting.
        return {"ok": True, "preview": True,
                "headers": rows[0][:40],
                "sample": [r[:40] for r in rows[1:4]],
                "row_count": len(rows) - 1,
                "auto": _auto_map()}
    if ci_phone < 0:
        return {"error": "couldn't find a phone column — headers seen: " + ", ".join(headers[:15])}
    # unique source name
    base_name = re.sub(r"\.csv$", "", name, flags=re.I).strip()[:60] or "Imported list"
    con = db()
    existing = {r[0] for r in con.execute("SELECT DISTINCT source FROM imported_leads")}
    src_name, k = base_name, 2
    while src_name in existing:
        src_name = base_name + " (" + str(k) + ")"
        k += 1
    def cell(row, i):
        return row[i].strip() if 0 <= i < len(row) else ""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    skipped = 0
    # Ingest-time stacking: one property = one lead. Rows sharing a normalized
    # address + owner merge into a single lead whose signals[] array accumulates
    # every distinct violation type, and severity is scored off the stack depth.
    groups = {}
    order = []
    for row in rows[1:]:
        phone = cell(row, ci_phone)
        if len(re.sub(r"\D", "", phone)) < 7:
            skipped += 1
            continue
        owner = cell(row, ci_name) or (cell(row, ci_first) + " " + cell(row, ci_last)).strip() or cell(row, ci_co)
        if cell(row, ci_co) and owner != cell(row, ci_co):
            owner = (owner + " — " + cell(row, ci_co)).strip(" —")
        if ci_notes >= 0:
            desc = cell(row, ci_notes)[:200]
        else:
            desc = " · ".join(v for v in (cell(row, i) for i in ci_desc) if v)[:200]
        addr = cell(row, ci_addr)
        sigs = _classify_signals(desc, cell(row, ci_notes) if ci_notes >= 0 else "")
        key = (_norm_address(addr) or _normalize_phone(phone), _norm_owner(owner))
        if key in groups:
            g = groups[key]
            for s in sigs:
                if s not in g["signals"]:
                    g["signals"].append(s)
            if desc and desc not in g["descs"]:
                g["descs"].append(desc)
            if not g["phone"] and phone:
                g["phone"] = phone
            if not g["value"] and cell(row, ci_value):
                g["value"] = cell(row, ci_value)
            if not g["zip"] and cell(row, ci_zip):
                g["zip"] = cell(row, ci_zip)
        else:
            groups[key] = {"owner": owner, "phone": phone, "address": addr,
                           "zip": cell(row, ci_zip), "descs": [desc] if desc else [],
                           "value": cell(row, ci_value), "signals": list(sigs)}
            order.append(key)
    imported = 0
    sev_counts = {"CRITICAL": 0, "HIGH": 0, "MED": 0, "LOW": 0}
    for key in order:
        g = groups[key]
        desc = " | ".join(g["descs"])[:400]
        sigs = g["signals"]
        sev = _severity_for(sigs)
        sev_counts[sev] += 1
        con.execute("INSERT INTO imported_leads(source,owner,phone,address,zip,description,value,"
                    "imported_at,signals,signal_count,severity) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (src_name, g["owner"], g["phone"], g["address"], g["zip"], desc,
                     g["value"], now, json.dumps(sigs), len(sigs), sev))
        imported += 1
    merged = (len(rows) - 1 - skipped) - imported
    con.commit()
    con.close()
    return {"ok": True, "source": src_name, "imported": imported, "skipped": skipped,
            "merged": merged, "severity": sev_counts,
            "mapping": _auto_map()}

def ep_import_delete(d):
    src = (d.get("source") or "").strip()
    if not src:
        return {"error": "no source given"}
    con = db()
    con.execute("DELETE FROM imported_leads WHERE source=?", (src,))
    con.commit()
    con.close()
    return {"ok": True}

# ── Call recordings ───────────────────────────────────────────────────────────
RECORDINGS_DIR = os.path.join(BASE, "recordings")

def ep_save_recording(raw, qs):
    if not raw:
        return {"error": "empty recording"}
    os.makedirs(RECORDINGS_DIR, exist_ok=True)
    phone = re.sub(r"\D", "", (qs.get("phone", [""])[0] or ""))[:15] or "unknown"
    fname = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + phone + ".webm"
    with open(os.path.join(RECORDINGS_DIR, fname), "wb") as f:
        f.write(raw)
    return {"ok": True, "file": fname}

def _dial_guard_numbers():
    """Test-mode dial guard: when dial_allowed_numbers is a non-empty list (or
    comma string) in cc_config.json, ONLY those numbers may be dialed --
    ep_twilio_voice refuses everything else, so a mis-click can never ring a
    real prospect during testing. Empty/absent = live mode, all numbers
    allowed. Never raises; a broken config fails OPEN to live mode so
    production dialing is never blocked by a config typo... except the list
    itself, which is the explicit gate."""
    try:
        c = _local_cfg()
        raw = c.get("dial_allowed_numbers") or []
        if isinstance(raw, str):
            raw = [x.strip() for x in raw.split(",") if x.strip()]
        out = []
        for v in raw:
            digits = "".join(ch for ch in str(v) if ch.isdigit())
            if len(digits) == 10:
                digits = "1" + digits
            if 10 <= len(digits) <= 15:
                out.append("+" + digits)
        return out
    except Exception:
        return []

def ep_status():
    c = _local_cfg()
    missing = not c.get("openai_key") or not c.get("assemblyai_key")
    twilio_ready = bool(c.get("twilio_account_sid") and c.get("twilio_api_key")
                        and c.get("twilio_api_secret") and
                        (c.get("twilio_phone_number") or c.get("twilio_from_number")))
    telnyx_ready = bool(c.get("telnyx_api_key", "").strip()
                        and c.get("telnyx_credential_id", "").strip())
    plivo_ready = bool(c.get("plivo_auth_id", "").strip()
                       and c.get("plivo_auth_token", "").strip())
    provider = (c.get("telephony_provider") or "twilio").strip().lower()
    if provider not in ("twilio", "telnyx", "plivo"):
        provider = "twilio"
    elevenlabs_ready = bool(c.get("elevenlabs_key", "").strip() and c.get("elevenlabs_agent_id", "").strip())
    guard = _dial_guard_numbers()
    return {"missing_keys": missing, "twilio_ready": twilio_ready,
            "telnyx_ready": telnyx_ready, "plivo_ready": plivo_ready,
            "telephony_provider": provider,
            "elevenlabs_ready": elevenlabs_ready,
            "dial_guard": {"active": bool(guard), "allowed": guard}}

def ep_aai():
    key = _local_cfg().get("assemblyai_key")
    if not key:
        return {"error": "no assemblyai_key in cc_config.json"}
    try:
        r = _http("https://streaming.assemblyai.com/v3/token?expires_in_seconds=600",
                  headers={"Authorization": key})
        return {"token": r.get("token")}
    except Exception as e:
        return {"error": f"assemblyai token failed: {e}"}

def _build_staircase_block(current_step):
    """Return the ACTIVE STEP exemplar block to inject into the user prompt."""
    staircase = _load_staircase()
    steps = staircase.get("steps", {})
    moves = staircase.get("moves", {})
    step_data = steps.get(current_step, {})
    if not step_data:
        return ""
    lines = [
        f"\nACTIVE STEP: {step_data.get('label', current_step)}",
        f"GOAL: {step_data.get('goal', '')}",
        f"ADVANCE WHEN: {step_data.get('advance_when', '')}",
        "VOICE EXAMPLES for this step (the rep's phrasing lives here — use the one that fits the "
        "moment, after the listen-first rule has answered whatever the prospect just said):",
    ]
    for sub_key, sub in (step_data.get("sub_steps") or {}).items():
        for ex in (sub.get("exemplars") or []):
            lines.append(f'  - [{ex.get("situation", sub_key)}] "{ex.get("text", "")}"')
    if moves:
        moves_str = " | ".join(f"{k.upper()}: {v}" for k, v in moves.items())
        lines.append(f"THE THREE MOVES: {moves_str}")
    return "\n".join(lines)


# ── 3-Node pipeline: helper functions ─────────────────────────────────────────

def _parse_rep_identity(rep_identity):
    """'Sean with Risk & Compliance Bureau' → (first_name, full_name, agency)."""
    ri = (rep_identity or "Sean with Risk & Compliance Bureau").strip()
    if " with " in ri:
        parts = ri.split(" with ", 1)
        full_name = parts[0].strip()
        agency = parts[1].strip()
    else:
        full_name = ri
        agency = "Risk & Compliance Bureau"
    first_name = full_name.split()[0] if full_name else "Sean"
    return first_name, full_name, agency


def _play_to_intro_sub_step(play):
    """Map lead play type to the correct intro sub-step."""
    p = (play or "").upper()
    if p in ("FIRE", "WATER", "FORECLOSURE", "FORECLOSURE_PAYOFF", "CRISIS"):
        return "crisis"
    if p in ("VACANT", "BLIGHT", "ABATEMENT"):
        return "vacant"
    return "standard"


def _build_fact_line(ctx):
    """Build the specific fact sentence for the opener from lead context."""
    notes = (ctx.get("notes") or "").strip()
    address = (ctx.get("address") or "").strip()
    play = (ctx.get("play") or "GENERAL").upper()
    if notes and len(notes) < 200:
        return notes
    addr_clause = f" at {address}" if (address and address not in ("(simulated)", "(unknown)")) else ""
    fact_map = {
        "FIRE":             f"I saw a fire incident report on your property{addr_clause}",
        "WATER":            f"I noticed a water damage situation on your property{addr_clause}",
        "FORECLOSURE":      f"I noticed you're behind on payments on your property{addr_clause}",
        "FORECLOSURE_PAYOFF": f"I noticed some mortgage activity on your property{addr_clause}",
        "VACANT":           f"your property{addr_clause} has been flagged as vacant with some maintenance issues",
        "STR":              f"your property{addr_clause} has been flagged for short-term rental activity without a valid license",
        "STRUCTURE":        f"there's a structure violation on your property{addr_clause}",
        "OSHA":             f"there are some safety violations on your property{addr_clause}",
        "ABATEMENT":        f"your property{addr_clause} has some city abatement items",
        "PERMIT":           f"there's a permit issue on your property{addr_clause}",
    }
    return fact_map.get(play, f"your property{addr_clause} came up in our compliance records")


# ── Node 0: Opener (no LLM — deterministic template fill) ─────────────────────

def _node_opener(d, c):
    """Generate the G.U.T.S. intro line from a template — no LLM call."""
    rep_identity = c.get("rep_identity", "Sean with Risk & Compliance Bureau")
    first_name, _, agency = _parse_rep_identity(rep_identity)
    agency = agency.replace("&", "and")   # cards are read aloud — always "Risk and Compliance Bureau"

    # ── Custom play: build opener from questionnaire, no property content ──────
    custom = d.get("custom") or {}
    if (d.get("play") or "").upper() == "CUSTOM" and custom:
        who   = (custom.get("who")   or "them").strip()
        goal  = (custom.get("goal")  or "").strip()
        angle = (custom.get("angle") or "").strip()
        tone  = (custom.get("tone")  or "Professional").strip()
        prospect_first = who.split()[0].rstrip(",") if who else "[Name]"
        if tone.lower() == "casual":
            say_next = (
                f"Hey — is this {prospect_first}? This is {first_name}. "
                f"I'll be quick — {angle or 'I had something I wanted to run by you'}. "
                f"You got a couple minutes?"
            )
            alt = f"Or: 'Hey {prospect_first} — {first_name} here. Real quick — you free to talk?'"
        elif tone.lower() == "warm":
            say_next = (
                f"Hi {prospect_first}, this is {first_name}. "
                f"I hope I'm catching you at a good time — "
                f"{angle or 'I came across something I thought might be relevant to you'}. "
                f"Do you have just a few minutes?"
            )
            alt = f"Or: 'Hi {prospect_first} — {first_name}. I'll keep it brief. You got a minute?'"
        else:  # Professional (default)
            say_next = (
                f"Hey {prospect_first}, this is {first_name}. "
                f"I'll get straight to it — {angle or 'I had something specific I wanted to bring to your attention'}. "
                f"You got a few minutes to talk?"
            )
            alt = f"Or: '{prospect_first}, {first_name} here — real quick, do you have two minutes?'"
        return {
            "analysis": {
                "objection": None,
                "say_next": say_next,
                "alt_suggestion": alt,
                "context_line": f"Custom call — goal: {goal}. Counterpart: {who}.",
                "coach_type": "rapport",
                "staircase_step": "intro",
                "qualification_verdict": "undetermined",
                "play": "CUSTOM",
                "checklist": {"intro": False, "qualified": False, "play_selected": False, "committed": False},
                "next_action": "Deliver opener, wait for response, then get permission to ask questions.",
                "summary": "Custom call starting.",
                "temperature": "neutral",
                "prospect_intel": {
                    "properties_owned": None, "urgency": None,
                    "awareness": None, "decision_maker": None, "desired_outcome": None, "stated_number": None
                }
            }
        }

    # ── Property play: original logic ─────────────────────────────────────────
    ctx = {
        "play": d.get("play") or "GENERAL",
        "owner": d.get("owner") or "",
        "address": d.get("address") or "",
        "notes": d.get("notes") or "",
    }
    sub_step = _play_to_intro_sub_step(ctx["play"])
    fact = _build_fact_line(ctx)
    owner_raw = (ctx["owner"] or "").strip()
    prospect_first = owner_raw.split()[0].rstrip(",") if owner_raw else "[Name]"

    if sub_step == "crisis":
        say_next = (
            f"Hey {prospect_first}, this is {first_name} calling from {agency}. We're an independent agency. "
            f"I'm calling because {fact}. "
            f"I know that's stressful — I'm not calling to add to it. "
            f"We help owners in your exact situation. You got a few minutes to talk?"
        )
        alt = (
            f"Or softer: '{prospect_first}, this is {first_name} with {agency} — independent agency. "
            f"I saw what happened. I know you've got a lot going on. You got a few minutes?'"
        )
    elif sub_step == "vacant":
        say_next = (
            f"Hey {prospect_first}, this is {first_name} calling from {agency}. We're an independent agency. "
            f"I was going through some city records and I noticed {fact}. "
            f"Did you know the city had flagged that?"
        )
        alt = (
            f"After they answer: 'That's actually the reason for my call — the longer it sits, the more "
            f"the city piles on. We help owners get these things handled. You got a minute?'"
        )
    else:  # standard / multi_violation — locked G.U.T.S. beats from the Claude practice thread:
        # identity → independent-agency disclaimer → records source → fact → INTERRUPT question → STOP
        source_map = {
            "PERMIT":    "the county permit records",
            "STRUCTURE": "the county code enforcement records",
            "LAND_USE":  "the county code enforcement records",
            "STR":       "the city records",
            "OSHA":      "the county records",
        }
        source = source_map.get(ctx["play"].upper(), "the county records")
        say_next = (
            f"Hey {prospect_first}, this is {first_name} calling from {agency}. We're an independent agency. "
            f"I'm calling because I was going through {source}, and I noticed {fact}. "
            f"Did you know the city had flagged that?"
        )
        alt = (
            f"STOP after the question — let them answer. Then: 'That's actually the reason for my call — "
            f"the deadline's coming up fast, and the fines jump if it sits. We help owners file extensions "
            f"and get it handled. You got a minute?'"
        )

    return {
        "analysis": {
            "objection": None,
            "say_next": say_next,
            "alt_suggestion": alt,
            "context_line": "Call just connected. Nobody has spoken yet.",
            "coach_type": "rapport",
            "staircase_step": "intro",
            "qualification_verdict": "undetermined",
            "play": None,
            "checklist": {"intro": False, "qualified": False, "play_selected": False, "committed": False},
            "next_action": f"Deliver the opener THROUGH the interrupt question ('Did you know the city had flagged that?'), then STOP and let {prospect_first} answer.",
            "summary": "Call start — delivering intro.",
            "temperature": "neutral",
            "prospect_intel": {
                "properties_owned": None, "urgency": None,
                "awareness": None, "decision_maker": None, "desired_outcome": None, "stated_number": None
            }
        }
    }


# ── Node 1+2 merged: Stage Classifier + Signal Detector (4o-mini, one call) ────
# Both are read-only extraction tasks over the same transcript with disjoint output
# fields — no dependency between them — so they run as a single gpt-4o-mini call
# instead of two, cutting one HTTP round-trip off every coaching turn.

_NODE_ANALYZE_SYSTEM = (
    "You are a combined call-state analyzer for a G.U.T.S. sales system. Given a transcript, "
    "the prior call state, and the prospect's latest statement, extract BOTH the call's stage "
    "progress AND the signals in what the prospect just said. Two independent jobs, one pass:\n\n"
    "JOB 1 — STAGE CLASSIFICATION:\n"
    "1. What staircase step the call is on NOW\n"
    "2. Which checklist items are complete\n"
    "3. The qualification verdict\n\n"
    "STAIRCASE STEPS (in order, never skip):\n"
    "  intro — rep introduced, prospect hasn't engaged past the hook\n"
    "  agenda — prospect engaged with hook, rep needs permission to ask questions\n"
    "  qualification — rep is asking need/money/authority/time questions\n"
    "  commitment — all 4 pillars known, rep is hypothetically closing\n"
    "  play_close — rep presented a specific play, locking the callback\n\n"
    "CHECKLIST:\n"
    "  intro: true once prospect engaged past the hook (said more than 'hello')\n"
    "  qualified: true when all 4 pillars are known (urgency, money, authority, time)\n"
    "  play_selected: true once rep has named a specific play\n"
    "  committed: true once prospect agreed to a specific next step with day/time\n\n"
    "EXPLICIT TRANSITION TRIGGERS (apply these immediately — do not wait for a 'cleaner' signal):\n"
    "  - intro -> agenda: the moment the prospect says ANYTHING beyond a bare greeting in\n"
    "    response to the rep's hook (acknowledges the issue, asks a question, pushes back,\n"
    "    corrects a fact — any engagement counts). Set checklist.intro=true HERE, same turn.\n"
    "  - agenda -> qualification: the moment the prospect grants permission or simply does not\n"
    "    object to the rep asking questions — agreement words like 'okay', 'sure', 'yeah that's\n"
    "    fair', 'go ahead', 'ask away', or even just answering a question the rep already asked,\n"
    "    all count as granted permission. The instant this happens, advance staircase_step to\n"
    "    'qualification' in THIS response. Do not stay on 'agenda' waiting for a more explicit\n"
    "    yes — a lukewarm or passive agreement is still agreement.\n"
    "  - Do not confuse 'prospect agreed to the agenda ask' with 'prospect is fully qualified' —\n"
    "    those are different checklist items. Advancing staircase_step to qualification does NOT\n"
    "    require checklist.qualified to be true yet; qualification is a step you enter, not a\n"
    "    box you check before entering it.\n\n"
    "HARD RULES FOR JOB 1:\n"
    "  - Never mark a checklist item false once it was true\n"
    "  - Never regress staircase step unless prospect explicitly forces it\n"
    "  - Never leave staircase_step frozen on 'agenda' once a transition trigger above has fired\n"
    "  - qualification_verdict=pass when qualified=true\n"
    "  - qualification_verdict=fail when prospect confirmed: no money, OR not decision-maker, OR zero urgency\n"
    "  - qualification_verdict=undetermined otherwise\n\n"
    "JOB 2 — SIGNAL DETECTION (from the prospect's LATEST statement only — don't invent signals; "
    "if there's no latest statement, return null/neutral values for this job):\n"
    "  objection: the exact objection/resistance they're raising, or null\n"
    "  context_line: one short phrase — what they communicated / their state of mind\n"
    "  temperature: 'warming' (engaged/curious/open) | 'cooling' (pulling back/annoyed) | 'neutral'\n"
    "  prospect_intel.properties_owned: number/description if stated, else null\n"
    "  prospect_intel.urgency: how urgent they said it is, else null\n"
    "  prospect_intel.awareness: 'aware' (they said they KNEW about the violation/flag/letter\n"
    "    before this call) | 'unaware' (they said they did NOT know) | null if not stated.\n"
    "    This drives which script branch is legal — never coach an unaware beat at an aware\n"
    "    prospect or vice versa.\n"
    "  prospect_intel.decision_maker: 'them alone' | 'partner' | 'other' — if stated, else null\n"
    "  prospect_intel.desired_outcome: 'fix_keep' | 'sell' | 'lease' | 'done' — if surfaced, else null\n"
    "  prospect_intel.stated_number: any price, rent, or fee figure they mentioned, else null\n\n"
    "JOB 3 — CONSISTENCY WATCH (compare the LATEST lines against the WHOLE transcript):\n"
    "  rep_misquote: if the rep asserted 'you said X', paraphrased the prospect in a way that does\n"
    "    NOT match what the prospect actually said earlier, or is arguing with the prospect about\n"
    "    what they said — describe the mismatch in one short phrase (e.g. 'rep claims prospect said\n"
    "    she knew nothing; she actually said she didn't understand the letter'). Null if the rep is\n"
    "    being accurate. Only flag REAL distortions of the prospect's words.\n"
    "  prospect_contradiction: if the prospect's latest line contradicts a FACT in their OWN earlier\n"
    "    statement (not a clarification or added detail — a real conflict, e.g. 'I never got any\n"
    "    letter' after describing the letter's contents), quote both conflicting facts in one short\n"
    "    phrase. Null otherwise.\n"
    "  fact_correction: if the prospect CORRECTED the violation or fact the rep/lead data claimed\n"
    "    (e.g. rep said short-term rental but the letter is about an unpermitted rear structure),\n"
    "    state the CORRECTED fact in one short phrase ('violation is an unpermitted rear structure,\n"
    "    not STR'). Null if no correction. Once stated, this becomes the call's fact base.\n\n"
    "JOB 4 — PROPERTY CONDITION EXTRACTION (feeds the live wholesale offer engine; fill ONLY\n"
    "  from what the prospect explicitly said about the property's physical condition — never\n"
    "  infer from the violation type, never assume. Everything null unless actually stated):\n"
    "  condition_intel keys: kitchen, foundation, year_built, roof, bathrooms, flooring, hvac,\n"
    "    windows, interior_paint, exterior_paint, appliances, garage_door, water_heater.\n"
    "  Values: 'needs_work' (original/dated/broken/leaking/never updated/needs replacing),\n"
    "    'good' (remodeled/new/replaced recently/works great), or a NUMBER for bathrooms\n"
    "    (how many need remodeling) and year_built (the year).\n"
    "  Examples: 'the kitchen is original' -> kitchen:'needs_work'. 'redid the roof two years\n"
    "    ago' -> roof:'good'. 'two baths, both dated' -> bathrooms:2. 'built in the 60s' ->\n"
    "    year_built:1965. 'AC works fine' -> hvac:'good'.\n\n"
    "Respond ONLY with valid JSON matching this exact combined schema:\n"
    "{\"staircase_step\":\"...\",\"checklist\":{\"intro\":bool,\"qualified\":bool,"
    "\"play_selected\":bool,\"committed\":bool},\"qualification_verdict\":\"pass|fail|undetermined\","
    "\"objection\":\"... or null\",\"context_line\":\"...\",\"temperature\":\"warming|cooling|neutral\","
    "\"rep_misquote\":\"... or null\",\"prospect_contradiction\":\"... or null\","
    "\"fact_correction\":\"... or null\","
    "\"condition_intel\":{\"kitchen\":null,\"foundation\":null,\"year_built\":null,"
    "\"roof\":null,\"bathrooms\":null,\"flooring\":null,\"hvac\":null,\"windows\":null,"
    "\"interior_paint\":null,\"exterior_paint\":null,\"appliances\":null,\"garage_door\":null,"
    "\"water_heater\":null},"
    "\"prospect_intel\":{\"properties_owned\":\"... or null\",\"urgency\":\"... or null\","
    "\"awareness\":\"aware|unaware|null\",\"decision_maker\":\"... or null\",\"desired_outcome\":\"... or null\",\"stated_number\":\"... or null\"}}"
)


def _node_analyze(transcript, latest, prior, key):
    """Merged Node 1+2: stage classification + signal detection in ONE gpt-4o-mini call.

    Returns a single dict carrying every field both _node_classify and _node_signals used
    to return separately (staircase_step, checklist, qualification_verdict, objection,
    context_line, temperature, prospect_intel) — callers read it exactly as they used to
    read the two prior return values.
    """
    prior_step = prior.get("staircase_step") or "intro"
    prior_ck = prior.get("checklist") or {}
    user_msg = (
        f"PRIOR STATE: step={prior_step}  checklist={json.dumps(prior_ck)}\n\n"
        f"TRANSCRIPT (last 2000 chars):\n{transcript[-2000:]}"
        + (f"\n\nLATEST PROSPECT LINE: \"{latest}\"" if latest
           else "\n\nLATEST PROSPECT LINE: (none — rep is speaking, no new prospect "
                "statement to analyze for job 2)")
    )
    try:
        r = _http("https://api.openai.com/v1/chat/completions", "POST",
                  {"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                  {"model": "gpt-4o-mini", "temperature": 0.1, "max_tokens": 300,
                   "response_format": {"type": "json_object"},
                   "messages": [{"role": "system", "content": _NODE_ANALYZE_SYSTEM},
                                {"role": "user", "content": user_msg}]})
        result = json.loads(r["choices"][0]["message"]["content"])
        # Enforce monotonic checklist — never regress a true item (same safety net as before)
        ck = result.get("checklist") or {}
        for k in ("intro", "qualified", "play_selected", "committed"):
            if prior_ck.get(k) and not ck.get(k):
                ck[k] = True
        result["checklist"] = ck
        if not isinstance(result.get("prospect_intel"), dict):
            result["prospect_intel"] = {
                "properties_owned": None, "urgency": None,
                "awareness": None, "decision_maker": None, "desired_outcome": None, "stated_number": None
            }
        if not isinstance(result.get("condition_intel"), dict):
            result["condition_intel"] = {}
        return result
    except Exception:
        return {
            "staircase_step": prior_step,
            "checklist": prior_ck,
            "qualification_verdict": prior.get("qualification_verdict", "undetermined"),
            "objection": None,
            "context_line": "Could not parse prospect signal.",
            "temperature": "neutral",
            "rep_misquote": None,
            "prospect_contradiction": None,
            "fact_correction": None,
            "condition_intel": {},
            "prospect_intel": {
                "properties_owned": None, "urgency": None,
                "awareness": None, "decision_maker": None, "desired_outcome": None, "stated_number": None
            }
        }


# ── Node 3: Coach (gpt-4o, strict exemplar matching) ─────────────────────────

_NODE3_CONTRACT = (
    "\n\nCOACHING OUTPUT CONTRACT — one job: tell the rep exactly what to say next.\n"
    "LISTEN-FIRST RULE (overrides everything else — apply it before any exemplar):\n"
    "  The prospect's latest statement ALWAYS gets answered before the script moves.\n"
    "  - If they asked a question, say_next OPENS by answering it — directly, one short sentence.\n"
    "  - If they revealed a fact or a feeling, say_next OPENS with a one-beat acknowledgment\n"
    "    ('Got it.', 'Okay.') — NEVER by restating their own words back to them.\n"
    "  - ONLY THEN bridge into the next beat of the LOCKED CALL ARC.\n"
    "  Never ignore, skip, or talk past what the prospect just said to get back to the script.\n"
    "  If the prospect jumps ahead (asks the price early, says 'how do we start'), jump WITH them\n"
    "  — answer, deliver that beat, then resume the arc from there. If they pull back, slow down\n"
    "  WITH them — one curious question, no pitching.\n\n"
    "DIRECT-QUESTION RULE (a listen-first special case — check the prospect's latest line for a\n"
    "  literal question BEFORE picking any arc beat):\n"
    "  When the prospect asks a direct question — 'what's going on here?', 'what is this about?',\n"
    "  'can you explain that?', 'who are you?', 'what do you mean flagged?' — say_next MUST open\n"
    "  with a ONE-SENTENCE factual answer built ONLY from LEAD CONTEXT facts (who flagged the\n"
    "  property, for what, and what the deadline/fine exposure is), and ONLY THEN bridge to the\n"
    "  next beat. NEVER answer a direct question with another question, and NEVER skip past it\n"
    "  into the agenda ask — a prospect who asks 'what's going on' and gets asked for permission\n"
    "  to talk more feels unheard and hangs up.\n\n"
    "IDENTITY CHECK RULE — compare the name/identity the prospect gives against the lead owner\n"
    "  in LEAD CONTEXT on EVERY early turn:\n"
    "  - If the rep asked for one name and the prospect gave a DIFFERENT one, or the prospect says\n"
    "    'wrong number' / 'no one here by that name' / 'this is their spouse/son/tenant' — say_next\n"
    "    MUST verify who you're speaking with and their relationship to the property BEFORE any\n"
    "    pitch, agenda ask, or violation detail. Wrong person entirely → short, polite exit line.\n"
    "  - Never deliver violation details or urgency math to someone whose identity is unverified.\n"
    "  - GATEKEEPER LANGUAGE BAN: once identity MATCHES the lead owner, the person on the phone IS\n"
    "    the owner. NEVER refer to 'the owner' in third person ('the owner will want to know',\n"
    "    'get this in front of them', 'what's the best number for them') — that script is ONLY for\n"
    "    a prospect who explicitly told you they are NOT the owner. Talking about the owner in the\n"
    "    third person TO the owner proves you weren't listening and kills trust instantly.\n\n"
    "AWARENESS RULE — check prospect_intel.awareness and the transcript before every card:\n"
    "  - If the prospect said they were AWARE of the violation/flag/letter, every 'I figured you\n"
    "    didn't know' / 'you probably hadn't heard' / 'that's why I'm calling, you had no idea'\n"
    "    beat is BANNED — those lines are for UNAWARE prospects only. Acknowledge their awareness\n"
    "    in one beat ('Good — then you know this isn't going away on its own.') and move forward.\n"
    "  - If UNAWARE, the zero-awareness doctrine beats apply normally.\n\n"
    "PERMISSION RULE — check the transcript for an already-granted yes before the agenda ask:\n"
    "  If the prospect already granted permission or invited you to continue ('fire away', 'go\n"
    "  ahead', 'I don't mind', 'sure', 'ask away', 'what have you got'), the permission ask is\n"
    "  DONE — NEVER re-ask it. Go straight into the first discovery question. Re-asking for\n"
    "  permission that was just given tells the prospect you didn't hear a word they said.\n\n"
    "ANSWERED-FACT RULE — before writing ANY question, scan the whole transcript for whether\n"
    "  the prospect ALREADY stated that fact, even loosely: how long it's been going on\n"
    "  ('a year and a half or 2 years' COUNTS as answered), who lives there, what the letter\n"
    "  said, whether they were aware, what they want. If they said it, the question is BANNED —\n"
    "  no matter how perfectly it matches the current staircase exemplar. Instead, BUILD on\n"
    "  their answer ('Two years of this piling up — that's exactly how the fines stack on\n"
    "  owners') or move to a DIFFERENT unanswered discovery beat. The exemplar loses to the\n"
    "  transcript every single time.\n\n"
    "ARC NAVIGATION (replaces rigid script-following — the arc is a map, not a cage):\n"
    "  The LOCKED CALL ARC in LEAD CONTEXT is the full call map. Read the RECENT TRANSCRIPT to\n"
    "  see which beats are already done, then deliver the NEXT undone beat. Use the beat's exact\n"
    "  locked wording whenever the moment matches; adapt only as much as the prospect's actual\n"
    "  statement requires — swap names, facts, numbers, keep the rhythm and sentence count.\n"
    "  1-3 sentences max per card, natural phone speech. ONE question per card — never stack two.\n"
    "  Never invent fines, stats, or facts not in the lead context.\n"
    "  Never charge a crisis victim (fire/water/foreclosure) a direct fee.\n\n"
    "PIVOT GATE (hard rule): if LEAD CONTEXT signal_intel.pivot_armed is NO — or there is no\n"
    "  signal_intel at all — say_next must NEVER raise selling, a cash offer, walking away, or\n"
    "  'getting out from under' the property. Even when pivot_armed is YES, the pivot requires\n"
    "  the prospect's OWN distress language first ('I'm just done with it', 'I can't keep up').\n"
    "  A cooperative prospect who wants to fix the problem is a $250 close — pitch, don't pivot.\n\n"
    "EARNED-MOMENT RULE: when the prospect says they want the problem fixed but don't know how\n"
    "  ('I'm lost', 'not sure what to do first', 'just tell me what I gotta do'), discovery is\n"
    "  DONE — they already told you what they want. Do NOT ask another open question and do NOT\n"
    "  re-ask anything they already answered. Deliver the urgency_math beat, then the pitch.\n\n"
    "NO PARROTING: never restate the prospect's own words back as an observation about them\n"
    "  ('sounds like you're feeling lost') when they JUST said it plainly — it reads as fake.\n"
    "  Acknowledge with ONE beat ('Got it.' / 'Okay.' / 'That's exactly why I called') and move\n"
    "  forward. Mirror ONLY to draw out a feeling they have NOT stated themselves.\n\n"
    "PROSPECT CORRECTION RULE — STROKE + REDIRECTION (a listen-first special case — check it\n"
    "  early, before picking an arc beat):\n"
    "  If the prospect's latest statement CORRECTS, CLARIFIES, or DISPUTES a fact the rep just\n"
    "  stated — a different violation type than the one named, a wrong address detail, \"that's not\n"
    "  my property\", \"it's not vacant, my tenant lives there\", or anything else that means the\n"
    "  rep's stated premise may be wrong or incomplete — the say_next MUST:\n"
    "    1. STROKE — briefly acknowledge what they just said (\"Oh, gotcha\" / \"Got it\" / \"Okay\" —\n"
    "       one short beat, not a paragraph, not effusive)\n"
    "    2. REDIRECTION — ask ONE direct follow-up question that probes the new detail they just\n"
    "       gave you, so the rep understands the ACTUAL situation\n"
    "  ABSOLUTE BAN: do NOT deliver the Agenda pre-commitment line (\"I'm just going to ask you a\n"
    "  couple of questions... at the end you decide\") or any other canned staircase-step script\n"
    "  while a correction or new fact from the prospect is still unresolved. The rep must validate\n"
    "  the correct problem BEFORE moving to Agenda or Qualification — do not advance the script past\n"
    "  an unresolved correction just because the staircase step nominally allows it.\n\n"
    "REP MISQUOTE RECOVERY RULE — check PROSPECT SIGNALS.rep_misquote; when it is set, this\n"
    "  OVERRIDES everything else, including the exemplar rule:\n"
    "  The rep distorted or argued about what the prospect actually said. Never let the rep win an\n"
    "  argument with the prospect about their own words — it kills the call. say_next MUST:\n"
    "    1. DROP IT instantly — a short graceful retreat that accepts THEIR version (\"You're right,\n"
    "       my bad — that's what I meant\" / \"Okay, that makes sense\" — one beat, no groveling)\n"
    "    2. RE-ASK cleanly — ONE question that moves the call forward using the prospect's OWN\n"
    "       corrected version of the facts\n"
    "  Never coach the rep to double down, quote them back, or say 'your exact words'.\n\n"
    "PROSPECT CONTRADICTION RULE — check PROSPECT SIGNALS.prospect_contradiction; when set:\n"
    "  The prospect contradicted their own earlier statement. Do NOT accuse or corner them.\n"
    "  say_next MUST surface the inconsistency as a genuinely curious, non-threatening question\n"
    "  (\"Oh okay — so the letter did come, you just weren't sure what it meant?\"), giving them a\n"
    "  face-saving way to clarify. Their answer is usually where the real pain sits.\n\n"
    "DO NOT PARAPHRASE THE LOCKED LINES INTO GENERIC SALES-SPEAK OR GURU-SPEAK. This means:\n"
    "  no smoothed-over corporate consultant phrasing, no motivational-speaker cadence, no\n"
    "  old-school sales-guru rhythm, no invented rapport lines.\n"
    "  say_next MUST read like a real, modern professional actually talking on the phone —\n"
    "  the locked arc's words wherever they fit, adapted only to answer what the prospect\n"
    "  actually just said.\n\n"
    "BANNED PHRASES — NEVER USE THESE, ON ANY CALL, ESPECIALLY CRISIS INTROS (fire/water/\n"
    "  foreclosure). They are generic corporate hedging, not something Sean says:\n"
    "  - \"I wanted to reach out\" / \"just reaching out\" / \"reaching out to\"\n"
    "  - \"I hope this finds you well\" / \"I hope I'm catching you at a good time\"\n"
    "  - \"touch base\" / \"circle back\" / \"at the end of the day\"\n"
    "  State the business directly instead — who you are and the specific fact — with no\n"
    "  apology or hedge for the fact that you're calling. Do not soften the intro with vague\n"
    "  throat-clearing language. Say the reason plainly, on the first sentence.\n\n"
    "OFFER ENGINE RULE — applies only when LEAD CONTEXT contains offer_engine (live wholesale\n"
    "  underwriting, recomputed EVERY turn from the prospect's own condition answers):\n"
    "  - offer_engine.mao and offer_engine.offer_range are the ONLY number source — never\n"
    "    invent, round, or editorialize figures. The numbers tighten as answers land; trust them.\n"
    "  - The rep NEVER names the first number. If the prospect pushes for one: 'It honestly\n"
    "    depends on the condition — what would you need to walk away with?'\n"
    "  - If offer_engine.next_condition_question is set and the call is in discovery or\n"
    "    qualification, weave that ONE question in naturally when the moment fits. Max one\n"
    "    condition question per turn — never machine-gun the rehab checklist, and skip it\n"
    "    entirely when the prospect is emotional, objecting, or closing.\n\n"
    "Respond ONLY with valid JSON:\n"
    "{\n"
    '  "say_next": "exact words for the rep (always filled)",\n'
    '  "alt_suggestion": "different angle using a different approved example, or null",\n'
    '  "coach_type": "rebuttal | discovery | empathy | close | rapport",\n'
    '  "next_action": "single most important next move",\n'
    '  "summary": "one-line running summary of the call",\n'
    '  "play": "contractor | extension | lease_option | cash_buy | foreclosure_payoff | null"\n'
    "}"
)


def _node_coach(step, signals, ctx, rep_identity, persona_prompt, staircase_block, key, model="gpt-4o",
                prior_say_next=None, transcript_tail=None, extra_note=None):
    """Node 3: Generate coaching line. Persona voice + strict exemplar matching.

    `model` defaults to gpt-4o (unchanged production behavior for every existing
    caller). Exposed as a parameter solely so eval scripts can exercise the exact
    same prompt-construction logic against gpt-4o-mini for a real A/B comparison,
    without duplicating this function's prompt-building code elsewhere.
    `prior_say_next` / `transcript_tail` give the coach memory of what was already
    said so it advances the script instead of repeating a delivered line.
    """
    system = persona_prompt.replace("{rep_identity}", rep_identity) + _NODE3_CONTRACT
    # Extract a clean first name from ctx["owner"] so the model always gets a single
    # title-cased first name — handles "ERIC JOHNSON", "eric", "Eric Johnson", etc.
    owner_raw = (ctx.get("owner") or "").strip()
    prospect_first = owner_raw.split()[0].rstrip(",.").title() if owner_raw else "[Name]"
    # Interpolate the rep's real first name into any {rep_first_name} tokens carried
    # by the staircase exemplars (cc_staircase.json uses this token instead of a
    # hardcoded name so exemplars stay swappable across reps/personas).
    rep_first_name = _parse_rep_identity(rep_identity)[0]
    staircase_block = staircase_block.replace("{rep_first_name}", rep_first_name)
    user_msg = (
        f"PROSPECT FIRST NAME (use this exact name when adapting exemplars): {prospect_first}\n\n"
        + (f"RECENT TRANSCRIPT (what has actually been said — follow up on what the prospect "
           f"ACTUALLY said, using their own words):\n{transcript_tail}\n\n"
           if transcript_tail else "")
        + (f"PRIOR COACHED LINE (the rep already delivered this — do NOT repeat it or re-ask a "
           f"question the prospect just answered; advance to the NEXT beat): \"{prior_say_next}\"\n\n"
           if prior_say_next else "")
        + f"LEAD CONTEXT:\n{json.dumps(ctx, indent=1)}\n\n"
        f"CURRENT STAIRCASE STEP: {step}\n\n"
        f"PROSPECT SIGNALS:\n{json.dumps(signals, indent=1)}\n"
        + staircase_block
        + (f"\n\nCORRECTION FROM THE SYSTEM — your previous attempt violated a hard rule. "
           f"{extra_note} Regenerate the line." if extra_note else "")
        + "\n\nFINAL SELF-CHECK — reject and rewrite your own line if it fails ANY of these:\n"
          "1. Does it restate the prospect's own words back to them as an observation "
          "('sounds like you...', 'so what you're saying is...', 'it sounds like you're feeling...')? "
          "If they just said it plainly, REPLACE that opener with a one-beat acknowledgment "
          "('Got it.', 'Okay.', 'That's exactly why I called.') and move forward.\n"
          "2. Has the prospect already said they want it fixed but don't know how? Then this "
          "line MUST be the urgency_math beat or the pitch — NOT another discovery question.\n"
          "3. Does it ask anything the prospect already answered in the transcript? If yes, "
          "advance to the next unanswered beat instead.\n"
          "4. Any sale / cash-offer / 'get out from under' language while the pivot gate is "
          "closed? Remove it.\n"
          "5. Did the prospect's LATEST line contain a direct question ('what's going on', "
          "'what is this about', 'can you explain', 'who are you')? Then say_next MUST open "
          "with a ONE-SENTENCE factual answer built from LEAD CONTEXT — answering a question "
          "with another question or jumping to the agenda ask is an automatic rewrite.\n"
          "6. Does the name/identity the prospect just gave match the lead owner in LEAD "
          "CONTEXT? If NOT — or identity is still unverified — say_next MUST verify who they "
          "are and their relationship to the property FIRST: no pitch, no agenda ask, no "
          "violation details, no urgency math until identity is confirmed. EXAMPLE: the rep "
          "asked 'is this Sharp?' and the prospect replied 'yeah, this is Sam' — that is a "
          "MISMATCH. Do NOT pitch Sam. Verify: 'Sorry about that, Sam — I was trying to reach "
          "[owner name], the owner of [address]. Is he available, or do you handle things for "
          "the property?'\n"
          "7. Did the prospect say they were AWARE of the violation? Then any 'I figured you "
          "didn't know / wouldn't have the details' phrasing is an automatic rewrite — that "
          "beat is for unaware prospects only.\n"
          "8. Did the prospect already grant permission or say 'fire away' / 'go ahead'? Then "
          "re-asking for permission is an automatic rewrite — ask the discovery question.\n"
          "9. Does the line refer to 'the owner' in third person while the person on the phone "
          "IS the confirmed owner? Automatic rewrite — talk to them AS the owner.\n"
          "10. Does the line ask for a fact the prospect already stated in the transcript "
          "(how long, who lives there, what the letter said)? Automatic rewrite — build on "
          "their answer instead of re-asking it.\n\n"
          "Generate the coaching line. JSON only."
    )
    try:
        r = _http("https://api.openai.com/v1/chat/completions", "POST",
                  {"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                  {"model": model, "temperature": 0.2, "max_tokens": 350,
                   "response_format": {"type": "json_object"},
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": user_msg}]})
        return json.loads(r["choices"][0]["message"]["content"])
    except Exception:
        return {
            "say_next": "Give me just a second...",
            "alt_suggestion": None,
            "coach_type": "rapport",
            "next_action": "Coach error — wait and retry",
            "summary": "Coach error",
            "play": None
        }


# ── Fused pipeline: analysis + coaching in ONE streamed gpt-4o call ───────────
# Latency architecture: the legacy path made two SEQUENTIAL LLM calls per
# prospect turn (gpt-4o-mini analyze ~1.5-2s, then gpt-4o coach ~2.5-3s) =
# 4-7s of dead air before the rep saw a line. The fused path issues ONE gpt-4o
# call whose JSON output leads with say_next, streamed token-by-token all the
# way to the UI: the rep sees the line forming ~1s after the prospect stops
# talking, complete ~2-3s, with the call-state fields trailing silently behind.

_FUSED_OUTPUT_OVERRIDE = (
    "\n\nOUTPUT FORMAT OVERRIDE — supersedes the two individual JSON schemas above: you are "
    "performing ALL jobs in ONE pass (stage classification, signal detection, consistency "
    "watch, condition extraction, AND the coaching line). Respond with ONE valid JSON object "
    "whose keys appear IN THIS EXACT ORDER — say_next MUST be the first key because the rep "
    "is live on the phone waiting for it:\n"
    "{\n"
    '  "say_next": "exact words for the rep (always filled)",\n'
    '  "alt_suggestion": "different angle, or null",\n'
    '  "coach_type": "rebuttal | discovery | empathy | close | rapport",\n'
    '  "next_action": "single most important next move",\n'
    '  "summary": "one-line running summary of the call",\n'
    '  "play": "contractor | extension | lease_option | cash_buy | foreclosure_payoff | null",\n'
    '  "staircase_step": "intro | agenda | qualification | commitment | play_close",\n'
    '  "checklist": {"intro": bool, "qualified": bool, "play_selected": bool, "committed": bool},\n'
    '  "qualification_verdict": "pass | fail | undetermined",\n'
    '  "objection": "the exact objection, or null",\n'
    '  "context_line": "one short phrase — what the prospect communicated / state of mind",\n'
    '  "temperature": "warming | cooling | neutral",\n'
    '  "rep_misquote": "short phrase, or null",\n'
    '  "prospect_contradiction": "short phrase quoting both conflicting facts, or null",\n'
    '  "fact_correction": "the corrected fact in one short phrase, or null",\n'
    '  "condition_intel": {the JOB 4 keys — all null unless the prospect explicitly stated them},\n'
    '  "prospect_intel": {"properties_owned": null, "urgency": null, "awareness": null, '
    '"decision_maker": null, "desired_outcome": null, "stated_number": null}\n'
    "}\n"
    "HOLD RULE: when there is no LATEST PROSPECT LINE (rep is speaking) or nothing meaningful "
    "changed, return the PRIOR COACHED LINE verbatim as say_next and keep the signal fields "
    "null/neutral — do not manufacture a new card. Keep every field terse."
)


def _openai_chat_stream(key, model, system, user_msg, max_tokens=800, temperature=0.2,
                        on_buf=None, timeout=90):
    """Streaming chat completion (SSE) via stdlib only — urlopen yields SSE lines as
    they arrive. on_buf(full_text_so_far) fires per token; returns the complete text."""
    payload = {
        "model": model, "temperature": temperature, "max_tokens": max_tokens,
        "stream": True, "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user_msg}],
    }
    req = _urlreq.Request("https://api.openai.com/v1/chat/completions",
                          data=json.dumps(payload).encode(),
                          headers={"Authorization": "Bearer " + key,
                                   "Content-Type": "application/json"})
    buf = ""
    try:
        with _urlreq.urlopen(req, timeout=timeout) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except Exception:
                    continue
                delta = ((chunk.get("choices") or [{}])[0].get("delta") or {}).get("content")
                if delta:
                    buf += delta
                    if on_buf:
                        on_buf(buf)
    except _urlreq.HTTPError as e:
        try:
            detail = e.read().decode()[:300]
        except Exception:
            detail = str(e)
        raise RuntimeError(f"HTTP {e.code}: {detail}")
    return buf


def _partial_say_next(buf):
    """Extract the (possibly incomplete) say_next string value from a streaming JSON
    buffer. Returns (text, complete) or None if the key hasn't appeared yet."""
    m = re.search(r'"say_next"\s*:\s*"', buf)
    if not m:
        return None
    out = []
    i = m.end()
    while i < len(buf):
        ch = buf[i]
        if ch == "\\" and i + 1 < len(buf):
            nxt = buf[i + 1]
            out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\", "/": "/"}.get(nxt, nxt))
            i += 2
            continue
        if ch == '"':
            return "".join(out), True
        out.append(ch)
        i += 1
    return "".join(out), False


def _node_coach_fused(prior_step, ctx, rep_identity, persona_prompt, staircase_block, key,
                      model="gpt-4o", prior_say_next=None, transcript_tail=None, latest=None,
                      prior=None, on_saynext=None):
    """Fused Node 1+2+3: stage classification + signal detection + the coaching line
    in ONE streamed gpt-4o call. The output JSON leads with say_next so the UI can
    render the rep's line while the call-state fields are still streaming in.
    on_saynext(text, complete) fires as the say_next string grows."""
    system = (persona_prompt.replace("{rep_identity}", rep_identity)
              + "\n\n" + _NODE_ANALYZE_SYSTEM + _NODE3_CONTRACT + _FUSED_OUTPUT_OVERRIDE)
    owner_raw = (ctx.get("owner") or "").strip()
    prospect_first = owner_raw.split()[0].rstrip(",.").title() if owner_raw else "[Name]"
    rep_first_name = _parse_rep_identity(rep_identity)[0]
    staircase_block = staircase_block.replace("{rep_first_name}", rep_first_name)
    prior = prior or {}
    user_msg = (
        f"PROSPECT FIRST NAME (use this exact name when adapting exemplars): {prospect_first}\n\n"
        f"PRIOR CALL STATE (carried from the previous coaching turn — advance from here, "
        f"do not restart): step={prior_step}  "
        f"checklist={json.dumps(prior.get('checklist') or {})}  "
        f"prospect_intel={json.dumps(prior.get('prospect_intel') or {})}  "
        f"condition_intel={json.dumps(prior.get('condition_intel') or {})}  "
        f"prior_play={prior.get('play') or 'null'}\n\n"
        + (f"PRIOR COACHED LINE (the rep already delivered this — do NOT repeat it or re-ask a "
           f"question the prospect just answered; advance to the NEXT beat): \"{prior_say_next}\"\n\n"
           if prior_say_next else "")
        + f"LEAD CONTEXT:\n{json.dumps(ctx, indent=1)}\n\n"
        + (f"TRANSCRIPT (last 2000 chars — what has actually been said; follow up on what the "
           f"prospect ACTUALLY said, using their own words):\n{transcript_tail}\n\n"
           if transcript_tail else "")
        + (f"LATEST PROSPECT LINE (analyze this for the signal jobs; say_next answers it "
           f"first): \"{latest}\"\n"
           if latest
           else "LATEST PROSPECT LINE: (none — rep is speaking; return null/neutral signal "
                "fields and hold the prior coached line per the HOLD RULE)\n")
        + staircase_block
        + "\n\nFINAL SELF-CHECK — reject and rewrite your own say_next if it fails ANY of these:\n"
          "1. Does it restate the prospect's own words back to them as an observation "
          "('sounds like you...', 'so what you're saying is...', 'it sounds like you're feeling...')? "
          "If they just said it plainly, REPLACE that opener with a one-beat acknowledgment "
          "('Got it.', 'Okay.', 'That's exactly why I called.') and move forward.\n"
          "2. Has the prospect already said they want it fixed but don't know how? Then this "
          "line MUST be the urgency_math beat or the pitch — NOT another discovery question.\n"
          "3. Does it ask anything the prospect already answered in the transcript? If yes, "
          "advance to the next unanswered beat instead.\n"
          "4. Any sale / cash-offer / 'get out from under' language while the pivot gate is "
          "closed? Remove it.\n"
          "5. Did the prospect's LATEST line contain a direct question ('what's going on', "
          "'what is this about', 'can you explain', 'who are you')? Then say_next MUST open "
          "with a ONE-SENTENCE factual answer built from LEAD CONTEXT — answering a question "
          "with another question or jumping to the agenda ask is an automatic rewrite.\n"
          "6. Does the name/identity the prospect just gave match the lead owner in LEAD "
          "CONTEXT? If NOT — or identity is still unverified — say_next MUST verify who they "
          "are and their relationship to the property FIRST: no pitch, no agenda ask, no "
          "violation details, no urgency math until identity is confirmed. EXAMPLE: the rep "
          "asked 'is this Sharp?' and the prospect replied 'yeah, this is Sam' — that is a "
          "MISMATCH. Do NOT pitch Sam. Verify: 'Sorry about that, Sam — I was trying to reach "
          "[owner name], the owner of [address]. Is he available, or do you handle things for "
          "the property?'\n"
          "7. Did the prospect say they were AWARE of the violation? Then any 'I figured you "
          "didn't know / wouldn't have the details' phrasing is an automatic rewrite — that "
          "beat is for unaware prospects only.\n"
          "8. Did the prospect already grant permission or say 'fire away' / 'go ahead'? Then "
          "re-asking for permission is an automatic rewrite — ask the discovery question.\n"
          "9. Does the line refer to 'the owner' in third person while the person on the phone "
          "IS the confirmed owner? Automatic rewrite — talk to them AS the owner.\n"
          "10. Does the line ask for a fact the prospect already stated in the transcript "
          "(how long, who lives there, what the letter said)? Automatic rewrite — build on "
          "their answer instead of re-asking it.\n\n"
          "Respond with the ONE fused JSON object from the OUTPUT FORMAT OVERRIDE — "
          "say_next FIRST, JSON only."
    )
    def _on_buf(buf):
        if not on_saynext:
            return
        ps = _partial_say_next(buf)
        if ps:
            on_saynext(ps[0], ps[1])
    raw = _openai_chat_stream(key, model, system, user_msg, max_tokens=800, on_buf=_on_buf)
    result = json.loads(raw)
    if not isinstance(result.get("prospect_intel"), dict):
        result["prospect_intel"] = {}
    if not isinstance(result.get("condition_intel"), dict):
        result["condition_intel"] = {}
    return result


def _inject_offer_engine(ctx, d, play, is_custom, cond):
    """Price the deal from the given condition intel and attach offer_engine to ctx."""
    if is_custom:
        return
    arv = (ctx.get("valuation") or {}).get("arv")
    wholesale_mode = (play == "WHOLESALE" or (d.get("playbook_id") or "").strip() == "wholesale")
    if arv and (wholesale_mode or _pivot_armed_yes(ctx)):
        ob = offer_engine.offer_block(arv, cond or {})
        if ob:
            ctx["offer_engine"] = ob


def _prior_hold_payload(prior, offer_out=None):
    """Standard analysis shape when nothing changed — hold the prior card, zero LLM cost."""
    return {"analysis": {
        "objection":            None,
        "say_next":             prior.get("say_next", ""),
        "alt_suggestion":       prior.get("alt_suggestion"),
        "context_line":         "Rep is speaking.",
        "coach_type":           "discovery",
        "staircase_step":       prior.get("staircase_step") or "intro",
        "qualification_verdict": prior.get("qualification_verdict", "undetermined"),
        "play":                 prior.get("play"),
        "checklist":            prior.get("checklist") or {
                                    "intro": False, "qualified": False,
                                    "play_selected": False, "committed": False
                                },
        "next_action":          "",
        "summary":              "No meaningful change — holding current coaching.",
        "temperature":          "neutral",
        "rep_misquote":         None,
        "prospect_contradiction": None,
        "fact_correction":      None,
        "condition_intel":      prior.get("condition_intel") or {},
        "offer_engine":         offer_out,
        "prospect_intel":       prior.get("prospect_intel") or {
                                    "properties_owned": None, "urgency": None,
                                    "decision_maker": None, "desired_outcome": None,
                                    "stated_number": None
                                }
    }}


def _reask_guard(say_next, transcript):
    """Deterministic re-ask detector: the prospect's own lines are scanned for facts
    they ALREADY volunteered (duration, occupancy, awareness). If say_next then asks
    for that same fact, return a human-readable violation reason — else None.
    This catches the exemplar-pull failure mode prompts alone kept missing: the model
    reaches for the locked 'how long has the city been flagging you' beat even when
    the prospect literally just said 'a year and a half or 2 years'."""
    if not say_next or "?" not in say_next:
        return None
    prospect_lines = " ".join(
        ln.split(":", 1)[1] for ln in (transcript or "").splitlines()
        if ln.strip().upper().startswith("PROSPECT:"))
    if not prospect_lines.strip():
        return None
    checks = [
        (re.compile(r"\b\d+\s*(year|month|week|day)s?\b|year and a half|couple (of )?(year|month|week)s", re.I),
         re.compile(r"how long|since when|when did (this|the city|they|it) (start|begin)", re.I),
         "how long it's been going on"),
        (re.compile(r"\btenant|rent(er|ing|ed)|lives? (there|in)\b", re.I),
         re.compile(r"who (lives|is living)|anyone (living|live) (there|in)|is it (vacant|occupied|rented)|do you (live|rent)", re.I),
         "who lives at the property / occupancy"),
        (re.compile(r"\baware\b|knew about|got (a|the) letter|heard about|already know", re.I),
         re.compile(r"(did|were|are) you (know|aware)|have you heard|did you know", re.I),
         "whether they were aware of the violation"),
    ]
    for fact_re, ask_re, label in checks:
        if fact_re.search(prospect_lines) and ask_re.search(say_next):
            return ("The prospect ALREADY told you " + label + " in the transcript. "
                    "Re-asking a fact they volunteered proves the rep wasn't listening. "
                    "Build on their stated answer or move to a DIFFERENT unanswered beat.")
    return None


def _ep_analyze_fused(d, c, ctx, persona_prompt, rep_identity, play, is_custom,
                      prior, latest, t, key, on_partial):
    """Fused path: one streamed gpt-4o call returns both the call-state analysis and
    the coaching line. Post-processing mirrors the legacy path exactly: monotonic
    checklist, never-lose-a-fact intel merge, condition merge + re-price, and the
    hard pivot-gate regeneration."""
    prior_step = prior.get("staircase_step") or "intro"
    prior_intel = prior.get("prospect_intel") or {}
    staircase_block = "" if is_custom else _build_staircase_block(prior_step)
    coach_model = (c.get("coach_model") or "gpt-4o").strip() or "gpt-4o"
    result = _node_coach_fused(
        prior_step, ctx, rep_identity, persona_prompt, staircase_block, key,
        model=coach_model, prior_say_next=prior.get("say_next"),
        transcript_tail=t[-2000:], latest=latest, prior=prior, on_saynext=on_partial)

    current_step = result.get("staircase_step") or prior_step
    # Monotonic checklist — never regress a true item (same safety net as legacy)
    ck = result.get("checklist") or {}
    prior_ck = prior.get("checklist") or {}
    for k in ("intro", "qualified", "play_selected", "committed"):
        if prior_ck.get(k) and not ck.get(k):
            ck[k] = True
    if not ck:
        ck = {"intro": False, "qualified": False, "play_selected": False, "committed": False}
    # Merge intel — never lose a known fact
    new_intel = result.get("prospect_intel") or {}
    merged_intel = {k: (new_intel.get(k) or prior_intel.get(k))
                    for k in ("properties_owned", "urgency", "awareness", "decision_maker",
                              "desired_outcome", "stated_number")}
    # Merge condition intel across turns, then re-price for the response payload
    merged_cond = dict(prior.get("condition_intel") or {})
    for k, v in (result.get("condition_intel") or {}).items():
        if v is not None:
            merged_cond[k] = v
    offer_out = ctx.get("offer_engine")
    if not is_custom:
        arv = (ctx.get("valuation") or {}).get("arv")
        wholesale_mode = (play == "WHOLESALE"
                          or (d.get("playbook_id") or "").strip() == "wholesale")
        if arv and (wholesale_mode or _pivot_armed_yes(ctx)):
            ob = offer_engine.offer_block(arv, merged_cond)
            if ob:
                offer_out = ob
    # Hard pivot gate — same enforcement as the legacy path
    say_next = result.get("say_next") or ""
    if not is_custom and not _pivot_armed_yes(ctx) and _PIVOT_PHRASES_RE.search(say_next):
        signals_for_regen = {
            "objection": result.get("objection"),
            "context_line": result.get("context_line") or "",
            "temperature": result.get("temperature") or "neutral",
            "rep_misquote": result.get("rep_misquote"),
            "prospect_contradiction": result.get("prospect_contradiction"),
            "fact_correction": result.get("fact_correction"),
            "condition_intel": merged_cond,
            "prospect_intel": merged_intel,
        }
        regen = _node_coach(current_step, signals_for_regen, ctx, rep_identity, persona_prompt,
                            staircase_block, key, model=coach_model,
                            prior_say_next=prior.get("say_next"),
                            transcript_tail=t[-1200:],
                            extra_note=("The wholesale pivot gate is CLOSED on this call — the "
                                        "prospect has shown no distress language and this is not an "
                                        "armed multi-signal lead. No selling, cash offers, or 'getting "
                                        "out from under the property' language. Coach the compliance "
                                        "play only."))
        if regen.get("say_next"):
            result["say_next"] = regen["say_next"]
            result["alt_suggestion"] = regen.get("alt_suggestion") or result.get("alt_suggestion")
            result["coach_type"] = regen.get("coach_type") or result.get("coach_type")
            result["play"] = regen.get("play") or result.get("play")

    # Deterministic re-ask guard: if the line asks for a fact the prospect already
    # volunteered (duration, occupancy, awareness), force one regeneration.
    reask_note = _reask_guard(result.get("say_next") or "", t)
    if reask_note:
        signals_for_regen = {
            "objection": result.get("objection"),
            "context_line": result.get("context_line") or "",
            "temperature": result.get("temperature") or "neutral",
            "rep_misquote": result.get("rep_misquote"),
            "prospect_contradiction": result.get("prospect_contradiction"),
            "fact_correction": result.get("fact_correction"),
            "condition_intel": merged_cond,
            "prospect_intel": merged_intel,
        }
        regen = _node_coach(current_step, signals_for_regen, ctx, rep_identity, persona_prompt,
                            staircase_block, key, model=coach_model,
                            prior_say_next=prior.get("say_next"),
                            transcript_tail=t[-1200:], extra_note=reask_note)
        if regen.get("say_next") and not _reask_guard(regen["say_next"], t):
            result["say_next"] = regen["say_next"]
            result["alt_suggestion"] = regen.get("alt_suggestion") or result.get("alt_suggestion")
            result["coach_type"] = regen.get("coach_type") or result.get("coach_type")
            result["play"] = regen.get("play") or result.get("play")

    return {"analysis": {
        "objection":            result.get("objection"),
        "say_next":             result.get("say_next", ""),
        "alt_suggestion":       result.get("alt_suggestion"),
        "context_line":         result.get("context_line", ""),
        "coach_type":           result.get("coach_type", "discovery"),
        "staircase_step":       current_step,
        "qualification_verdict": result.get("qualification_verdict", "undetermined"),
        "play":                 result.get("play"),
        "checklist":            ck,
        "next_action":          result.get("next_action", ""),
        "summary":              result.get("summary", ""),
        "temperature":          result.get("temperature", "neutral"),
        "rep_misquote":         result.get("rep_misquote"),
        "prospect_contradiction": result.get("prospect_contradiction"),
        "fact_correction":      result.get("fact_correction"),
        "condition_intel":      merged_cond,
        "offer_engine":         offer_out,
        "prospect_intel":       merged_intel
    }}


def _build_state_block(prior):
    """Return the CURRENT CALL STATE block to inject when prior_state is present."""
    if not prior:
        return ""
    pi = prior.get("prospect_intel") or {}
    pillars_known = []
    if pi.get("urgency"):
        pillars_known.append("need_greed")
    if pi.get("decision_maker"):
        pillars_known.append("authority")
    if pi.get("stated_number") is not None:
        pillars_known.append("money")
    # time is carried by urgency — mark separately if urgency is set
    if pi.get("urgency"):
        pillars_known.append("time")
    pillars_str = ", ".join(sorted(set(pillars_known))) if pillars_known else "none yet"
    return (
        "\nCURRENT CALL STATE (carried from the previous coaching turn — advance from here, "
        "do not restart):\n"
        f"  staircase_step: {prior.get('staircase_step', 'intro')}\n"
        f"  checklist: {json.dumps(prior.get('checklist') or {})}\n"
        f"  pillars_known: {pillars_str}\n"
        f"  prospect_intel: {json.dumps(pi)}\n"
        "  prior_play: " + str(prior.get("play") or "null") + "\n"
        "RULES:\n"
        "  - Do NOT mark a checklist item false once true unless the prospect explicitly "
        "contradicts it.\n"
        "  - Do NOT regress to an earlier staircase step unless the prospect forced it "
        "(a new objection may reopen a prior step).\n"
        "  - If all four qualification pillars are known, advance staircase_step to commitment.\n"
        "  - If pillars FAIL (no money, no authority, no urgency), coach the disqualify path "
        "and set qualification_verdict to 'fail'.\n"
    )


def _intel_changed(new_intel, old_intel):
    """Return True if any intel field gained a non-null value it didn't have before."""
    for k in ("properties_owned", "urgency", "awareness", "decision_maker", "desired_outcome", "stated_number"):
        if new_intel.get(k) and not old_intel.get(k):
            return True
    return False


def ep_analyze(d, on_partial=None):
    c = _local_cfg()
    key = c.get("openai_key")
    if not key:
        return {"error": "no openai_key in cc_config.json"}
    opening = bool(d.get("opening"))
    t = (d.get("transcript") or "").strip()
    if not t and not opening:
        return {"error": "no transcript"}

    # ── Node 0: Opener — no LLM, pure template fill ───────────────────────────
    if opening and not t:
        return _node_opener(d, c)

    # ── Ongoing: 3-node pipeline ──────────────────────────────────────────────
    play = (d.get("play") or "GENERAL").upper()
    rep_identity = c.get("rep_identity", "Sean with Risk & Compliance Bureau")
    personas = _load_personas()
    persona_id = d.get("persona_id") or "guts_diamond"
    persona = personas.get(persona_id) or personas.get("guts_diamond") or next(iter(personas.values()))
    playbooks = _load_playbooks()
    playbook_block = _build_playbook_block(playbooks.get((d.get("playbook_id") or "").strip()) or {})

    # ── Custom play: swap ctx + prepend domain-override to persona ────────────
    custom = d.get("custom") or {}
    is_custom = (play == "CUSTOM") and bool(custom)
    if is_custom:
        ctx = _build_custom_ctx(custom)
        # Custom: use first name only — never leak the property/compliance agency
        rep_identity = _parse_rep_identity(rep_identity)[0]
        persona_prompt = _CUSTOM_DOMAIN_OVERRIDE + persona["system_prompt"]
        staircase_block_custom = ""  # No property exemplars in custom mode
    else:
        stakes_text, is_crisis = COACH_STAKES.get(play, COACH_STAKES["GENERAL"])
        ctx = {
            "play": play,
            "stakes_for_this_play": stakes_text,
            "crisis_situation": is_crisis,
            "crisis_rule": ("YES — crisis. NEVER charge the owner directly. "
                            "Contractor-referral or debt-payoff play only." if is_crisis
                            else "No — standard violation, direct fees ok."),
            "owner": d.get("owner") or "(unknown)",
            "address": d.get("address") or "(unknown)",
            "case_id": d.get("case_id") or "(unknown)",
            "fee": d.get("fee") or "(not set)",
            "notes": d.get("notes") or "(none)",
            "active_playbook": playbook_block or "(none selected — coach from persona doctrine alone)",
        }
        persona_prompt = persona["system_prompt"]

    # Rep performance profile: accumulated training grades steer this coach — weak
    # categories get drilled preemptively, strong areas get trusted.
    _profile_block = _get_profile_context()
    if _profile_block:
        ctx["rep_profile"] = _profile_block

    # Signal intel (GUTS Phase 2): stacked-signal severity arms the pivot gate.
    if not is_custom:
        li = d.get("lead_intel") or {}
        sigs = li.get("signals") or []
        if isinstance(sigs, str):
            try:
                sigs = json.loads(sigs)
            except Exception:
                sigs = [sigs]
        sev = (li.get("severity") or "").upper() or _severity_for(sigs)
        try:
            sig_count = int(li.get("signal_count") or 0) or len(sigs)
        except (TypeError, ValueError):
            sig_count = len(sigs)
        _wholesale_selected = ((d.get("playbook_id") or "").strip() == "wholesale"
                               or play == "WHOLESALE")
        ctx["signal_intel"] = {
            "signals": sigs,
            "signal_count": sig_count,
            "severity": sev,
            "pivot_armed": (
                "YES — wholesale acquisition mode selected. This call IS the wholesale "
                "conversation: repair interview, anchoring, and offer flow are in bounds. "
                "The rep still never names the first number until the offer beat is earned."
                if _wholesale_selected else
                "YES — multi-signal distressed lead. Secure the $250 filing FIRST, "
                "then the wholesale pivot gate is OPEN. Watch for distress language "
                "('I'm just done with it', 'I can't keep up', 'I just want out')."
                if sig_count >= 2 or sev in ("HIGH", "CRITICAL") else
                "NO — single-signal lead. Compliance play only; do NOT pivot to "
                "wholesale on this call."),
        }
        # Phase 3: pre-computed BRIEF-state valuation rides with lead_intel.
        val = li.get("valuation") or {}
        if val.get("arv"):
            ctx["valuation"] = {
                "arv": val.get("arv"), "est_repairs": val.get("est_repairs"),
                "mao": val.get("mao"), "offer_range": [val.get("offer_low"), val.get("offer_high")],
                "equity_band": val.get("equity_band"), "occupancy": val.get("occupancy"),
                "source": val.get("source"),
                "anchor_rule": ("Arm the rep with this range — the rep NEVER names the first "
                                "number. If the prospect asks what we'd pay: 'It depends on "
                                "condition — what would you need to walk away?' Equity band "
                                "picks the fork: fat = cash-first, thin = lease option first."),
            }

    # Prospect-corrected fact base: once the prospect corrects the record mid-call
    # (e.g. not STR — the letter is about an unpermitted rear structure), the UI sends the
    # correction back on every subsequent turn so urgency math / pitch / referrals all use
    # the TRUE fact instead of the original lead data.
    fact_override = (d.get("fact_override") or "").strip()
    if fact_override and not is_custom:
        ctx["corrected_fact"] = (
            fact_override + "  — the prospect corrected the record. Use THIS fact for the "
            "urgency math, the pitch, and any referral language, NOT the original lead data."
        )

    prior = d.get("prior_state") or {}
    latest = (d.get("latest") or "").strip()

    # ── Fused pipeline (default): ONE streamed gpt-4o call does analysis + coaching ──
    # Kill-switch: set "coach_pipeline": "legacy" in cc_config.json to force the old
    # two-call path. Any fused failure falls through to legacy automatically.
    if ((c.get("coach_pipeline") or "fused").strip().lower() != "legacy"):
        # Cheap hold: rep is speaking (no new prospect line) and a card is already on
        # screen — return it with zero LLM cost and zero latency.
        if not latest and prior.get("say_next"):
            return _prior_hold_payload(prior)
        # Offer engine: inject numbers priced from condition intel known BEFORE this
        # turn (one-turn lag vs. legacy — the fused model extracts this turn's condition
        # answers in the same pass that writes the line, so they can't feed back into
        # its own prompt). The response payload re-prices with the fresh answers, so
        # the numbers on the rep's screen are never stale.
        _inject_offer_engine(ctx, d, play, is_custom, prior.get("condition_intel") or {})
        try:
            return _ep_analyze_fused(d, c, ctx, persona_prompt, rep_identity, play,
                                     is_custom, prior, latest, t, key, on_partial)
        except Exception:
            pass  # fall through to the legacy two-call path

    # Node 1+2 merged: stage classification + signal detection in one gpt-4o-mini call.
    # Called unconditionally, same as Node 1 always was — when `latest` is empty (rep is
    # speaking, no new prospect line), this costs the same one call classification alone
    # already cost, and the model returns null/neutral signal fields per its own
    # instructions rather than a hardcoded stub. When `latest` IS present, this replaces
    # two calls (classify + signals) with one.
    prior_intel = prior.get("prospect_intel") or {}
    analysis = _node_analyze(t, latest, prior, key)
    current_step = analysis.get("staircase_step") or (prior.get("staircase_step") or "intro")
    stage = analysis
    if latest:
        # Merge new intel with prior — never lose a known fact
        new_intel = analysis.get("prospect_intel") or {}
        analysis["prospect_intel"] = {
            k: (new_intel.get(k) or prior_intel.get(k))
            for k in ("properties_owned", "urgency", "awareness", "decision_maker", "desired_outcome", "stated_number")
        }
        signals = analysis
    else:
        signals = {
            "objection": None,
            "context_line": "Rep is speaking.",
            "temperature": "neutral",
            "rep_misquote": None,
            "prospect_contradiction": None,
            "fact_correction": None,
            "condition_intel": prior.get("condition_intel") or {},
            "prospect_intel": prior_intel or {
                "properties_owned": None, "urgency": None,
                "awareness": None, "decision_maker": None, "desired_outcome": None, "stated_number": None
            }
        }

    # ── Live underwriting (offer engine): merge condition answers across turns,
    # then re-price the deal. Injected into ctx only when the call is wholesale-
    # relevant (wholesale playbook OR an armed pivot) and we have an ARV — a
    # single-signal compliance call never sees cash-offer numbers.
    prior_cond = prior.get("condition_intel") or {}
    merged_cond = dict(prior_cond)
    for _k, _v in (signals.get("condition_intel") or {}).items():
        if _v is not None:
            merged_cond[_k] = _v
    signals["condition_intel"] = merged_cond
    if not is_custom:
        _arv = (ctx.get("valuation") or {}).get("arv")
        _wholesale_mode = (play == "WHOLESALE"
                           or (d.get("playbook_id") or "").strip() == "wholesale")
        if _arv and (_wholesale_mode or _pivot_armed_yes(ctx)):
            _ob = offer_engine.offer_block(_arv, merged_cond)
            if _ob:
                ctx["offer_engine"] = _ob

    # ── Node 3 gate: skip gpt-4o when nothing meaningful changed ──────────────
    # Conditions to skip: step unchanged + no new objection + no new intel fields
    # + no consistency flag + the prospect's latest line is NOT a substantive
    # answer + we have a prior say_next to return.
    # The substantive-answer clause matters: when the rep's last card was a
    # question and the prospect just gave a real answer (6+ words), the coach
    # MUST advance to the next question — holding the prior card would repeat
    # a question the prospect already answered.
    prior_step = prior.get("staircase_step") or "intro"
    _latest_substantive = len(latest.split()) >= 6
    skip_node3 = (
        bool(prior.get("say_next"))
        and current_step == prior_step
        and not signals.get("objection")
        and not signals.get("rep_misquote")
        and not signals.get("prospect_contradiction")
        and not _latest_substantive
        and not _intel_changed(signals.get("prospect_intel") or {}, prior_intel)
    )
    if skip_node3:
        coach_out = {
            "say_next":       prior.get("say_next", ""),
            "alt_suggestion": prior.get("alt_suggestion"),
            "coach_type":     "discovery",
            "next_action":    "",
            "summary":        "No meaningful change — holding current coaching.",
            "play":           prior.get("play")
        }
    else:
        # Node 3: Generate coaching line (gpt-4o, strict exemplar matching)
        staircase_block = staircase_block_custom if is_custom else _build_staircase_block(current_step)
        coach_model = (c.get("coach_model") or "gpt-4o").strip() or "gpt-4o"
        coach_out = _node_coach(current_step, signals, ctx, rep_identity, persona_prompt, staircase_block, key,
                                model=coach_model,
                                prior_say_next=prior.get("say_next"),
                                transcript_tail=t[-1200:])
        # Hard pivot gate: if the gate is closed and the model still tried to pivot to a
        # sale/cash offer, force one regeneration with the violation spelled out.
        if not is_custom and not _pivot_armed_yes(ctx) and _PIVOT_PHRASES_RE.search(coach_out.get("say_next") or ""):
            coach_out = _node_coach(current_step, signals, ctx, rep_identity, persona_prompt, staircase_block, key,
                                    model=coach_model,
                                    prior_say_next=prior.get("say_next"),
                                    transcript_tail=t[-1200:],
                                    extra_note=("The wholesale pivot gate is CLOSED on this call — the "
                                                "prospect has shown no distress language and this is not an "
                                                "armed multi-signal lead. No selling, cash offers, or 'getting "
                                                "out from under the property' language. Coach the compliance "
                                                "play only."))

    # Merge all node outputs into the standard analysis JSON shape the frontend expects
    return {
        "analysis": {
            "objection":            signals.get("objection"),
            "say_next":             coach_out.get("say_next", ""),
            "alt_suggestion":       coach_out.get("alt_suggestion"),
            "context_line":         signals.get("context_line", ""),
            "coach_type":           coach_out.get("coach_type", "discovery"),
            "staircase_step":       current_step,
            "qualification_verdict": stage.get("qualification_verdict", "undetermined"),
            "play":                 coach_out.get("play"),
            "checklist":            stage.get("checklist") or {
                                        "intro": False, "qualified": False,
                                        "play_selected": False, "committed": False
                                    },
            "next_action":          coach_out.get("next_action", ""),
            "summary":              coach_out.get("summary", ""),
            "temperature":          signals.get("temperature", "neutral"),
            "rep_misquote":         signals.get("rep_misquote"),
            "prospect_contradiction": signals.get("prospect_contradiction"),
            "fact_correction":      signals.get("fact_correction"),
            "condition_intel":      signals.get("condition_intel") or {},
            "offer_engine":         ctx.get("offer_engine"),
            "prospect_intel":       signals.get("prospect_intel") or {}
        }
    }

# ── Pivot gate enforcement (hard, server-side) ───────────────────────────────
_PIVOT_PHRASES_RE = re.compile(
    r"get out from under|walk away from|sell (the|your|this) (house|property)|"
    r"cash offer|buy (your|the|this) (house|property)|take (this|the) property off your hands",
    re.I)

def _pivot_armed_yes(ctx):
    si = (ctx or {}).get("signal_intel") or {}
    return str(si.get("pivot_armed") or "").startswith("YES")


def _parse_dt(raw):
    clean = (raw or "").replace("Z", "").replace("T", " ").split(".")[0].split("+")[0].strip()
    if not clean:
        return None
    try:
        return datetime.strptime(clean, "%Y-%m-%d %H:%M:%S") if len(clean) > 16 else datetime.strptime(clean, "%Y-%m-%d %H:%M")
    except Exception:
        return None

def ep_call_end(d):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    phone = (d.get("phone") or "").strip()
    started = d.get("started_at") or now
    rep_notes = (d.get("notes") or "").strip()
    # Duration: started_at -> true call end. The UI sends ended_at captured at
    # the Twilio disconnect event; without it, duration would keep growing
    # until the rep picks a disposition (minutes of dead wrap time counted
    # as talk time). Fall back to 'now' only for older clients.
    dur = 0
    try:
        s = _parse_dt(started)
        e = _parse_dt(d.get("ended_at")) or datetime.now()
        if s:
            dur = max(0, int((e - s).total_seconds()))
    except Exception:
        pass
    con = db()
    cur = con.execute(
        "INSERT INTO calls(phone,play,owner,address,case_id,started_at,ended_at,duration,"
        "disposition,follow_up_date,transcript,recording,coach_log,rep_notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (phone, d.get("play", ""), d.get("owner", ""), d.get("address", ""),
         d.get("case_id", ""), started, now, dur,
         d.get("disposition", "no_answer"), d.get("follow_up_date", ""),
         d.get("transcript", ""), d.get("recording", ""),
         d.get("coach_log", ""), rep_notes))
    sid = cur.lastrowid
    # Lite-CRM write-back: tag every imported lead with this phone number.
    # status tracks the latest disposition; 'dnc' is sticky forever. notes is
    # an append-only log so rep observations survive between sessions.
    # PROTECTED STAGES (port of datacenter2 dispoMap.ts's PROTECTED_STAGES):
    # a 'paid' lead is never silently downgraded by a later stale no_answer /
    # followup from a queue re-dial -- only another explicit 'paid' keeps it,
    # and 'dnc' always wins because compliance beats everything.
    dispo = d.get("disposition", "no_answer") or "no_answer"
    norm = _normalize_phone(phone)
    if norm:
        try:
            tag = "[" + now + "] " + dispo + (": " + rep_notes if rep_notes else "")
            rows = con.execute("SELECT id, phone, status, notes FROM imported_leads").fetchall()
            for r in rows:
                if _normalize_phone(r["phone"] or "") != norm:
                    continue
                new_notes = ((r["notes"] or "") + "\n" + tag).strip()
                cur = (r["status"] or "")
                if cur == "dnc" or (cur == "paid" and dispo not in ("paid", "dnc")):
                    con.execute("UPDATE imported_leads SET notes=? WHERE id=?",
                                (new_notes, r["id"]))
                else:
                    con.execute("UPDATE imported_leads SET status=?, notes=? WHERE id=?",
                                (dispo, new_notes, r["id"]))
        except Exception:
            pass  # tagging failure must never lose the call row itself
    con.commit()
    con.close()
    # Background: GPT-4o summary + next-call prep
    transcript = (d.get("transcript") or "").strip()
    if transcript:
        threading.Thread(target=_post_call_ai, args=(sid,), daemon=True).start()
        threading.Thread(target=_score_session, args=(sid,), daemon=True).start()
    return {"ok": True, "session_id": sid}

def _fmt_dur(sec):
    sec = int(sec or 0)
    return "%d:%02d" % (sec // 60, sec % 60)

def _render_call_export(row, log_events):
    """Clean Call Transcript — rep + prospect only."""
    owner = row.get("owner") or row.get("phone") or "Unknown"
    lines = [
        "# Call Transcript — " + owner,
        "**Date:** " + (row.get("started_at") or "")[:16] +
        "  ·  **Duration:** " + _fmt_dur(row.get("duration")) +
        "  ·  **Disposition:** " + (row.get("disposition") or ""),
        "**Phone:** " + (row.get("phone") or "") +
        "  ·  **Address:** " + (row.get("address") or "") +
        "  ·  **Case:** " + (row.get("case_id") or ""),
        "**Play:** " + (row.get("play") or ""),
        "", "---", "",
    ]
    if log_events:
        for e in log_events:
            if e.get("type") not in ("rep", "prospect"):
                continue
            speaker = "REP" if e["type"] == "rep" else "PROSPECT"
            tag = " [SCREENING]" if e.get("screening") else ""
            lines.append("[" + e.get("t", "00:00") + "] " + speaker + ":" + tag + " " + e.get("text", ""))
    else:
        raw = (row.get("transcript") or "").strip()
        if raw:
            lines.append("*(coach log not captured for this call — raw transcript below)*")
            lines.append("")
            lines.extend(raw.splitlines())
        else:
            lines.append("*(no transcript captured)*")
    lines.extend(["", "---", "*Cell Coach · clean call transcript · rep + prospect only*"])
    return "\n".join(lines)

def _render_coaching_export(row, log_events):
    """Coaching Review Transcript — all three parties, paired layout + raw JSON."""
    owner = row.get("owner") or row.get("phone") or "Unknown"
    # Stats
    coach_fires = {"gpt": 0, "instant": 0, "screening": 0}
    final_ck = {}
    for e in log_events:
        if e.get("type") == "coach":
            ct = e.get("coach_type", "")
            src = e.get("source", "gpt")
            if ct == "screening":
                coach_fires["screening"] += 1
            elif src == "instant":
                coach_fires["instant"] += 1
            else:
                coach_fires["gpt"] += 1
            if e.get("checklist"):
                final_ck = e["checklist"]
    total = sum(coach_fires.values())
    ck_str = (
        "intro " + ("✅" if final_ck.get("intro") else "❌") + " · " +
        "qualified " + ("✅" if final_ck.get("qualified") else "❌") + " · " +
        "play " + ("✅" if final_ck.get("play_selected") else "❌") + " · " +
        "committed " + ("✅" if final_ck.get("committed") else "❌")
    )
    lines = [
        "# Coaching Review — " + owner,
        "**Date:** " + (row.get("started_at") or "")[:16] +
        "  ·  **Duration:** " + _fmt_dur(row.get("duration")) +
        "  ·  **Disposition:** " + (row.get("disposition") or ""),
        "**Play:** " + (row.get("play") or ""),
        "**Coach fires:** %d  (gpt: %d · instant: %d · screening: %d)" % (
            total, coach_fires["gpt"], coach_fires["instant"], coach_fires["screening"]),
        "**Final checklist:** " + ck_str,
        "",
        "> How to read this: each PROSPECT turn is followed by the COACH's response to it,",
        "> then the REP's actual next line. Compare what the coach called to what the rep ran,",
        "> and watch how the prospect reacts on the following turn.",
        "", "---", "",
    ]
    if not log_events:
        raw = (row.get("transcript") or "").strip()
        lines.append("*(coach log not captured for this call)*")
        if raw:
            lines.extend(["", "**Raw transcript:**", ""])
            lines.extend(raw.splitlines())
        lines.extend(["", "---", "## Machine-readable event log", "```json", "[]", "```"])
        return "\n".join(lines)
    # Build coach lookup: trigger_seq -> list of coach events
    coach_by_trigger = {}
    for e in log_events:
        if e.get("type") == "coach":
            ts = e.get("trigger_seq", 0)
            coach_by_trigger.setdefault(ts, []).append(e)
    for e in log_events:
        t = e.get("type", "")
        if t == "prospect":
            tag = " [SCREENING]" if e.get("screening") else ""
            lines.append("[" + e.get("t", "00:00") + "] PROSPECT:" + tag + " " + e.get("text", ""))
            for coach in coach_by_trigger.get(e.get("seq", 0), []):
                src = coach.get("source", "gpt")
                ct = (coach.get("coach_type") or "")
                if ct == "screening":
                    badge = "(screening)"
                elif src == "instant":
                    badge = ("(instant · " + ct + ")") if ct else "(instant)"
                else:
                    badge = ("(gpt · " + ct + ")") if ct else "(gpt)"
                say = coach.get("say_next", "")
                ck = coach.get("checklist") or {}
                ck_snap = (
                    "intro" + ("✅" if ck.get("intro") else "▫") + " " +
                    "qualified" + ("✅" if ck.get("qualified") else "▫") + " " +
                    "play" + ("✅" if ck.get("play_selected") else "▫") + " " +
                    "committed" + ("✅" if ck.get("committed") else "▫")
                )
                obj = coach.get("objection") or "—"
                lines.append('        └─ COACH ' + badge + ': "' + say + '"')
                lines.append("           objection: " + obj + " · checklist: " + ck_snap)
                alt = coach.get("alt_suggestion")
                if alt:
                    lines.append('           alt: "' + alt + '"')
        elif t == "rep":
            lines.append("[" + e.get("t", "00:00") + "] REP: " + e.get("text", ""))
            lines.append("")
    lines.extend(["", "---", "## Machine-readable event log", "```json"])
    lines.append(json.dumps(log_events, indent=2, ensure_ascii=False))
    lines.append("```")
    return "\n".join(lines)

def _post_call_ai(sid):
    """After every call: GPT-4o writes summary + prep brief for the NEXT call."""
    c = _local_cfg()
    key = c.get("openai_key")
    if not key:
        return
    con = db()
    s = con.execute("SELECT * FROM calls WHERE id=?", (sid,)).fetchone()
    con.close()
    if not s:
        return
    prompt = (
        "You are reviewing a finished sales call for a code-violation rescue business.\n"
        f"PLAY: {s['play']}, CASE: {s['case_id']}, ADDRESS: {s['address']}, "
        f"OWNER: {s['owner']}. Disposition: {s['disposition']}.\n\n"
        f"TRANSCRIPT (REP/PROSPECT labeled):\n{s['transcript'][-6000:]}\n\n"
        "Return JSON only:\n"
        '{"summary": "2-3 sentence summary of what happened on this call",\n'
        ' "next_call_prep": {\n'
        '   "last_time": ["3 short bullets: what happened, what they said, where it ended"],\n'
        '   "open_objections": ["objections raised and not yet resolved"],\n'
        '   "recommended_opener": "exact words to open the NEXT call — light and natural, '
        "reference last call in one clause, then bring one NEW piece of value and a hook\"}}"
    )
    try:
        r = _http("https://api.openai.com/v1/chat/completions", "POST",
                  {"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                  {"model": "gpt-4o-mini", "temperature": 0.3,
                   "response_format": {"type": "json_object"},
                   "messages": [{"role": "user", "content": prompt}]})
        out = json.loads(r["choices"][0]["message"]["content"])
        con = db()
        con.execute("UPDATE calls SET summary=?, next_call_prep=? WHERE id=?",
                    (out.get("summary", ""), json.dumps(out.get("next_call_prep") or {}), sid))
        con.commit()
        con.close()
    except Exception as e:
        # Never swallow this silently again — a dead OpenAI key previously
        # made post-call summaries vanish with zero trace.
        print("[post_call_ai] call %s failed: %s" % (sid, e), file=sys.stderr)

def _score_session(call_id):
    """Grade the rep's performance on a completed session and update the profile."""
    time.sleep(4)  # let _post_call_ai finish first; both are daemon threads
    c = _local_cfg()
    key = c.get("openai_key")
    if not key:
        return
    con = db()
    s = con.execute("SELECT * FROM calls WHERE id=?", (call_id,)).fetchone()
    con.close()
    if not s:
        return
    transcript = (s["transcript"] or "").strip()
    # Need at least a minimal back-and-forth to score
    if not transcript or transcript.count('\n') < 3:
        return
    is_training = 1 if (s["disposition"] or "").startswith("train_") else 0
    scenario_id = s["play"] or "" if is_training else ""
    call_type = "training" if is_training else "live"
    # Playbook-aware grading: the scenario's tagged playbook supplies the specific
    # rules this session is scored against (money play, pivot gate, scope honesty).
    playbook_block = ""
    if scenario_id:
        scen = _get_scenario(scenario_id) or {}
        pb = _load_playbooks().get((scen.get("playbook_id") or "").strip()) or {}
        playbook_block = _build_playbook_block(pb)
    system_prompt = (
        "You are a G.U.T.S. sales call performance scorer. The rep uses Claude Diamond's "
        "G.U.T.S. method (Agenda → Qualification → Commitment → Close). "
        "Score the REP only. Transcript is labeled REP: and PROSPECT:.\n\n"
        "THE G.U.T.S. STAIRCASE (judge against this sequence):\n"
        "  STEP 1 — INTRO + AGENDA: Calm factual opener (name + agency + specific observed fact). "
        "Gets permission, sets roadmap, gives guilt-free exit ('if it's not a fit, just tell me'). "
        "NO authority posture, NO 'how are you doing' on crisis calls, NO feature pitch upfront.\n"
        "  STEP 2 — QUALIFICATION: Surfaces all four before presenting anything: "
        "(1) NEED/GREED — pain level 1-10, emotional trigger; "
        "(2) MONEY — can they fund a fix or is cash locked up; "
        "(3) AUTHORITY — do they decide alone or need a spouse/partner; "
        "(4) TIME — deadline, what happens if nothing changes. "
        "Also picks the play (fix/sell/lease/extension) from what THEY say. "
        "Uses negative-phrased redirection questions to pull honest answers. "
        "75% of prospects don't qualify — firing a bad prospect is a WIN.\n"
        "  STEP 3 — COMMITMENT: Isolates the one thing they care most about. "
        "Uses hypothetical close: 'Say I could get that handled — what would you say?' "
        "Prospect names the finish line themselves before any play is presented.\n"
        "  STEP 4 — PLAY + CLOSE: Presents exactly ONE play that qualification surfaced. "
        "Locks a specific day/time callback TODAY. Uses freedom close. "
        "Pins 'I'll think about it' with the pre-commitment. Captures phone + email.\n\n"
        "THE THREE MOVES (used throughout, not sequential):\n"
        "  STROKE: sincere recognition when they push back legitimately.\n"
        "  NURTURE: normalize their pain ('a lot of owners deal with the same thing').\n"
        "  REDIRECTION: short answer + question; negative phrasing to pull positive answers; "
        "OPPOSITE when they attack (never argue, never defend).\n"
        "  TAKEAWAY: when they're hot or posturing, pull back ('maybe this isn't a fit').\n\n"
        "NON-NEGOTIABLE RULES:\n"
        "  - No presentation before full qualification. Premature presentation = automatic deduction.\n"
        "  - Never be first to name a buy price.\n"
        "  - Never charge a crisis victim (fire/water/foreclosure) directly.\n"
        "  - 'I'll think about it' unchallenged = failed close.\n"
        "  - Never ASK for the order — the rep presents the path and lets the prospect decide.\n"
        "  - Every commitment ask needs a freedom close.\n\n"
        "G.U.T.S. AUDIT CRITERIA (check each explicitly):\n"
        "  1. AGENDA EARNED: did the rep get permission for questions and hand the prospect "
        "the guilt-free out BEFORE interrogating?\n"
        "  2. ZERO-AWARENESS: did the rep assume knowledge the prospect couldn't have — asking "
        "about a violation the rep hasn't revealed yet, or 'how long have you lived there' to "
        "an absentee owner? Any assumption = zero_awareness_violation.\n"
        "  3. PIVOT TIMING (playbook-gated): on compliance calls the wholesale pivot is ONLY "
        "legal AFTER the compliance service is secured AND the prospect shows distress language. "
        "Pivot earlier = pivot_too_early. Distress language ignored after the fee is secured = "
        "pivot_missed. Wholesale pitched before the filing = compliance_not_secured_first.\n"
        "  4. PRICE DELIVERY: the prospect names the first number on buy offers; the fee is "
        "stated once, plainly, AFTER the diagnosis lands — negative phrasing available "
        "('you wouldn't be open to...'). Rep naming a buy number first = named_price_first.\n\n"
        + ("PLAYBOOK RULES FOR THIS SESSION (score against these specifics):\n" + playbook_block + "\n\n"
           if playbook_block else "")
        + ("Score each category 1-10 using G.U.T.S. standards:\n"
        "- opener: Calm + factual intro pattern followed? Permission + guilt-free exit given? "
        "No authority posture, no wrong tone for the situation?\n"
        "- discovery: All four qualification pillars hit (Need/Greed, Money, Authority, Time)? "
        "Play selected FROM what prospect said, not assumed?\n"
        "- objection_handling: Stalls/objections redirected with G.U.T.S. moves? "
        "Pre-commitment cashed on 'I'll think about it'? Opposite redirection used?\n"
        "- pitch_timing: Did the rep wait until Commitment step before presenting the play? "
        "Or premature presentation before qualification complete?\n"
        "- tone: Matched prospect's emotional register? Used Stroke/Nurture/Empathy moves? "
        "Doctor posture (rep asks, prospect talks) vs. salesman posture?\n"
        "- close: Specific day/time locked TODAY? Freedom close used? Phone + email captured? "
        "Vague ending = low score.\n\n"
        "weaknesses: G.U.T.S.-specific labels only. Use these exact terms where they apply:\n"
        "  skipped_agenda, no_permission_no_roadmap, wrong_tone_for_severity, authority_posture_opener,\n"
        "  premature_presentation, skipped_qualification, missed_money_pillar, missed_authority_pillar,\n"
        "  missed_time_pillar, assumed_the_play, no_hypothetical_close, no_commitment_step,\n"
        "  let_it_think_about_it, no_freedom_close, vague_close, no_next_step_locked,\n"
        "  defended_instead_of_redirected, met_anger_with_argument, no_takeaway_on_hot_prospect,\n"
        "  named_price_first, charged_crisis_victim_directly, over_talked, lost_doctor_posture,\n"
        "  zero_awareness_violation, pivot_too_early, pivot_missed, compliance_not_secured_first,\n"
        "  asked_for_the_order\n"
        "strengths: G.U.T.S.-specific labels only. Use these exact terms where they apply:\n"
        "  clean_intro_pattern, gave_guilt_free_exit, surfaced_emotional_pain, hit_all_four_pillars,\n"
        "  fired_bad_prospect, used_redirection, used_negative_phrasing, used_stroke_move,\n"
        "  used_nurture_move, used_takeaway, locked_specific_callback, cashed_precommitment,\n"
        "  correct_play_from_qualification, one_play_only, freedom_close_used, captured_contact,\n"
        "  agenda_earned, zero_awareness_clean, pivot_timed_right, prospect_named_number_first\n"
        "- overall_grade: A/B/C/D/F\n"
        "- notes: 2-3 sentences citing G.U.T.S. Staircase steps and Moves by name. "
        "Name the exact step that was skipped or executed well.\n\n"
        'Respond ONLY with JSON: {"opener_score":int,"discovery_score":int,'
        '"objection_handling_score":int,"pitch_timing_score":int,"tone_score":int,'
        '"close_score":int,"overall_grade":"A|B|C|D|F","weaknesses":["label"],'
        '"strengths":["label"],"notes":"string"}'
        )
    )
    user_msg = (
        f"CALL TYPE: {call_type}\n"
        f"PLAY: {s['play'] or 'GENERAL'}\n"
        f"DISPOSITION: {s['disposition'] or '(none)'}\n"
        f"DURATION: {s['duration'] or 0}s\n\n"
        f"TRANSCRIPT:\n{transcript[-6000:]}\n\n"
        "Score the REP's performance. JSON only."
    )
    try:
        r = _http("https://api.openai.com/v1/chat/completions", "POST",
                  {"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                  {"model": "gpt-4o-mini", "temperature": 0.2, "max_tokens": 400,
                   "response_format": {"type": "json_object"},
                   "messages": [{"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_msg}]})
        out = json.loads(r["choices"][0]["message"]["content"])
    except Exception as e:
        # Surface scoring failures — same dead-key silent-death pattern.
        print("[score_session] call %s failed: %s" % (call_id, e), file=sys.stderr)
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    con = db()
    con.execute(
        "INSERT INTO session_scores(call_id, scored_at, is_training, scenario_id, overall_grade, "
        "opener_score, discovery_score, objection_handling_score, pitch_timing_score, "
        "tone_score, close_score, weaknesses, strengths, notes, raw_json) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (call_id, now, is_training, scenario_id,
         out.get("overall_grade", ""),
         int(out.get("opener_score") or 0),
         int(out.get("discovery_score") or 0),
         int(out.get("objection_handling_score") or 0),
         int(out.get("pitch_timing_score") or 0),
         int(out.get("tone_score") or 0),
         int(out.get("close_score") or 0),
         json.dumps(out.get("weaknesses") or []),
         json.dumps(out.get("strengths") or []),
         out.get("notes", ""),
         json.dumps(out)))
    con.execute("UPDATE calls SET scored=1 WHERE id=?", (call_id,))
    con.commit()
    con.close()
    _rebuild_profile()


# Maps grader weakness labels to the exact GUTS step they drill — the coach
# profile block uses this so weak categories point at a named staircase step.
_GUTS_STEP_MAP = {
    "skipped_agenda": "Step 1 Agenda", "no_permission_no_roadmap": "Step 1 Agenda",
    "authority_posture_opener": "Step 1 Intro posture", "wrong_tone_for_severity": "Step 1 Intro tone",
    "zero_awareness_violation": "Steps 1-2 Zero-awareness",
    "skipped_qualification": "Step 2 Qualification", "missed_money_pillar": "Step 2 Money pillar",
    "missed_authority_pillar": "Step 2 Authority pillar", "missed_time_pillar": "Step 2 Time pillar",
    "assumed_the_play": "Step 2 Play selection",
    "no_hypothetical_close": "Step 3 Commitment", "no_commitment_step": "Step 3 Commitment",
    "let_it_think_about_it": "Step 4 Close", "no_freedom_close": "Step 4 Close",
    "vague_close": "Step 4 Close", "no_next_step_locked": "Step 4 Close",
    "named_price_first": "Step 4 Price delivery",
    "pivot_too_early": "Step 4 Pivot timing", "pivot_missed": "Step 4 Pivot timing",
    "compliance_not_secured_first": "Step 4 Pivot timing",
    "asked_for_the_order": "Step 4 GUTS close",
    "premature_presentation": "Steps 2-4 Pitch timing",
    "defended_instead_of_redirected": "Moves: Redirection",
    "met_anger_with_argument": "Moves: Redirection",
    "no_takeaway_on_hot_prospect": "Moves: Takeaway",
    "over_talked": "Moves: Doctor posture", "lost_doctor_posture": "Moves: Doctor posture",
    "charged_crisis_victim_directly": "Hard rule: Crisis victims",
}

def _rebuild_profile():
    """Rebuild the aggregated rep_profile row from all session_scores."""
    con = db()
    rows = con.execute("SELECT * FROM session_scores ORDER BY id ASC").fetchall()
    pr = con.execute("SELECT manual_rules FROM rep_profile WHERE id=1").fetchone()
    manual_rules = json.loads((pr["manual_rules"] if pr else None) or "[]")
    con.close()
    if not rows:
        return
    n = len(rows)
    cats = ["opener", "discovery", "objection_handling", "pitch_timing", "tone", "close"]
    cat_sums = {c: 0.0 for c in cats}
    for r in rows:
        cat_sums["opener"]              += r["opener_score"] or 0
        cat_sums["discovery"]           += r["discovery_score"] or 0
        cat_sums["objection_handling"]  += r["objection_handling_score"] or 0
        cat_sums["pitch_timing"]        += r["pitch_timing_score"] or 0
        cat_sums["tone"]                += r["tone_score"] or 0
        cat_sums["close"]               += r["close_score"] or 0
    cat_avgs = {c: round(cat_sums[c] / n, 1) for c in cats}
    # Trend: last 5 vs. overall
    last5 = rows[-5:]
    cat_l5 = {c: 0.0 for c in cats}
    for r in last5:
        cat_l5["opener"]             += r["opener_score"] or 0
        cat_l5["discovery"]          += r["discovery_score"] or 0
        cat_l5["objection_handling"] += r["objection_handling_score"] or 0
        cat_l5["pitch_timing"]       += r["pitch_timing_score"] or 0
        cat_l5["tone"]               += r["tone_score"] or 0
        cat_l5["close"]              += r["close_score"] or 0
    cat_l5_avgs = {c: round(cat_l5[c] / len(last5), 1) for c in cats}
    def _trend(c):
        diff = cat_l5_avgs[c] - cat_avgs[c]
        if diff < -0.5: return "declining"
        if diff > 0.5:  return "improving"
        return "stable"
    # Aggregate weakness/strength labels across all sessions
    weak_counts = {}
    strong_counts = {}
    for r in rows:
        for w in json.loads(r["weaknesses"] or "[]"):
            weak_counts[w] = weak_counts.get(w, 0) + 1
        for s in json.loads(r["strengths"] or "[]"):
            strong_counts[s] = strong_counts.get(s, 0) + 1
    top_weak_labels = [k for k, _ in sorted(weak_counts.items(), key=lambda x: -x[1])[:5]]
    recurring_habits = [k for k, _ in sorted(
        list(weak_counts.items()) + list(strong_counts.items()),
        key=lambda x: -x[1]
    )[:8]]
    category_labels = {
        "opener": "Opener",
        "discovery": "Discovery / Qualification",
        "objection_handling": "Objection Handling",
        "pitch_timing": "Pitch Timing",
        "tone": "Tone / Empathy",
        "close": "Closing",
    }
    weak_cats = []
    strong_cats = []
    for c in cats:
        avg = cat_avgs[c]
        entry = {
            "category": c,
            "label": category_labels[c],
            "avg_score": avg,
            "trend": _trend(c),
            "detail": "; ".join(top_weak_labels[:3]),
            "guts_steps": sorted({_GUTS_STEP_MAP.get(w, w) for w in top_weak_labels[:5]}),
        }
        if avg < 6.0:
            weak_cats.append(entry)
        elif avg >= 8.0:
            strong_cats.append(entry)
    weak_cats.sort(key=lambda x: x["avg_score"])
    # Overall letter grade from mean of category averages
    overall_avg = sum(cat_avgs.values()) / len(cats)
    if overall_avg >= 9:   overall_grade = "A+"
    elif overall_avg >= 8: overall_grade = "A"
    elif overall_avg >= 7: overall_grade = "B"
    elif overall_avg >= 6: overall_grade = "C"
    elif overall_avg >= 5: overall_grade = "D"
    else:                   overall_grade = "F"
    last5_grades = [r["overall_grade"] for r in reversed(rows[-5:])]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    con = db()
    con.execute("""INSERT OR REPLACE INTO rep_profile(
        id, updated_at, sessions_analyzed, avg_overall,
        weak_categories, strong_categories, recurring_habits, manual_rules, last_5_grades)
        VALUES(1,?,?,?,?,?,?,?,?)""",
        (now, n, overall_grade,
         json.dumps(weak_cats), json.dumps(strong_cats),
         json.dumps(recurring_habits), json.dumps(manual_rules),
         json.dumps(last5_grades)))
    con.commit()
    con.close()


def _get_profile_context():
    """Return a formatted block with the rep's performance profile for injection into coach prompts."""
    try:
        con = db()
        row = con.execute("SELECT * FROM rep_profile WHERE id=1").fetchone()
        con.close()
        if not row or (row["sessions_analyzed"] or 0) == 0:
            return ""
        n = row["sessions_analyzed"]
        avg = row["avg_overall"] or ""
        last5 = json.loads(row["last_5_grades"] or "[]")
        weak = json.loads(row["weak_categories"] or "[]")
        strong = json.loads(row["strong_categories"] or "[]")
        habits = json.loads(row["recurring_habits"] or "[]")
        rules = json.loads(row["manual_rules"] or "[]")
        trend_sym = {"improving": "↑", "declining": "↓", "stable": "→"}
        lines = [
            f"REP PERFORMANCE PROFILE ({n} scored sessions):",
            f"Overall: {avg}  |  Last 5: {', '.join(last5) if last5 else 'N/A'}",
        ]
        if weak:
            lines.append("WEAK AREAS — prioritize coaching these:")
            for w in weak:
                sym = trend_sym.get(w.get("trend", ""), "→")
                steps = w.get("guts_steps") or []
                lines.append(f"  - {w.get('label', w.get('category', ''))}: "
                             f"avg {w.get('avg_score','?')}/10 {sym}" +
                             (" — drill: " + ", ".join(steps) if steps else ""))
        if habits:
            lines.append("RECURRING HABITS:")
            for h in habits[:5]:
                lines.append(f"  - {h}")
        if strong:
            lines.append("STRONG AREAS — trust the rep here, focus elsewhere:")
            for s in strong:
                lines.append(f"  - {s.get('label', s.get('category', ''))}: avg {s.get('avg_score','?')}/10")
        if rules:
            lines.append("REP'S CUSTOM COACHING RULES (always follow these):")
            for rule in rules:
                lines.append(f"  - {rule}")
        lines.append("Use this profile to personalize SAY THIS. When the rep is about to repeat "
                     "a known mistake, call it out preemptively in say_next or next_action.")
        return "\n".join(lines)
    except Exception:
        return ""


def _normalize_phone(raw):
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits

def ep_prep_by_phone(raw_phone):
    digits = _normalize_phone(raw_phone)
    if len(digits) < 7:
        return {"found": False}
    con = db()
    rows = con.execute(
        "SELECT * FROM calls WHERE phone!='' ORDER BY id DESC").fetchall()
    matches = [dict(r) for r in rows if _normalize_phone(r["phone"]) == digits or
               digits in _normalize_phone(r["phone"]) or _normalize_phone(r["phone"]).endswith(digits)]
    con.close()
    if not matches:
        return {"found": False}
    last = matches[0]
    prep = {}
    try:
        prep = json.loads(last.get("next_call_prep") or "{}")
    except Exception:
        pass
    return {
        "found": True,
        "count": len(matches),
        "last_disposition": last.get("disposition"),
        "summary": last.get("summary", ""),
        "recommended_opener": prep.get("recommended_opener", ""),
        "open_objections": ", ".join(prep.get("open_objections") or []),
        "play": last.get("play"),
        "owner_name": last.get("owner"),
        "address": last.get("address"),
        "case_id": last.get("case_id"),
    }

def ep_history():
    con = db()
    rows = con.execute("SELECT * FROM calls ORDER BY id DESC LIMIT 20").fetchall()
    con.close()
    return {"calls": [dict(r) for r in rows]}

# ── Twilio: JWT access token (stdlib HS256) ──────────────────────────────────
def _b64url(data):
    if isinstance(data, str):
        data = data.encode()
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def _make_twilio_token(account_sid, api_key, api_secret, identity="cellcoach",
                       twiml_app_sid=None, ttl=3600):
    """Generate a Twilio Access Token with Voice grant using HS256 JWT."""
    now = int(time.time())
    header = {"typ": "JWT", "alg": "HS256", "cty": "twilio-fpa;v=1"}
    grants = {
        "identity": identity,
        "voice": {
            "incoming": {"allow": True},
            "outgoing": {"application_sid": twiml_app_sid or ""}
        }
    }
    payload = {
        "jti": api_key + "-" + str(now),
        "iss": api_key,
        "sub": account_sid,
        "nbf": now,
        "iat": now,
        "exp": now + ttl,
        "grants": grants
    }
    # compact separators — Twilio rejects tokens with spaces in JSON
    seg = (_b64url(json.dumps(header, separators=(",", ":")).encode()) + "." +
           _b64url(json.dumps(payload, separators=(",", ":")).encode()))
    sig = hmac.new(api_secret.encode(), seg.encode(), hashlib.sha256).digest()
    return seg + "." + _b64url(sig)

def ep_twilio_token():
    c = _local_cfg()
    sid = c.get("twilio_account_sid")
    key = c.get("twilio_api_key")
    secret = c.get("twilio_api_secret")
    app_sid = c.get("twilio_twiml_app_sid", "")
    if not (sid and key and secret):
        return {"error": "Twilio keys not configured in cc_config.json"}
    try:
        token = _make_twilio_token(sid, key, secret, twiml_app_sid=app_sid)
        return {"token": token}
    except Exception as e:
        return {"error": "twilio token failed: " + str(e)}

# ── Telnyx (parallel engine — Twilio above is untouched) ───────────────────
# The browser SDK logs in with a short-lived JWT minted server-side from the
# telephony credential (POST /v2/telephony_credentials/{id}/token). We cache
# the token and re-mint only when Telnyx rejects it or it approaches expiry.
_telnyx_token_cache = {"token": "", "minted_at": 0.0}

def ep_telnyx_token(force_refresh=False):
    c = _local_cfg()
    api_key = (c.get("telnyx_api_key") or "").strip()
    cred_id = (c.get("telnyx_credential_id") or "").strip()
    if not (api_key and cred_id):
        return {"error": "Telnyx not configured — set telnyx_api_key and "
                         "telnyx_credential_id in cc_config.json"}
    if not force_refresh and _telnyx_token_cache["token"] \
            and time.time() - _telnyx_token_cache["minted_at"] < 3300:
        return {"token": _telnyx_token_cache["token"]}
    try:
        req = _urlreq.Request(
            "https://api.telnyx.com/v2/telephony_credentials/" + cred_id + "/token",
            data=b"", method="POST",
            headers={"Authorization": "Bearer " + api_key})
        with _urlreq.urlopen(req, timeout=15) as r:
            body = r.read().decode()
        # API returns the JWT as a bare JSON string
        token = json.loads(body) if body.strip().startswith('"') else body.strip()
        if not token:
            raise RuntimeError("empty token in Telnyx response")
        _telnyx_token_cache["token"] = token
        _telnyx_token_cache["minted_at"] = time.time()
        return {"token": token}
    except _urlreq.HTTPError as e:
        try:
            detail = e.read().decode()[:200]
        except Exception:
            detail = str(e)
        return {"error": "telnyx token failed: HTTP %d: %s" % (e.code, detail)}
    except Exception as e:
        return {"error": "telnyx token failed: " + str(e)[:200]}

# Phase 2 (2026-07-22): read-only DID pool lookup against lead_machine's
# command_center.db. cell_coach is a deliberately independent, standalone
# deployable (its own DB, its own port, runs with zero dependency on
# lead_machine existing at all) -- this function must NEVER hard-fail or
# raise if that DB/table isn't present, since cell_coach's core coaching
# features have nothing to do with lead_machine and must keep working
# without it. All it does here is SELECT (never INSERT/UPDATE) -- the
# actual dials_today increment happens once, in lead_machine's
# api_twilio_token, which is why the cockpit passes its already-selected
# number through as the primary path (see the "From" param check below);
# this lookup is strictly the fallback for calls that didn't come from
# that cockpit (e.g. cell_coach's own standalone dialer UI).
def _command_center_db_path():
    # Mirrors _local_cfg_path()'s own resolution rule: this file lives in
    # cell_coach/, lead_machine's DB lives in ../data/command_center.db
    # relative to the data_center root, same as lead_machine/app.py's DB.
    return os.path.join(os.path.dirname(BASE), "data", "command_center.db")

def _did_daily_cap(created_at, today=None):
    """Per-number daily dial cap. Brand-new DIDs (created on/after 2026-07-30,
    the day the 4 new Austin numbers were bought) run a 2-week warmup ramp so
    carriers don't flag them as spam: week 1 → 15/day, week 2 → 25/day, then
    the steady 40/day. Established numbers go straight to 40/day."""
    today = today or datetime.now().strftime("%Y-%m-%d")
    ca = (created_at or "")[:10]
    if ca and ca < "2026-07-30":
        return 40
    try:
        age = (datetime.strptime(today, "%Y-%m-%d")
               - datetime.strptime(ca, "%Y-%m-%d")).days
    except Exception:
        return 15  # unparseable creation date → safest cap
    if age < 7:
        return 15
    if age < 14:
        return 25
    return 40

# ── Sticky caller ID (2026-07-31) ────────────────────────────────────────────
# A prospect who called back on (or was last called from) a specific pool DID
# recognizes that number — calling them back from a DIFFERENT number throws
# away the warmest signal we have. sticky_did pairs normalized lead phone →
# pool DID; the outbound webhook prefers the pairing over round-robin, but
# only while that DID is active and under its daily cap (warmup limits always
# win over stickiness).
def _sticky_did_remember(lead_phone, did):
    """Upsert lead phone → pool DID pairing. Never raises; no-op on junk."""
    try:
        norm = _normalize_phone(lead_phone or "")
        digits = "".join(ch for ch in (did or "") if ch.isdigit())
        if len(digits) == 10:
            digits = "1" + digits
        if len(norm) < 7 or not (10 <= len(digits) <= 15):
            return
        did_e164 = "+" + digits
        con = db()
        con.execute("CREATE TABLE IF NOT EXISTS sticky_did("
                    "phone TEXT PRIMARY KEY, did TEXT, updated_at TEXT)")
        con.execute("INSERT INTO sticky_did(phone, did, updated_at) VALUES(?,?,?) "
                    "ON CONFLICT(phone) DO UPDATE SET did=excluded.did, "
                    "updated_at=excluded.updated_at",
                    (norm, did_e164,
                     datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        con.commit()
        con.close()
    except Exception:
        pass

def _sticky_did_for(lead_phone, provider="twilio"):
    """Returns the paired pool DID (E.164) for this lead if it is still
    usable: exists in did_pool, status='active', right provider, and under
    its daily cap. Otherwise '' — caller falls back to round-robin.
    Never raises."""
    try:
        norm = _normalize_phone(lead_phone or "")
        if len(norm) < 7:
            return ""
        con = db()
        con.execute("CREATE TABLE IF NOT EXISTS sticky_did("
                    "phone TEXT PRIMARY KEY, did TEXT, updated_at TEXT)")
        row = con.execute("SELECT did FROM sticky_did WHERE phone=?",
                          (norm,)).fetchone()
        con.close()
        if not row:
            return ""
        did = row["did"]
        path = _command_center_db_path()
        if not os.path.exists(path):
            return ""
        con = sqlite3.connect(path, timeout=5)
        con.row_factory = sqlite3.Row
        prow = con.execute(
            "SELECT status, provider, label, dials_today, created_at "
            "FROM did_pool WHERE phone_number=?", (did,)).fetchone()
        con.close()
        if not prow or prow["status"] != "active":
            return ""
        prov = (prow["provider"] or "").strip().lower()
        if prov and prov != provider:
            return ""
        if not prov and provider not in (prow["label"] or "").lower():
            return ""  # legacy rows: fall back to label matching like the pool lookup
        if (prow["dials_today"] or 0) >= _did_daily_cap(prow["created_at"]):
            return ""  # sticky never overrides a warmup/daily cap
        return did
    except Exception:
        return ""

def _did_pool_lookup(rep_name, provider="twilio"):
    """Returns a phone number string, or '' if the pool is unreachable/empty.
    Never raises -- every failure mode here just means 'no DID pool
    available,' handled by the existing twilio_from_number fallback in the
    caller.

    2026-07-29 bugfix: did_pool is a SHARED table (lead_machine and other
    tools write rows into it too) and previously had no `provider` column at
    all -- every row with status='active' was eligible regardless of which
    telephony provider it actually belonged to. With telephony_provider set
    to twilio but five Plivo numbers marked 'active' and the one real Twilio
    number marked 'parked-twilio', this lookup handed ep_twilio_voice a
    caller ID Twilio doesn't own -- Twilio silently kills the leg, which is
    the exact "instant hangup, no ring" symptom this was chasing. Added a
    `provider` column (backfilled from the pre-existing `label` text) and
    filter on it here so a caller ID can never cross providers again. Rows
    written by other tools before this column existed have provider IS NULL
    -- for those, fall back to matching against `label` so old data still
    resolves instead of silently returning nothing pool-wide.
    """
    try:
        path = _command_center_db_path()
        if not os.path.exists(path):
            return ""
        con = sqlite3.connect(path, timeout=5)
        con.row_factory = sqlite3.Row
        try:
            tables = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='did_pool'")}
            if "did_pool" not in tables:
                return ""
            cols = {r[1] for r in con.execute("PRAGMA table_info(did_pool)")}
            if "provider" in cols:
                provider_filter = (
                    " AND (provider=? OR (provider IS NULL AND label LIKE ?))")
                provider_args = (provider, "%" + provider + "%")
            else:
                # Table predates the provider column entirely (shouldn't happen
                # post-migration, but never crash live dialing over a schema gap).
                provider_filter = ""
                provider_args = ()
            # ── Smart rotation layer (2026-07-31) ──────────────────────
            # dials_date: the local date dials_today belongs to. Lazy daily
            # reset — the counter zeroes itself the first time anyone looks
            # up a DID on a new day; no cron/midnight job required.
            if "dials_date" not in cols:
                try:
                    con.execute("ALTER TABLE did_pool ADD COLUMN dials_date TEXT")
                    con.commit()
                    cols.add("dials_date")
                except Exception:
                    pass
            today = datetime.now().strftime("%Y-%m-%d")
            if "dials_date" in cols:
                try:
                    con.execute(
                        "UPDATE did_pool SET dials_today=0, dials_date=? "
                        "WHERE (dials_date IS NULL OR dials_date<>?) "
                        "AND dials_today>0", (today, today))
                    con.execute(
                        "UPDATE did_pool SET dials_date=? "
                        "WHERE dials_date IS NULL", (today,))
                    con.commit()
                except Exception:
                    pass
            def _cap(created_at):
                return _did_daily_cap(created_at, today)
            def _eligible(where_extra, extra_args):
                q = ("SELECT id, phone_number, dials_today, created_at "
                     "FROM did_pool WHERE status='active'" + provider_filter
                     + where_extra)
                rows = con.execute(q, provider_args + extra_args).fetchall()
                return [r for r in rows
                        if (r["dials_today"] or 0) < _cap(r["created_at"])]
            pick = None
            if rep_name:
                cand = _eligible(" AND assigned_rep=?", (rep_name,))
                if cand:
                    pick = cand[0]
                # Assigned DID over its daily cap → fall through to the
                # unassigned round-robin instead of burning past the limit.
            if not pick:
                # Same rule as lead_machine's get_outbound_caller_id: a
                # rep-assigned DID is reserved and must not be picked up by
                # someone else's round-robin fallback.
                cand = _eligible(" AND (assigned_rep='' OR assigned_rep IS NULL)", ())
                cand.sort(key=lambda r: ((r["dials_today"] or 0), r["id"]))
                if cand:
                    pick = cand[0]
            if not pick:
                # Every active DID hit its daily cap → caller falls back to
                # the static config number. Loud log so the rep knows WHY the
                # rotation stopped instead of silently sticking to one DID.
                print("[DID POOL] all active numbers at daily cap "
                      "(warmup ramp / 40-per-day) — using config fallback")
                return ""
            return pick["phone_number"]
        finally:
            con.close()
    except Exception:
        return ""  # fail closed to the config fallback -- never break dialing over this

def ep_twilio_voice(params, provider="twilio"):
    """TwiML/TeXML webhook — the telephony provider calls this when the
    browser SDK initiates a call. TeXML is TwiML-compatible, so one function
    serves both engines; `provider` only changes the caller-ID config
    fallback key (telnyx_phone_number vs twilio_phone_number)."""
    c = _local_cfg()
    # Priority: (1) a "From" param the caller explicitly pre-selected (the
    # lead_machine cockpit passes its already-rotated+recorded caller ID
    # this way once wired -- see app.py's api_twilio_token comment) so the
    # two processes never independently pick different rows for the same
    # call; (2) this process's own did_pool lookup by rep, for any caller
    # that didn't pre-select one (e.g. cell_coach's standalone UI); (3) the
    # single static config number, unchanged from before this feature.
    rep_name = (params.get("Rep", [""])[0] or "").strip()
    preselected = (params.get("From", [""])[0] or "").strip()
    # 2026-07-22 bugfix: "From" is sometimes populated by the Twilio Voice
    # SDK itself with the browser's own Client identity (e.g.
    # "client:cellcoach") rather than a phone number -- confirmed live via
    # ngrok's captured request log, where From resolved to "client:cellcoach"
    # and got passed straight through into <Dial callerId="client:cellcoach">.
    # Twilio requires callerId to be a real E.164 number it owns/has
    # verified; a client: identity there is invalid, so Twilio accepts the
    # TwiML (200 OK) but kills the outbound leg immediately -- silent
    # instant-hangup, no ring, no error surfaced to the WebRTC leg. That
    # matches the exact symptom reported. Fix: only trust a pre-selected
    # "From" if it actually looks like a phone number; otherwise fall
    # through to the did_pool lookup as before.
    # Root cause of the collision: "From" is ALSO one of Twilio's own
    # standard webhook params, and for a browser-Client-originated call
    # Twilio sets it to the client identity (client:cellcoach) whenever the
    # SDK connect() didn't pass a custom param of the same name. So any
    # dial from cell_coach's own UI (which sends only {To}) had
    # `preselected` silently pick up Twilio's standard From. Two-layer fix:
    # (a) callers should use the collision-proof custom param "FromDid"
    # (lead_machine's cockpit updated to send it); (b) legacy "From" is
    # still honored but only when it actually looks like a phone number.
    from_did = (params.get("FromDid", [""])[0] or "").strip()
    def _e164_or_none(v):
        if not v or v.startswith("client:"):
            return None
        digits = "".join(ch for ch in v if ch.isdigit())
        if len(digits) == 10:
            digits = "1" + digits
        if not (10 <= len(digits) <= 15):
            return None
        return "+" + digits
    to = params.get("To", [""])[0]
    to_e164 = _e164_or_none(to)
    pool_did = _e164_or_none(_did_pool_lookup(rep_name, provider=provider))
    # Sticky caller ID: if this lead already has a pool-DID pairing (they
    # called it back, or we last reached them from it), prefer that number
    # over the round-robin pick — prospects answer numbers they recognize.
    # _sticky_did_for enforces active/provider/daily-cap, so warmup limits
    # always win over stickiness. Explicit pre-selection (FromDid/From) still
    # outranks everything.
    sticky_did = _e164_or_none(_sticky_did_for(to, provider=provider))
    caller = (_e164_or_none(from_did) or _e164_or_none(preselected)
              or sticky_did
              or pool_did
              or _e164_or_none(c.get(provider + "_phone_number"))
              or _e164_or_none(c.get("twilio_phone_number"))
              or _e164_or_none(c.get("twilio_from_number")))
    # Plivo XML uses <Speak> where TwiML/TeXML use <Say>; everything else
    # (<Response>, <Dial callerId>, <Number>) is identical across all three.
    say = "Speak" if provider == "plivo" else "Say"
    allowed = _dial_guard_numbers()
    if allowed and to_e164 and to_e164 not in allowed:
        # Test-mode dial guard: refuse anything off the allowlist. Audible in
        # the rep's ear, and the outbound leg is never created -- a mis-click
        # can never ring a real prospect while the guard is on.
        twiml = ('<?xml version="1.0" encoding="UTF-8"?><Response>'
                 '<' + say + '>Dial blocked. That number is not on the allowed test list.</' + say + '>'
                 '</Response>')
        return twiml
    if not to_e164:
        twiml = ('<?xml version="1.0" encoding="UTF-8"?><Response><' + say +
                 '>No valid number provided.</' + say + '></Response>')
    elif not caller:
        # Never emit <Dial> with an empty/invalid callerId -- the provider
        # would accept the XML then kill the leg. Fail loudly and audibly.
        twiml = ('<?xml version="1.0" encoding="UTF-8"?><Response><' + say +
                 '>No valid caller I D is configured. Check the D I D pool and config.</' + say + '></Response>')
    else:
        # Ring timeout: carrier default is a full 60s of ringback on no-answer —
        # pure dead time on a power-dial cadence. Cap it (config dial_ring_timeout,
        # default 20s). A decline/no-answer then costs seconds, not a minute.
        try:
            ring_to = int(c.get("dial_ring_timeout") or 20)
        except (TypeError, ValueError):
            ring_to = 20
        ring_to = max(5, min(ring_to, 60))
        twiml = ('<?xml version="1.0" encoding="UTF-8"?>'
                 '<Response><Dial callerId="' + caller + '" timeout="' + str(ring_to) + '"'
                 ' action="/api/twilio_dial_status">'
                 '<Number>' + to_e164 + '</Number>'
                 '</Dial></Response>')
        # Pool bookkeeping: when the caller ID came from this process's pool
        # (sticky pairing OR round-robin pick), count the dial so caps and
        # rotation stay truthful, and (re)pair the lead to the number actually
        # used so the next call to them sticks to it too.
        # Never raises -- a bookkeeping failure must never break a live call.
        used_pool_did = None
        if sticky_did and caller == sticky_did:
            used_pool_did = sticky_did
        elif pool_did and caller == pool_did:
            used_pool_did = pool_did
        if used_pool_did:
            try:
                path = _command_center_db_path()
                if os.path.exists(path):
                    con = sqlite3.connect(path, timeout=5)
                    try:
                        con.execute("UPDATE did_pool SET dials_today = dials_today + 1,"
                                    " dials_date = ? WHERE phone_number = ?",
                                    (datetime.now().strftime("%Y-%m-%d"), used_pool_did))
                        con.commit()
                    finally:
                        con.close()
            except Exception:
                pass
            _sticky_did_remember(to_e164, used_pool_did)
    return twiml

def ep_twilio_dial_status(params):
    """<Dial action=...> callback — the provider POSTs DialCallStatus here when
    the outbound PSTN leg ends: completed | no-answer | busy | failed | canceled.
    Recorded so the browser can auto-disposition unanswered dials (no wrap time)."""
    sid = (params.get("CallSid", [""])[0] or "").strip()
    status = ((params.get("DialCallStatus", [""])[0] or
               params.get("DialStatus", [""])[0] or "").strip().lower())
    if sid and status:
        try:
            con = db()
            con.execute("INSERT OR REPLACE INTO dial_outcomes(call_sid,status,ts) VALUES(?,?,?)",
                        (sid, status, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            con.commit()
            con.close()
        except Exception:
            pass
    return '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'

def ep_dial_outcome(qs):
    """GET /api/dial_outcome?sid=CA... — the browser polls this right after the
    SDK disconnects to learn WHY the dial ended (answered vs no-answer/busy)."""
    sid = (qs.get("sid", [""])[0] or "").strip()
    if not sid:
        return {"status": None}
    try:
        con = db()
        row = con.execute("SELECT status FROM dial_outcomes WHERE call_sid=?", (sid,)).fetchone()
        con.close()
        return {"status": row["status"] if row else None}
    except Exception:
        return {"status": None}

def ep_telnyx_voice(params):
    """TeXML webhook — Telnyx calls this when the browser SDK initiates a
    call. TeXML is TwiML-compatible (<Response>/<Dial callerId>/<Number>/
    <Say> all supported), so the SAME dial-guard + DID-rotation + caller-ID
    logic serves both engines. Identical behavior, second door."""
    return ep_twilio_voice(params, provider="telnyx")

# ── Plivo (third parallel engine — Twilio/Telnyx untouched) ─────────────────
# Browser SDK authenticates with a JWT minted server-side:
#   POST /v1/Account/{auth_id}/JWT/Token/  (HTTP basic: auth_id:auth_token)
#   body: {sub, nbf, exp}  → returns a JWT for client.loginWithAccessToken()
_plivo_token_cache = {"token": "", "minted_at": 0.0}

def ep_plivo_token(force_refresh=False):
    c = _local_cfg()
    auth_id = (c.get("plivo_auth_id") or "").strip()
    auth_token = (c.get("plivo_auth_token") or "").strip()
    endpoint_user = (c.get("plivo_endpoint_user") or "cellcoach").strip()
    if not (auth_id and auth_token):
        return {"error": "Plivo not configured — set plivo_auth_id and "
                         "plivo_auth_token in cc_config.json"}
    if not force_refresh and _plivo_token_cache["token"] \
            and time.time() - _plivo_token_cache["minted_at"] < 3300:
        return {"token": _plivo_token_cache["token"]}
    try:
        now = int(time.time())
        basic = base64.b64encode((auth_id + ":" + auth_token).encode()).decode()
        req = _urlreq.Request(
            "https://api.plivo.com/v1/Account/" + auth_id + "/JWT/Token/",
            data=json.dumps({"iss": auth_id, "sub": endpoint_user, "nbf": now, "exp": now + 3600,
                             "per": {"voice": {"incoming_allow": True, "outgoing_allow": True}}}).encode(),
            method="POST",
            headers={"Authorization": "Basic " + basic,
                     "Content-Type": "application/json"})
        with _urlreq.urlopen(req, timeout=15) as r:
            body = r.read().decode()
        token = ""
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                token = parsed.get("token") or parsed.get("jwt") or ""
            elif isinstance(parsed, str):
                token = parsed
        except Exception:
            token = body.strip()
        if not token:
            raise RuntimeError("empty token in Plivo response: " + body[:120])
        _plivo_token_cache["token"] = token
        _plivo_token_cache["minted_at"] = time.time()
        return {"token": token}
    except _urlreq.HTTPError as e:
        try:
            detail = e.read().decode()[:200]
        except Exception:
            detail = str(e)
        return {"error": "plivo token failed: HTTP %d: %s" % (e.code, detail)}
    except Exception as e:
        return {"error": "plivo token failed: " + str(e)[:200]}

def ep_plivo_voice(params):
    """Plivo XML webhook — same dial-guard + DID-rotation + caller-ID logic
    as the Twilio/Telnyx doors; only the speak verb differs (<Speak> vs
    <Say>), handled inside the shared implementation."""
    return ep_twilio_voice(params, provider="plivo")

# ══════════════════════════════════════════════════════════════════════════════
# INBOUND CALLBACK ROUTER (2026-07-31)
# A prospect who missed our outbound call redials one of the pool DIDs.
# Twilio hits /api/twilio_inbound; we look the caller up across every lead
# store and route:
#   1) the rep's browser WebRTC client (identity "cellcoach"), 20s ring
#   2) the rep's cell (callback_forward_number, default +17036460021) with a
#      spoken whisper: "Callback from Sean — 123 Main St — last: follow up"
#   3) voicemail (<Record>), stored on the lead + lead hot-bumped to the top
#      of tomorrow's queue via follow_up_date=today
# The step machine: each <Dial> has action=/api/twilio_inbound_route; the
# action callback sees DialCallStatus and returns the NEXT step's TwiML, so a
# completed call can never fall through into the voicemail prompt.
# ══════════════════════════════════════════════════════════════════════════════

def _public_base(handler=None):
    """Absolute https base URL for Twilio-facing callback URLs (whisper,
    recording status). Precedence: config override → live ngrok detection
    (cached 60s) → forwarded request headers. Never raises."""
    c = _local_cfg()
    cfg = (c.get("public_base_url") or "").strip().rstrip("/")
    if cfg:
        return cfg
    now = time.time()
    cached = _public_base._cache
    if cached["url"] and now - cached["at"] < 60:
        return cached["url"]
    url = None
    try:
        url = _check_ngrok_tunnel(_public_base._port)
    except Exception:
        url = None
    if not url and handler is not None:
        try:
            host = (handler.headers.get("X-Forwarded-Host")
                    or handler.headers.get("Host") or "").strip()
            proto = (handler.headers.get("X-Forwarded-Proto") or "").strip()
            if not proto:
                proto = "https" if ("ngrok" in host or host.endswith(".dev")) else "http"
            if host:
                url = proto + "://" + host
        except Exception:
            url = None
    if url:
        url = url.rstrip("/")
        _public_base._cache = {"url": url, "at": now}
        return url
    return ""
_public_base._cache = {"url": "", "at": 0.0}
_public_base._port = 5099

def _xml_escape(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))

def _lead_context_for_phone(raw_phone):
    """Best-effort identity for an inbound caller, searched in priority order:
    local call log (richest: last dispo + summary) → imported CSV leads →
    command_center.db leads table. Never raises; returns a dict that may be
    just {found: False}."""
    digits = _normalize_phone(raw_phone or "")
    if len(digits) < 7:
        return {"found": False}
    ctx = {"found": False, "phone": "+" + digits[-11:] if len(digits) >= 10 else raw_phone}
    try:
        con = db()
        rows = con.execute(
            "SELECT phone, owner, address, case_id, play, disposition, summary "
            "FROM calls WHERE phone!='' ORDER BY id DESC").fetchall()
        for r in rows:
            if _normalize_phone(r["phone"]) == digits:
                ctx.update({"found": True, "owner": r["owner"] or "",
                            "address": r["address"] or "",
                            "case_id": r["case_id"] or "",
                            "play": r["play"] or "",
                            "last_dispo": r["disposition"] or "",
                            "summary": r["summary"] or "", "source": "call_log"})
                break
        if not ctx["found"]:
            rows = con.execute(
                "SELECT phone, owner, address, case_id, play, status, notes "
                "FROM imported_leads WHERE phone!=''").fetchall()
            for r in rows:
                if _normalize_phone(r["phone"]) == digits:
                    ctx.update({"found": True, "owner": r["owner"] or "",
                                "address": r["address"] or "",
                                "case_id": r["case_id"] or "",
                                "play": r["play"] or "",
                                "last_dispo": r["status"] or "",
                                "summary": (r["notes"] or "")[-200:],
                                "source": "imported_leads"})
                    break
        con.close()
    except Exception:
        pass
    if not ctx["found"]:
        try:
            path = _command_center_db_path()
            if os.path.exists(path):
                con = sqlite3.connect(path, timeout=5)
                con.row_factory = sqlite3.Row
                rows = con.execute(
                    "SELECT phone, owner, address, case_id, stage, play FROM leads "
                    "WHERE phone!='' AND phone IS NOT NULL").fetchall()
                con.close()
                for r in rows:
                    p = r["phone"] or ""
                    for cand in re.split(r"[,;/]", p):
                        if _normalize_phone(cand) == digits:
                            ctx.update({"found": True, "owner": r["owner"] or "",
                                        "address": r["address"] or "",
                                        "case_id": r["case_id"] or "",
                                        "play": r["play"] or "",
                                        "last_dispo": r["stage"] or "",
                                        "summary": "", "source": "command_center"})
                            break
                    if ctx["found"]:
                        break
        except Exception:
            pass
    return ctx

def _whisper_text(ctx):
    """Short spoken context played to the REP (cell fallback) before bridge."""
    if not ctx.get("found"):
        return "Inbound callback. No lead history for this number."
    parts = []
    if ctx.get("owner"):
        parts.append("Callback from " + ctx["owner"])
    else:
        parts.append("Callback from a known lead")
    if ctx.get("address"):
        parts.append(ctx["address"])
    if ctx.get("last_dispo"):
        parts.append("last status " + str(ctx["last_dispo"]).replace("_", " "))
    return ". ".join(parts) + "."

def _inbound_tag_lead(phone, tag_text, bump=False):
    """Lite-CRM write-back for inbound events (same append-only notes rule as
    ep_call_end). bump=True also forces a same-day follow-up so the lead
    resurfaces at the top of the queue as a hot inbound. Never raises."""
    try:
        norm = _normalize_phone(phone or "")
        if not norm:
            return
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        today = now[:10]
        con = db()
        # The ranked queue's hot-inbound bump rides on the local call log:
        # a row with follow_up_date=today wins the callback_due bucket.
        if bump:
            # One bump row per phone per day, max — a re-fired webhook (e.g.
            # the <Record> action re-entry fixed 2026-07-31) must never stack
            # duplicate inbound_missed rows on the lead.
            dup = False
            for r in con.execute(
                    "SELECT phone FROM calls WHERE disposition='inbound_missed' "
                    "AND follow_up_date=?", (today,)).fetchall():
                if _normalize_phone(r["phone"] or "") == norm:
                    dup = True
                    break
            if not dup:
                ctx = _lead_context_for_phone(phone)
                con.execute(
                    "INSERT INTO calls(phone,play,owner,address,case_id,started_at,"
                    "ended_at,duration,disposition,follow_up_date,rep_notes) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (phone, ctx.get("play", ""), ctx.get("owner", ""),
                     ctx.get("address", ""), ctx.get("case_id", ""), now, now, 0,
                     "inbound_missed", today, tag_text))
        rows = con.execute(
            "SELECT id, phone, status, notes FROM imported_leads").fetchall()
        for r in rows:
            if _normalize_phone(r["phone"] or "") != norm:
                continue
            tag = "[" + now + "] " + tag_text
            new_notes = ((r["notes"] or "") + "\n" + tag).strip()
            cur = (r["status"] or "")
            if cur in ("dnc", "paid"):
                con.execute("UPDATE imported_leads SET notes=? WHERE id=?",
                            (new_notes, r["id"]))
            else:
                con.execute("UPDATE imported_leads SET status='followup', "
                            "notes=? WHERE id=?", (new_notes, r["id"]))
        con.commit()
        con.close()
    except Exception:
        pass

def _forward_cell():
    c = _local_cfg()
    raw = (c.get("callback_forward_number") or "+17036460021").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) == 10:
        digits = "1" + digits
    return "+" + digits if 10 <= len(digits) <= 15 else "+17036460021"

def ep_twilio_inbound(params, handler=None):
    """Step 0: prospect redialed a pool DID. Ring the rep's browser client
    first; the <Dial> action callback advances the step machine."""
    frm = (params.get("From", [""])[0] or "").strip()
    # Sticky pairing: the prospect just told us which DID they answer — call
    # them back from exactly this number next time (cap permitting).
    _sticky_did_remember(frm, (params.get("To", [""])[0] or "").strip())
    base = _public_base(handler)
    action = (base + "/api/twilio_inbound_route?step=client&from="
              + _urlquote(frm)) if base else ""
    dial_attrs = ' timeout="20"'
    if action:
        dial_attrs += ' action="' + _xml_escape(action) + '" method="POST"'
    # No fallback verbs after <Dial>: if base URL is unknown the action URL
    # can't be built, so fall through to a static cell forward instead.
    if action:
        body = ('<Dial' + dial_attrs + '><Client>cellcoach</Client></Dial>'
                '<Hangup/>')
    else:
        body = ('<Dial timeout="25"><Number>' + _forward_cell() +
                '</Number></Dial>')
    return ('<?xml version="1.0" encoding="UTF-8"?><Response>' + body +
            '</Response>')

def ep_twilio_inbound_route(params, handler=None):
    """Step machine driven by <Dial action=...>. Twilio posts DialCallStatus:
    completed → call was answered, hang up cleanly. Anything else → advance:
    client step falls to the rep's cell (with whisper), cell step falls to
    voicemail."""
    status = (params.get("DialCallStatus", [""])[0] or "").strip()
    frm = (params.get("from", [""])[0] or "").strip()
    step = (params.get("step", ["client"])[0] or "client").strip()
    base = _public_base(handler)
    # <Record> action callback lands here (step=done) — Twilio ALWAYS posts
    # to the Record's action URL when recording ends instead of continuing to
    # the next verb. Without an explicit action, the default is the CURRENT
    # URL, which re-entered this handler and re-issued the greeting in an
    # infinite 5-second loop (seen live 2026-07-31). Two-layer guard: the
    # step=done route AND a RecordingDuration param check catch it either way.
    if step == "done" or (params.get("RecordingDuration", [""])[0]
                          and not status):
        if frm:
            ep_twilio_voicemail(params)  # stores recording on the lead row
        return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
                '<Say>Thanks — we have your message. Talk soon.</Say>'
                '<Hangup/></Response>')
    if status == "completed":
        if step == "cell" and frm:
            # Answered on the cell — log it so history/queue stay truthful.
            _inbound_tag_lead(frm, "inbound callback answered on cell")
        return ('<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/>'
                '</Response>')
    if step == "client":
        # Browser didn't pick up (offline or ignored) → forward to cell with
        # a spoken whisper identifying the caller before the bridge.
        whisper = (base + "/api/twilio_inbound_whisper?from="
                   + _urlquote(frm)) if base else ""
        action = (base + "/api/twilio_inbound_route?step=cell&from="
                  + _urlquote(frm)) if base else ""
        num_attrs = ''
        if whisper:
            num_attrs = ' url="' + _xml_escape(whisper) + '" method="POST"'
        dial_attrs = ' timeout="25"'
        if action:
            dial_attrs += ' action="' + _xml_escape(action) + '" method="POST"'
        return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
                '<Dial' + dial_attrs + '><Number' + num_attrs + '>'
                + _forward_cell() + '</Number></Dial><Hangup/></Response>')
    # Cell didn't pick up either → voicemail. Tag the lead as a hot inbound:
    # missed callback → top of queue via follow_up_date=today.
    if frm:
        _inbound_tag_lead(frm, "inbound callback missed — sent to voicemail",
                          bump=True)
    # The Record's action goes to step=done: store + thank + hang up there.
    # The trailing <Say>/<Hangup> after <Record> are pure fallback — Twilio
    # executes the action callback INSTEAD of the verbs after <Record>.
    rec_action = (base + "/api/twilio_inbound_route?step=done&from="
                  + _urlquote(frm)) if base else ""
    rec_attrs = ' maxLength="120" playBeep="true"'
    if rec_action:
        rec_attrs += (' action="' + _xml_escape(rec_action) +
                      '" method="POST"')
    return ('<?xml version="1.0" encoding="UTF-8"?><Response>'
            '<Say>You have reached the property team. We are on another line '
            '— please leave your name, number, and the property address, and '
            'we will call you right back.</Say>'
            '<Record' + rec_attrs + '/>'
            '<Say>Thanks — we have your message. Talk soon.</Say>'
            '<Hangup/></Response>')

def ep_twilio_inbound_whisper(params):
    """TwiML fetched by the <Number url=...> whisper: played ONLY to the rep's
    cell before the prospect is bridged in."""
    frm = (params.get("from", [""])[0] or "").strip()
    ctx = _lead_context_for_phone(frm)
    return ('<?xml version="1.0" encoding="UTF-8"?><Response><Say>'
            + _xml_escape(_whisper_text(ctx)) + '</Say></Response>')

def ep_twilio_voicemail(params):
    """recordingStatusCallback from the voicemail <Record>. Stores the
    recording on the lead's call log row and notes so it survives."""
    frm = (params.get("from", [""])[0] or "").strip()
    rec_url = (params.get("RecordingUrl", [""])[0] or "").strip()
    rec_sid = (params.get("RecordingSid", [""])[0] or "").strip()
    rec_dur = (params.get("RecordingDuration", [""])[0] or "").strip()
    if frm:
        note = "voicemail received (%ss): %s" % (rec_dur or "?", rec_url or "no url")
        try:
            norm = _normalize_phone(frm)
            con = db()
            # Attach the recording to the inbound_missed row written when the
            # call fell through to voicemail (latest matching row).
            rows = con.execute(
                "SELECT id, phone, rep_notes FROM calls "
                "WHERE disposition='inbound_missed' ORDER BY id DESC").fetchall()
            for r in rows:
                if _normalize_phone(r["phone"] or "") == norm:
                    con.execute(
                        "UPDATE calls SET recording=?, rep_notes=? WHERE id=?",
                        ("twilio:" + rec_sid,
                         ((r["rep_notes"] or "") + " | " + note).strip(" |"),
                         r["id"]))
                    break
            con.commit()
            con.close()
        except Exception:
            pass
        _inbound_tag_lead(frm, note)
    return {"ok": True}

# ── Rep profile endpoints ─────────────────────────────────────────────────────

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

def ep_update_rules(d):
    rules = d.get("rules") or []
    if not isinstance(rules, list):
        return {"error": "rules must be a list"}
    rules = [r.strip() for r in rules if isinstance(r, str) and r.strip()]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    con = db()
    con.execute("UPDATE rep_profile SET manual_rules=?, updated_at=? WHERE id=1",
                (json.dumps(rules), now))
    if con.total_changes == 0:
        con.execute("INSERT INTO rep_profile(id, manual_rules, updated_at) VALUES(1,?,?)",
                    (json.dumps(rules), now))
    con.commit()
    con.close()
    return {"ok": True}

def ep_edit_weaknesses(d):
    weak = d.get("weak_categories")
    if weak is None:
        return {"error": "weak_categories required"}
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    con = db()
    con.execute("UPDATE rep_profile SET weak_categories=?, updated_at=? WHERE id=1",
                (json.dumps(weak), now))
    con.commit()
    con.close()
    return {"ok": True}

def ep_get_scores(qs):
    limit = min(int((qs.get("limit", ["20"])[0] or "20")), 100)
    con = db()
    rows = con.execute(
        "SELECT s.*, c.started_at, c.play as call_play, c.owner, c.disposition "
        "FROM session_scores s LEFT JOIN calls c ON s.call_id=c.id "
        "ORDER BY s.id DESC LIMIT ?", (limit,)).fetchall()
    con.close()
    return {"scores": [dict(r) for r in rows]}

def ep_backfill_scores():
    con = db()
    rows = con.execute(
        "SELECT id FROM calls WHERE scored=0 AND transcript IS NOT NULL AND transcript!=''").fetchall()
    con.close()
    count = 0
    for row in rows:
        threading.Thread(target=_score_session, args=(row["id"],), daemon=True).start()
        count += 1
    return {"ok": True, "queued": count}

# ── Load HTML from file ───────────────────────────────────────────────────────
def _load_html():
    p = os.path.join(BASE, "cellcoach_ui.html")
    with open(p, encoding="utf-8") as f:
        return f.read()

HTML = None  # loaded once at startup

# ── HTTP handler ──────────────────────────────────────────────────────────────
class H(BaseHTTPRequestHandler):
    def _s(self, obj, code=200, ctype="application/json"):
        b = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _stream_analyze(self, d):
        """NDJSON-streamed /api/analyze: emits partial say_next lines as the fused
        coach generates them, then one final full analysis object. No Content-Length —
        the response terminates at connection close (the handler speaks HTTP/1.0),
        which fetch()'s body reader handles natively. Local-only traffic (the UI talks
        to 127.0.0.1 directly; ngrok fronts Twilio webhooks, not this)."""
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.close_connection = True
        state = {"last": None}

        def _write(obj):
            try:
                self.wfile.write((json.dumps(obj) + "\n").encode("utf-8"))
                self.wfile.flush()
            except Exception:
                pass

        def on_partial(text, complete):
            if text and text != state["last"]:
                state["last"] = text
                _write({"type": "partial", "say_next": text, "done": bool(complete)})

        try:
            out = ep_analyze(d, on_partial=on_partial)
        except Exception as e:
            out = {"error": "coach stream failed: " + str(e)[:200]}
        out["type"] = "final"
        _write(out)

    def log_message(self, *a):
        pass

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/":
            try:
                return self._s(_load_html().encode(), ctype="text/html")
            except Exception:
                return self._s(HTML.encode(), ctype="text/html")
        if p == "/api/status":
            return self._s(ep_status())
        if p == "/api/aai_token":
            return self._s(ep_aai())
        if p == "/api/twilio_token":
            return self._s(ep_twilio_token())
        if p == "/api/telnyx_token":
            return self._s(ep_telnyx_token())
        if p == "/api/plivo_token":
            return self._s(ep_plivo_token())
        if p.startswith("/api/prep_by_phone/"):
            raw = p.split("/api/prep_by_phone/", 1)[1] if "/api/prep_by_phone/" in p else ""
            return self._s(ep_prep_by_phone(raw))
        if p == "/api/history":
            return self._s(ep_history())
        if p == "/api/train/scenarios":
            return self._s(ep_train_scenarios())
        if p == "/api/train/voices":
            return self._s(ep_elevenlabs_voices())
        if p == "/api/train/preview_character":
            qs = parse_qs(urlparse(self.path).query)
            sid = (qs.get("scenario_id") or [""])[0]
            diff = (qs.get("difficulty") or ["easy"])[0]
            gpref = (qs.get("gender_pref") or ["random"])[0]
            return self._s(ep_train_preview_character(sid, diff, gpref))
        if p.startswith("/api/train/credentials"):
            qs = parse_qs(urlparse(self.path).query)
            sid = (qs.get("session_id") or [""])[0]
            return self._s(ep_train_credentials(sid))
        if p == "/api/personas":
            return self._s(ep_personas_list())
        if p == "/api/playbooks":
            return self._s(ep_playbooks_list())
        if p == "/api/valuation":
            return self._s(ep_valuation(parse_qs(urlparse(self.path).query)))
        if p == "/api/dial_outcome":
            return self._s(ep_dial_outcome(parse_qs(urlparse(self.path).query)))
        if p == "/api/profile":
            return self._s(ep_get_profile())
        if p == "/api/profile/scores":
            return self._s(ep_get_scores(parse_qs(urlparse(self.path).query)))
        if p == "/api/sources":
            return self._s(ep_sources())
        if p == "/api/queue":
            return self._s(ep_queue(parse_qs(urlparse(self.path).query)))
        if p.startswith("/recordings/"):
            fname = os.path.basename(p.split("/recordings/", 1)[1])
            fp = os.path.join(RECORDINGS_DIR, fname)
            if os.path.exists(fp) and fname.endswith(".webm"):
                with open(fp, "rb") as f:
                    return self._s(f.read(), ctype="audio/webm")
            return self._s({"error": "recording not found"}, 404)
        if p.startswith("/api/export/"):
            parts = [x for x in p.split("/") if x]
            # parts: ['api', 'export', '<id>', '<type>']
            if len(parts) == 4 and parts[3] in ("call", "coaching"):
                try:
                    cid = int(parts[2])
                except ValueError:
                    return self._s({"error": "invalid call id"}, 404)
                con = db()
                row = con.execute("SELECT * FROM calls WHERE id=?", (cid,)).fetchone()
                con.close()
                if not row:
                    return self._s({"error": "call not found"}, 404)
                log_events = []
                try:
                    coach_log = row["coach_log"] or ""
                    if coach_log:
                        log_events = json.loads(coach_log)
                except Exception:
                    log_events = []
                row_dict = dict(row)
                if parts[3] == "call":
                    content = _render_call_export(row_dict, log_events)
                else:
                    content = _render_coaching_export(row_dict, log_events)
                owner_slug = re.sub(r"[^a-z0-9]", "_",
                    (row_dict.get("owner") or row_dict.get("phone") or "call").lower())[:20]
                date_slug = (row_dict.get("started_at") or "")[:10].replace("-", "")
                fname = owner_slug + "_" + date_slug + "_" + parts[3] + ".md"
                b = content.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/markdown; charset=utf-8")
                self.send_header("Content-Disposition", 'attachment; filename="' + fname + '"')
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)
                return
            return self._s({"error": "not found"}, 404)
        return self._s({"error": "not found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        path = urlparse(self.path).path
        # Binary upload — call recording (not JSON)
        if path == "/api/save_recording":
            raw = self.rfile.read(n) if n else b""
            qs = parse_qs(urlparse(self.path).query)
            return self._s(ep_save_recording(raw, qs))
        # TwiML voice webhook — Twilio sends form-encoded, not JSON
        if path == "/api/twilio_voice":
            try:
                raw = self.rfile.read(n).decode()
                params = parse_qs(raw)
            except Exception:
                params = {}
            twiml = ep_twilio_voice(params)
            return self._s(twiml.encode(), ctype="text/xml")
        # TeXML voice webhook — Telnyx also sends form-encoded, TwiML-compatible
        if path == "/api/telnyx_voice":
            try:
                raw = self.rfile.read(n).decode()
                params = parse_qs(raw)
            except Exception:
                params = {}
            texml = ep_telnyx_voice(params)
            return self._s(texml.encode(), ctype="text/xml")
        # Plivo XML voice webhook — form-encoded too, same shape
        if path == "/api/plivo_voice":
            try:
                raw = self.rfile.read(n).decode()
                params = parse_qs(raw)
            except Exception:
                params = {}
            pxml = ep_plivo_voice(params)
            return self._s(pxml.encode(), ctype="text/xml")
        # ── Inbound callback router (Twilio posts form-encoded) ────────────
        if path == "/api/twilio_dial_status":
            try:
                raw = self.rfile.read(n).decode()
                params = parse_qs(raw)
            except Exception:
                params = {}
            return self._s(ep_twilio_dial_status(params).encode(), ctype="text/xml")
        # A prospect redialing any pool DID lands here; the step machine
        # (client → cell+whisper → voicemail) lives in ep_twilio_inbound*.
        # NOTE: our own action/whisper/callback URLs carry context (step,
        # from) in the QUERY STRING while Twilio's fields ride in the POST
        # body — merge both, body wins on collision.
        if path in ("/api/twilio_inbound", "/api/twilio_inbound_route",
                    "/api/twilio_inbound_whisper", "/api/twilio_voicemail"):
            params = parse_qs(urlparse(self.path).query)
            try:
                body = parse_qs(self.rfile.read(n).decode())
                params.update(body)
            except Exception:
                pass
            if path == "/api/twilio_inbound":
                twiml = ep_twilio_inbound(params, handler=self)
                return self._s(twiml.encode(), ctype="text/xml")
            if path == "/api/twilio_inbound_route":
                twiml = ep_twilio_inbound_route(params, handler=self)
                return self._s(twiml.encode(), ctype="text/xml")
            if path == "/api/twilio_inbound_whisper":
                twiml = ep_twilio_inbound_whisper(params)
                return self._s(twiml.encode(), ctype="text/xml")
            return self._s(ep_twilio_voicemail(params))
        try:
            d = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            d = {}
        if path == "/api/analyze":
            if d.get("stream"):
                return self._stream_analyze(d)
            return self._s(ep_analyze(d))
        if path == "/api/call_end":
            return self._s(ep_call_end(d))
        if path == "/api/train/start":
            return self._s(ep_train_start(d))
        if path == "/api/train/chat":
            return self._s(ep_train_chat(d))
        if path == "/api/train/coach":
            return self._s(ep_train_coach(d))
        if path == "/api/train/credentials":
            return self._s(ep_train_credentials_full(d))
        if path == "/api/train/voices/set":
            return self._s(ep_set_train_voices(d))
        if path == "/api/train/end":
            return self._s(ep_train_end(d))
        if path == "/api/personas":
            return self._s(ep_persona_save(d))
        if path == "/api/personas/delete":
            return self._s(ep_persona_delete(d.get("id", "")))
        if path == "/api/personas/reset":
            return self._s(ep_persona_reset(d.get("id", "")))
        if path == "/api/import_csv":
            return self._s(ep_import_csv(d))
        if path == "/api/import_delete":
            return self._s(ep_import_delete(d))
        if path == "/api/profile/rules":
            return self._s(ep_update_rules(d))
        if path == "/api/profile/weaknesses":
            return self._s(ep_edit_weaknesses(d))
        if path == "/api/profile/backfill":
            return self._s(ep_backfill_scores())
        return self._s({"error": "not found"}, 404)

# ── ngrok tunnel detection ────────────────────────────────────────────────────
# Twilio's Voice webhook (/api/twilio_voice) must be reachable from Twilio's own
# servers over the public internet, not just localhost. Without a tunnel (ngrok
# or equivalent) exposing this port, an outbound call rings the Device, Twilio
# tries to fetch TwiML from a URL it can't reach, and the call dies instantly
# with no ring and no error surfaced to the browser — the exact "instant
# hangup" symptom diagnosed and fixed (E.164 handling, TwiML generation) in a
# prior pass. That fix was necessary but not sufficient without a live tunnel,
# so this check runs at every startup and prints a loud, impossible-to-miss
# warning if one isn't detected, rather than letting the rep discover it
# call-by-call. Queries ngrok's own local inspection API (the same one that
# powers its http://127.0.0.1:4040 web UI) — no ngrok Python package required,
# stdlib-only via _urlreq, and fails silently to "not detected" if ngrok isn't
# running at all (connection refused) rather than raising.
def _check_ngrok_tunnel(port):
    try:
        req = _urlreq.Request("http://127.0.0.1:4040/api/tunnels", method="GET")
        with _urlreq.urlopen(req, timeout=2) as r:
            data = json.loads(r.read().decode())
    except Exception:
        return None  # ngrok's local API isn't reachable — not running (or not installed)
    for t in data.get("tunnels", []):
        try:
            if (t.get("proto") == "https"
                    and str(port) in (t.get("config", {}).get("addr") or "")):
                return t.get("public_url")
        except Exception:
            continue
    # Fallback: any https tunnel at all, in case config.addr didn't match the
    # exact port string (e.g. "localhost:5099" vs "5099") — better to report a
    # plausibly-wrong URL than to falsely claim no tunnel exists.
    for t in data.get("tunnels", []):
        if t.get("proto") == "https" and t.get("public_url"):
            return t.get("public_url")
    return None

def _print_ngrok_status(port):
    url = _check_ngrok_tunnel(port)
    if url:
        print("[TELEPHONY] Active Tunnel Detected: " + url +
              "  ->  TwiML Webhook: " + url + "/api/twilio_voice")
        print("[TELEPHONY] Confirm the Twilio Console TwiML App's Voice Request URL "
              "matches the webhook above (it changes on every ngrok restart unless "
              "you're using a reserved/static domain).")
    else:
        print("=" * 78)
        print("[TELEPHONY WARNING] NO NGROK TUNNEL DETECTED ON PORT " + str(port) + ".")
        print("  Outbound Twilio calls WILL hang up instantly with no ring until a")
        print("  public tunnel is running and the Twilio Console's TwiML App Voice")
        print("  Request URL points at it. Start one with:")
        print("      ngrok http " + str(port))
        print("  Then set the TwiML App's Voice URL to:")
        print("      https://<your-ngrok-url>/api/twilio_voice")
        print("=" * 78)

# ── Main ──────────────────────────────────────────────────────────────────────
def main(port=5099):
    global HTML
    _ensure_config()
    _ensure_db()
    HTML = _load_html()
    c = _local_cfg()
    status = "READY" if (c.get("openai_key") and c.get("assemblyai_key")) else "KEYS MISSING"
    print("CELL COACH — standalone |", status)
    url = "http://127.0.0.1:" + str(port)
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print("running at " + url + "  (Ctrl+C to stop)")
    _print_ngrok_status(port)
    try:
        ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
