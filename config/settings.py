# -*- coding: utf-8 -*-
"""
Central settings module.
All environment variables, API endpoints, and the mutable APP_CONFIG live here.
Import from this module — never call load_dotenv() or os.getenv() elsewhere.
"""
import os, json, urllib.parse
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

_DG_PARAMS = [
    ("model", "nova-2"),
    ("language", "hi"),
    ("encoding", "mulaw"),
    ("sample_rate", "8000"),
    ("interim_results", "true"),
    ("utterance_end_ms", "1000"),
    ("vad_events", "true"),
    ("endpointing", "400"),
    ("smart_format", "true"),
    ("numerals", "true"),
    ("filler_words", "true"),
    ("keywords", (
        "mujhe:4,bache:4,bachon:4,dikhaana:4,appointment:5,booking:5,book:5,"
        "fever:4,bukhaar:4,bukhar:4,pait:4,dard:4,khansi:4,khaansi:4,ulti:4,"
        "doctor:4,clinic:4,naam:4,umar:4,saal:4,kal:4,aaj:4,subah:4,shaam:4,"
        "koyal:10,कोयल:10,goyal:8,गोयल:8,poonam:7,पूनम:7,ira:6,aira:6,ayra:6,"
        "krishna:6,कृष्णा:6,arjun:6,अर्जुन:6,rahul:5,राहुल:5,ananya:6,अनन्या:6,"
        "trishna:10,तृष्णा:10,trisna:10,trushna:10,aryan:6,आर्यन:6,riya:6,रिया:6,"
        "mohan:5,मोहन:5,rohan:6,रोहन:6,sona:6,सोना:6,neha:5,नेहा:5,priya:5,प्रिया:5"
    ))
]

DG_URL = f"wss://api.deepgram.com/v1/listen?{urllib.parse.urlencode(_DG_PARAMS)}"

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
