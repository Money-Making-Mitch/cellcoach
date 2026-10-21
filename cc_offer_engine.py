"""cc_offer_engine.py — live wholesale underwriting engine.

Exact Python port of 'Wholesale Offer Calculator.xlsx' (Cash Offer / MLS Fixer /
MLS Turnkey sheets) plus the live repair-interview loop: the analyzer extracts
condition answers from the call transcript, this engine re-prices the deal each
turn, and the coach asks the next unanswered rehab question — so the offer range
on the rep's screen TIGHTENS as the call progresses instead of being a static
pre-call guess.

Canonical math (from the spreadsheet — do not "simplify"):

  Cash Offer   = ((0.95 * ARV) - InvestorReturn - Repairs - DesiredProfit) / 1.01
                 where InvestorReturn = 0.10 * ARV
  MLS Fixer    = (0.94 * ARV) - DesiredProfit - Repairs - (0.05 * ARV)
  MLS Turnkey  = (0.87 * ARV) - DesiredProfit

Workbook reference values (walkthrough video):
  ARV $500k, repairs $93.2k, profit $30k -> cash offer ~= $298,811 ("get it under
  contract for $298k"). MLS list $500k, profit $30k -> turnkey offer $405,000.
"""

# ── Repair line items ─────────────────────────────────────────────────────────
# Ordered by cost impact so next_question() always chases the biggest unknown.
# cost=None means the item is count-driven (bathrooms) or derived (year_built).
# Each item's `question` is the exact phone phrasing from the calculator
# walkthrough — the coach weaves these into discovery one at a time.

REPAIR_ITEMS = [
    {"id": "kitchen",        "cost": 25000,
     "label": "Kitchen remodel",
     "question": "Has the kitchen been remodeled in the last three years?"},
    {"id": "foundation",     "cost": 20000,
     "label": "Foundation",
     "question": "Any foundation issues — cracks, doors sticking, uneven floors?"},
    {"id": "year_built",     "cost": None,  # <1925 -> +$20k electrical
     "label": "Year built / electrical",
     "question": "Do you know roughly what year the house was built?"},
    {"id": "roof",           "cost": 15000,
     "label": "Roof",
     "question": "How's the roof — do you know about how old it is?"},
    {"id": "bathrooms",      "cost": None,  # count-driven: $12k per bath needing remodel
     "label": "Bathrooms",
     "question": "How many bathrooms are there, and have any of them been updated?"},
    {"id": "flooring",       "cost": 8000,
     "label": "Flooring",
     "question": "What shape is the flooring in throughout the house?"},
    {"id": "hvac",           "cost": 7500,
     "label": "HVAC",
     "question": "How's the AC and heating — working okay, do you know the age?"},
    {"id": "windows",        "cost": 10000,
     "label": "Windows",
     "question": "Have the windows ever been replaced?"},
    {"id": "interior_paint", "cost": 4500,
     "label": "Interior paint",
     "question": "How's the interior paint holding up?"},
    {"id": "exterior_paint", "cost": 5000,
     "label": "Exterior paint",
     "question": "What about the outside — paint and siding in decent shape?"},
    {"id": "appliances",     "cost": 4500,
     "label": "Appliances",
     "question": "Does the kitchen have stainless steel appliances?"},
    {"id": "garage_door",    "cost": 2000,
     "label": "Garage door",
     "question": "Is there a garage, and does the door work?"},
    {"id": "water_heater",   "cost": 1200,
     "label": "Water heater",
     "question": "Do you know how old the water heater is?"},
]

# Answers use these states: "needs_work" (add full cost), "good" (adds $0),
# a number (bathrooms count / year built), or absent (unknown -> ask).
ELECTRICAL_PRE_1925 = 20000
PER_BATHROOM = 12000
MISC_DEFAULT = 2000          # general landscaping / small stuff (advanced sheet)
CONTINGENCY_PCT = 0.10       # sheet: Contingency Reserve 10% of rehab

DEFAULT_DESIRED_PROFIT = 30000   # sheet default; walkthrough rule: ~10% of area
                                 # avg sale price, $10k floor, ~5% in $600k+ markets
INVESTOR_RETURN_PCT = 0.10       # flipper expects ~10% of ARV


def compute_repairs(answers):
    """answers: dict item_id -> 'needs_work' | 'good' | number | None.
    Returns (est_repairs:int, breakdown:[{id,label,cost}], unknown:[item_ids]).
    A full-gut signal ('gut' on any item or 8+ needs_work) prices like the
    walkthrough's ~$93k full remodel naturally through the line items."""
    total = 0
    breakdown = []
    unknown = []
    for item in REPAIR_ITEMS:
        iid = item["id"]
        a = (answers or {}).get(iid)
        if a is None:
            unknown.append(iid)
            continue
        cost = 0
        if iid == "year_built":
            try:
                if int(a) < 1925:
                    cost = ELECTRICAL_PRE_1925
            except (TypeError, ValueError):
                unknown.append(iid)
        elif iid == "bathrooms":
            try:
                n = float(a)
                if n > 0:
                    cost = int(n * PER_BATHROOM)
            except (TypeError, ValueError):
                if a == "needs_work":
                    cost = PER_BATHROOM  # count unknown, at least one bath
                elif a == "good":
                    cost = 0
                else:
                    unknown.append(iid)
        else:
            if a == "needs_work":
                cost = item["cost"] or 0
            elif a == "good":
                cost = 0
            else:
                unknown.append(iid)
                continue
        if cost:
            total += cost
            breakdown.append({"id": iid, "label": item["label"], "cost": cost})
    if total or breakdown:
        total += MISC_DEFAULT
        breakdown.append({"id": "misc", "label": "Misc / landscaping", "cost": MISC_DEFAULT})
    contingency = round(total * CONTINGENCY_PCT)
    if total:
        breakdown.append({"id": "contingency", "label": "Contingency 10%", "cost": contingency})
        total += contingency
    return int(total), breakdown, unknown


def next_question(answers):
    """The highest-cost repair item the prospect hasn't answered yet."""
    _, _, unknown = compute_repairs(answers)
    for item in REPAIR_ITEMS:
        if item["id"] in unknown:
            return item
    return None


def cash_offer(arv, repairs, desired_profit=DEFAULT_DESIRED_PROFIT):
    """Cash Offer sheet: ((0.95*ARV) - InvestorReturn - Repairs - Profit) / 1.01"""
    investor_return = 0.10 * arv
    mao = ((0.95 * arv) - investor_return - repairs - desired_profit) / 1.01
    mao = round(mao)
    return {"mao": mao, "offer_low": mao - 5000, "offer_high": mao + 5000,
            "investor_return": round(investor_return),
            "desired_profit": desired_profit, "repairs": round(repairs)}


def mls_fixer(arv, repairs, desired_profit=DEFAULT_DESIRED_PROFIT):
    """MLS Fixer sheet: (0.94*ARV) - Profit - Repairs - (0.05*ARV)"""
    mao = round((0.94 * arv) - desired_profit - repairs - (0.05 * arv))
    return {"mao": mao, "offer_low": mao - 5000, "offer_high": mao + 5000,
            "desired_profit": desired_profit, "repairs": round(repairs)}


def mls_turnkey(arv, desired_profit=DEFAULT_DESIRED_PROFIT):
    """MLS Turnkey sheet: (0.87*ARV) - Profit"""
    mao = round((0.87 * arv) - desired_profit)
    return {"mao": mao, "offer_low": mao - 5000, "offer_high": mao + 5000,
            "desired_profit": desired_profit}


def offer_block(arv, answers, desired_profit=DEFAULT_DESIRED_PROFIT):
    """Full live-underwriting snapshot for one call turn. Returns None without ARV."""
    if not arv:
        return None
    repairs, breakdown, unknown = compute_repairs(answers)
    offer = cash_offer(arv, repairs, desired_profit)
    nxt = next_question(answers)
    return {
        "arv": round(arv),
        "est_repairs": repairs,
        "repair_breakdown": breakdown,
        "mao": offer["mao"],
        "offer_range": [offer["offer_low"], offer["offer_high"]],
        "desired_profit": desired_profit,
        "investor_return": offer["investor_return"],
        "condition_answered": sorted(k for k, v in (answers or {}).items() if v is not None),
        "condition_unknown": unknown,
        "next_condition_question": (nxt["question"] if nxt else None),
        "formula": "((0.95*ARV) - 0.10*ARV - repairs - profit) / 1.01  (Wholesale Offer "
                   "Calculator — Cash Offer sheet)",
    }
