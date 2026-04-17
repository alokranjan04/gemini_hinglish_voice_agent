# -*- coding: utf-8 -*-
"""
Central settings module.
All environment variables, API endpoints, and the mutable APP_CONFIG live here.
Import from this module — never call load_dotenv() or os.getenv() elsewhere.
"""
import os, json
from dotenv import load_dotenv

load_dotenv()

# ── API keys ──────────────────────────────────────────────────────────────────
SARVAM_API_KEY   = os.getenv("SARVAM_API_KEY",   "").strip()
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY",  "").strip()
GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY",    "").strip()
PORT             = int(os.getenv("PORT", "5050"))   # Cloud Run injects this

# ── API endpoints ─────────────────────────────────────────────────────────────
SARVAM_CHAT_URL = "https://api.sarvam.ai/v1/chat/completions"
SARVAM_TTS_URL  = "https://api.sarvam.ai/text-to-speech"

GEMINI_WS_URL = (
    "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage"
    f".v1beta.GenerativeService.BidiGenerateContent?key={GEMINI_API_KEY}"
)

DG_URL = (
    "wss://api.deepgram.com/v1/listen"
    "?model=nova-2&language=hi&encoding=mulaw&sample_rate=8000"
    "&interim_results=true&utterance_end_ms=1500&vad_events=true"
    "&endpointing=500&smart_format=true&numerals=true"
    "&keywords=ungli:2,ungliyan:2,dard:2,bukhaar:2,khansi:2,जुकाम:2,पैर:2,"
    "appointment:3,shift:3,reschedule:3,booking:3,parent:2,child:2,doctor:2,vaccine:2,checkup:2"
)

# ── App config (runtime-mutable: provider switching writes back to disk) ──────
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app_config.json")

_FALLBACK_CONFIG = {
    "agent":           {"name": "Priya", "system_prompt": "You are Priya."},
    "clinic":          {},
    "scripts":         {"greeting": "Namaste"},
    "prompts":         {"sarvam_rules": "", "gemini_rules": "", "caller_context": ""},
    "tools":           {"sarvam": [], "gemini": [{"functionDeclarations": []}]},
    "active_provider": "sarvam",
}


def _load_config() -> dict:
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  Config load error: {e}")
        return _FALLBACK_CONFIG


# Mutable dict shared across all modules — mutations are immediately visible everywhere.
APP_CONFIG: dict = _load_config()


def save_config() -> None:
    """Persist APP_CONFIG back to disk. Called by the /api/set-provider route."""
    with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(APP_CONFIG, f, ensure_ascii=False, indent=4)
