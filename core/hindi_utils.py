# -*- coding: utf-8 -*-
"""
Hindi/Hinglish text utilities.

- time_to_hindi()         '06:10 PM'  → 'शाम के छह बजकर दस मिनट'
- day_to_hindi()          'Tuesday'   → 'मंगलवार'
- CONFIRMATION_WORDS      frozenset of words that count as slot confirmation
- JUNK_RE                 strips leaked tool-call tokens from TTS text
- SENT_RE                 sentence boundary splitter for chunked TTS
"""
import re
from datetime import datetime

# ── Regex constants ───────────────────────────────────────────────────────────

JUNK_RE = re.compile(
    r"\b(book_appointment|check_available_slots|arg_key|arg_value|tool_call|tool_response"
    r"|patient_name|preferred_day|preferred_time|patient_age|parent_name|contact_number"
    r"|reason|बेचारा|bechara)\b",
    re.IGNORECASE,
)
SENT_RE = re.compile(r"(?<=[।.!?])\s*")

# ── Confirmation vocabulary ───────────────────────────────────────────────────

CONFIRMATION_WORDS = frozenset({
    "हाँ", "हां", "हाँ जी", "जी हाँ", "जी हां",
    "haan", "han", "yes", "yeah",
    "ठीक", "theek", "ठीक है", "ठीक रहेगा", "ठीक बात", "ठीक बात है",
    "okay", "ok", "bilkul", "sure", "बिल्कुल",
    "चलेगा", "चलेगा जी", "हो जाए", "कर दो", "बुक कर दो",
    "मंज़ूर", "मंजूर", "बढ़िया", "अच्छा",
})

# ── Internal lookup tables ────────────────────────────────────────────────────

_HI_HOUR = {
    1: "एक",  2: "दो",    3: "तीन",    4: "चार",   5: "पाँच",  6: "छह",
    7: "सात", 8: "आठ",    9: "नौ",     10: "दस",  11: "ग्यारह", 12: "बारह",
}
_HI_MIN = {
    5: "पाँच",  10: "दस",    15: "पंद्रह",  20: "बीस",     25: "पच्चीस",
    30: "तीस", 35: "पैंतीस", 40: "चालीस",  45: "पैंतालीस", 50: "पचास", 55: "पचपन",
}
_HI_DAY = {
    "Monday":   "सोमवार",  "Tuesday":  "मंगलवार", "Wednesday": "बुधवार",
    "Thursday": "गुरुवार", "Friday":   "शुक्रवार", "Saturday":  "शनिवार",
    "Sunday":   "रविवार",  "Today":    "आज",       "Tomorrow":  "कल",
}

# ── Public API ────────────────────────────────────────────────────────────────

def day_to_hindi(day_str: str) -> str:
    """'Tuesday' → 'मंगलवार'.  Today's weekday → 'आज'."""
    today = datetime.now().strftime("%A")
    if day_str == today or day_str in ("Today", "today", "आज"):
        return "आज"
    return _HI_DAY.get(day_str, day_str)


def time_to_hindi(time_str: str) -> str:
    """'06:10 PM' → 'शाम के छह बजकर दस मिनट'."""
    try:
        dt     = datetime.strptime(time_str.strip(), "%I:%M %p")
        h24, m = dt.hour, dt.minute
        h12    = h24 % 12 or 12
        period = (
            "सुबह"  if h24 < 12 else
            "दोपहर" if h24 < 17 else
            "शाम"   if h24 < 20 else "रात"
        )
        if m == 0:
            return f"{period} के {_HI_HOUR[h12]} बजे"
        if m == 15:
            return f"{period} के सवा {_HI_HOUR[h12]} बजे"
        if m == 30:
            return f"{period} के साढ़े {_HI_HOUR[h12]} बजे"
        if m == 45:
            nxt = h12 % 12 + 1
            return f"{period} के पौने {_HI_HOUR[nxt]} बजे"
        min_hi = _HI_MIN.get(m, str(m))
        return f"{period} के {_HI_HOUR[h12]} बजकर {min_hi} मिनट"
    except Exception:
        return time_str
