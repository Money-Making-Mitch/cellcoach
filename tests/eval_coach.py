#!/usr/bin/env python3
"""
Minimal eval harness for Cell Coach ep_analyze.

Tests frozen prior_state + transcript fixtures and asserts on returned JSON.
Requires a live OpenAI key; gate behind CC_EVAL=1 env var to avoid accidental charges.

Usage:
    cd C:/Users/Admin/data_center/cell_coach
    set CC_EVAL=1
    python3 tests/eval_coach.py

Exit code: 0 if all pass, 1 if any fail.
"""
import json
import os
import sys

# Run from cell_coach/ directory so cellcoach imports cleanly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

GATE = os.environ.get("CC_EVAL", "").strip()
if not GATE:
    print("SKIP: set CC_EVAL=1 to run (requires a live OpenAI key and will cost tokens)")
    sys.exit(0)

try:
    import cellcoach
except ImportError as e:
    print(f"FAIL: could not import cellcoach: {e}")
    sys.exit(1)

# ── Fixtures ──────────────────────────────────────────────────────────────────
# Each fixture: {description, d (request dict), asserts (list of callables)}

def _check(label, result):
    a = result.get("analysis", {})
    if result.get("error"):
        return f"FAIL [{label}] — API error: {result['error']}"
    if not a:
        return f"FAIL [{label}] — no analysis in response"
    return None


FIXTURES = [
    # 1. Opening — staircase_step must be intro, all checklist false
    {
        "description": "Opening call: staircase_step=intro, checklist all false",
        "d": {
            "opening": True,
            "play": "STRUCTURE",
            "owner": "Robert",
            "address": "123 Barton Springs Rd",
            "case_id": "CC-2026-001",
        },
        "asserts": [
            lambda a: a.get("staircase_step") == "intro" or f"staircase_step={a.get('staircase_step')} not intro",
            lambda a: a.get("checklist", {}).get("intro") == False or "checklist.intro should be false on opener",
            lambda a: a.get("objection") is None or "objection should be null on opener",
        ],
    },

    # 2. Intro done, prospect engaged — advance to agenda or qualification
    {
        "description": "Post-intro prospect engages — should advance past intro",
        "d": {
            "transcript": (
                "REP: Mike, this is Sean with Risk & Compliance Bureau — we track the city code portal "
                "and I came across an active citation on your property at 4801 Oak Creek. You aware of that?\n"
                "PROSPECT: Yeah, I know about it. What's going on?"
            ),
            "latest": "Yeah, I know about it. What's going on?",
            "play": "LAND_USE",
            "owner": "Mike",
            "address": "4801 Oak Creek Dr",
            "case_id": "CC-2026-002",
            "prior_state": {
                "staircase_step": "intro",
                "checklist": {"intro": False, "qualified": False, "play_selected": False, "committed": False},
                "prospect_intel": None,
                "play": None,
            },
        },
        "asserts": [
            lambda a: a.get("staircase_step") in ("agenda", "qualification") or
                      f"expected agenda or qualification, got {a.get('staircase_step')}",
        ],
    },

    # 3. Qualification in progress — intro checklist item must not regress
    {
        "description": "Qualification in progress — intro must stay true",
        "d": {
            "transcript": (
                "REP: Mike, this is Sean — saw an open case on your property.\n"
                "PROSPECT: Yeah go ahead.\n"
                "REP: On a scale of 1 to 10, how urgent is this for you?\n"
                "PROSPECT: Maybe a 7. I don't want fines stacking up."
            ),
            "latest": "Maybe a 7. I don't want fines stacking up.",
            "play": "LAND_USE",
            "owner": "Mike",
            "address": "4801 Oak Creek Dr",
            "case_id": "CC-2026-002",
            "prior_state": {
                "staircase_step": "qualification",
                "checklist": {"intro": True, "qualified": False, "play_selected": False, "committed": False},
                "prospect_intel": {"urgency": "7 out of 10", "decision_maker": None,
                                   "desired_outcome": None, "stated_number": None,
                                   "properties_owned": None},
                "play": None,
            },
        },
        "asserts": [
            lambda a: a.get("checklist", {}).get("intro") == True or
                      "intro must not regress to false once set",
            lambda a: a.get("staircase_step") in ("qualification", "commitment") or
                      f"expected qualification or commitment, got {a.get('staircase_step')}",
        ],
    },

    # 4. All pillars known — should advance to commitment
    {
        "description": "All four pillars known — advance to commitment",
        "d": {
            "transcript": (
                "REP: How urgent is this for you?\n"
                "PROSPECT: Very urgent — maybe a 9. I can move on it financially, my wife and I decide together "
                "and she's on board. If nothing changes in 30 days it goes to the Building Standards Commission."
            ),
            "latest": "Very urgent — maybe a 9. I can move on it financially, my wife and I decide together "
                      "and she's on board. If nothing changes in 30 days it goes to the Building Standards Commission.",
            "play": "STRUCTURE",
            "owner": "Robert",
            "address": "2205 Barton Springs Rd",
            "case_id": "CC-2026-003",
            "prior_state": {
                "staircase_step": "qualification",
                "checklist": {"intro": True, "qualified": False, "play_selected": False, "committed": False},
                "prospect_intel": {"urgency": "9 out of 10", "decision_maker": "them and spouse",
                                   "desired_outcome": "fix_keep", "stated_number": None,
                                   "properties_owned": "1"},
                "play": None,
            },
        },
        "asserts": [
            lambda a: a.get("staircase_step") in ("commitment", "play_close") or
                      f"expected commitment or play_close with all pillars known, got {a.get('staircase_step')}",
        ],
    },

    # 5. Prospect says 'not interested' early — coach should redirect, NOT close
    {
        "description": "Early 'not interested' — coach should redirect, stay in intro/agenda",
        "d": {
            "transcript": (
                "REP: Jennifer, this is Sean with Risk & Compliance Bureau.\n"
                "PROSPECT: Not interested."
            ),
            "latest": "Not interested.",
            "play": "LAND_USE",
            "owner": "Jennifer",
            "address": "500 South Congress",
            "case_id": "CC-2026-004",
            "prior_state": {
                "staircase_step": "intro",
                "checklist": {"intro": False, "qualified": False, "play_selected": False, "committed": False},
                "prospect_intel": None,
                "play": None,
            },
        },
        "asserts": [
            lambda a: a.get("staircase_step") in ("intro", "agenda") or
                      f"should stay at intro/agenda on early pushback, got {a.get('staircase_step')}",
            lambda a: a.get("objection") is not None or "should detect the 'not interested' objection",
        ],
    },

    # 6. Crisis call (foreclosure) — staircase_step intro, crisis tone expected
    {
        "description": "Crisis opening (foreclosure) — staircase_step=intro, crisis tone",
        "d": {
            "opening": True,
            "play": "FORECLOSURE",
            "owner": "Robert",
            "address": "789 Manor Rd",
            "case_id": "FC-2026-001",
        },
        "asserts": [
            lambda a: a.get("staircase_step") == "intro" or f"staircase_step={a.get('staircase_step')} not intro",
            lambda a: a.get("checklist", {}).get("intro") == False or "checklist.intro false on opener",
        ],
    },

    # 7. Commitment step — hypothetical close, say_next should contain commitment language
    {
        "description": "Commitment step — say_next should include hypothetical close language",
        "d": {
            "transcript": (
                "REP: I understand — you want it fixed and you want to keep the property.\n"
                "PROSPECT: Yeah, that's what I want."
            ),
            "latest": "Yeah, that's what I want.",
            "play": "STRUCTURE",
            "owner": "Robert",
            "address": "2205 Barton Springs Rd",
            "case_id": "CC-2026-003",
            "prior_state": {
                "staircase_step": "commitment",
                "checklist": {"intro": True, "qualified": True, "play_selected": False, "committed": False},
                "prospect_intel": {"urgency": "9 out of 10", "decision_maker": "them and spouse",
                                   "desired_outcome": "fix_keep", "stated_number": None,
                                   "properties_owned": "1"},
                "play": None,
            },
        },
        "asserts": [
            lambda a: a.get("staircase_step") in ("commitment", "play_close") or
                      f"expected commitment or play_close, got {a.get('staircase_step')}",
            lambda a: len(a.get("say_next", "")) > 0 or "say_next must be filled",
        ],
    },

    # 8. play_close — checklist should not regress after commitment done
    {
        "description": "play_close: qualified+committed must not regress",
        "d": {
            "transcript": (
                "REP: So if we could get the contractor in this week and close the city case — would that be a yes?\n"
                "PROSPECT: Yeah that sounds good but I want to think about it."
            ),
            "latest": "Yeah that sounds good but I want to think about it.",
            "play": "STRUCTURE",
            "owner": "Robert",
            "address": "2205 Barton Springs Rd",
            "case_id": "CC-2026-003",
            "prior_state": {
                "staircase_step": "play_close",
                "checklist": {"intro": True, "qualified": True, "play_selected": True, "committed": False},
                "prospect_intel": {"urgency": "9 out of 10", "decision_maker": "them and spouse",
                                   "desired_outcome": "fix_keep", "stated_number": None,
                                   "properties_owned": "1"},
                "play": "contractor",
            },
        },
        "asserts": [
            lambda a: a.get("checklist", {}).get("intro") == True or "intro must not regress",
            lambda a: a.get("checklist", {}).get("qualified") == True or "qualified must not regress",
            lambda a: a.get("staircase_step") == "play_close" or
                      f"should stay at play_close on 'think about it', got {a.get('staircase_step')}",
            lambda a: a.get("objection") is not None or "should detect stalling objection",
        ],
    },
]


def run_fixture(fix):
    desc = fix["description"]
    d = fix["d"]
    asserts = fix["asserts"]

    try:
        result = cellcoach.ep_analyze(d)
    except Exception as e:
        return f"FAIL [{desc}] — ep_analyze raised: {e}"

    err = _check(desc, result)
    if err:
        return err

    a = result["analysis"]
    for fn in asserts:
        verdict = fn(a)
        if verdict is not True and verdict is not None and verdict is not False:
            # fn returned a string error message
            if isinstance(verdict, str):
                return f"FAIL [{desc}] — {verdict}"
        elif verdict is False:
            return f"FAIL [{desc}] — assertion returned False"

    return f"PASS [{desc}]"


def main():
    print(f"Running {len(FIXTURES)} fixtures against ep_analyze ...\n")
    results = []
    fail_count = 0
    for fix in FIXTURES:
        r = run_fixture(fix)
        results.append(r)
        print(r)
        if r.startswith("FAIL"):
            fail_count += 1

    print(f"\n{'='*60}")
    print(f"Results: {len(FIXTURES) - fail_count}/{len(FIXTURES)} passed")
    if fail_count:
        print(f"FAILED: {fail_count} fixture(s)")
        sys.exit(1)
    else:
        print("All fixtures passed.")
        sys.exit(0)


if __name__ == "__main__":
    main()
