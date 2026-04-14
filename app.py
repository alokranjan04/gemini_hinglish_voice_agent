# -*- coding: utf-8 -*-
import asyncio, sys, base64, json, os, time, audioop, traceback, re, wave, aiohttp, websockets
from datetime import datetime
from time import perf_counter
from aiohttp import web
from dotenv import load_dotenv
from pharmacy_functions import FUNCTION_MAP, send_call_summary_email, APPOINTMENTS_DB
from metrics.collector import store, resource_poller, TurnLatency
from metrics.cost_calculator import calculate_cost
from metrics.dashboard_html import METRICS_DASHBOARD_HTML

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

load_dotenv()

# ── Config ──────────────────────────────────────────────────────────────────
try:
    with open('app_config.json', 'r', encoding='utf-8') as f:
        APP_CONFIG = json.load(f)
except Exception as e:
    print(f"⚠️ Config Load Error: {e}")
    APP_CONFIG = {
        "agent": {"system_prompt": "You are Priya."},
        "scripts": {"greeting": "Hello"},
        "active_provider": "sarvam"
    }

SARVAM_API_KEY   = os.getenv("SARVAM_API_KEY",   "").strip()
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY",  "").strip()
GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY",    "").strip()
PORT             = int(os.getenv("PORT", "5050"))   # Cloud Run injects PORT

SARVAM_CHAT_URL = "https://api.sarvam.ai/v1/chat/completions"
SARVAM_TTS_URL  = "https://api.sarvam.ai/text-to-speech"
GEMINI_WS_URL   = (
    "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage"
    f".v1beta.GenerativeService.BidiGenerateContent?key={GEMINI_API_KEY}"
)

# ── Tool definitions ─────────────────────────────────────────────────────────

# Sarvam (OpenAI-compatible JSON schema)
SARVAM_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_available_slots",
            "description": "Check which 10-minute appointment slots are free for a given day.",
            "parameters": {
                "type": "object",
                "properties": {
                    "preferred_day": {
                        "type": "string",
                        "description": "Day name: Monday–Saturday, or 'Today'"
                    }
                },
                "required": ["preferred_day"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": (
                "Book a doctor appointment. "
                "Call ONLY after the user has explicitly confirmed the slot (day + time). "
                "Pass the exact day and time the user confirmed — never use defaults. "
                "NEVER write args as plain text — always invoke this tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name":   {"type": "string", "description": "Child's name ONLY"},
                    "reason":         {"type": "string", "description": "Medical reason / sickness ONLY"},
                    "preferred_day":  {"type": "string", "description": "Day the user confirmed, e.g. 'Monday'"},
                    "preferred_time": {"type": "string", "description": "Time the user confirmed, e.g. '06:40 PM'"}
                },
                "required": ["patient_name", "reason", "preferred_day", "preferred_time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_appointment",
            "description": (
                "Cancel an existing appointment. "
                "Call IMMEDIATELY when user says cancel / रद्द / cancel करो. "
                "You already have contact_number from the call — do NOT ask for it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name": {"type": "string", "description": "Child's name to cancel"}
                },
                "required": ["patient_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "reschedule_appointment",
            "description": "Reschedule an existing appointment to a new day and time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name": {"type": "string", "description": "Child's name"},
                    "new_day":      {"type": "string", "description": "New day, e.g. 'Monday'"},
                    "new_time":     {"type": "string", "description": "New time, e.g. '06:00 PM'"}
                },
                "required": ["patient_name", "new_day", "new_time"]
            }
        }
    }
]

# Gemini (Multimodal Live API format — camelCase, uppercase types)
GEMINI_TOOLS = [
    {
        "functionDeclarations": [
            {
                "name": "check_available_slots",
                "description": "Check available 10-minute appointment slots for a given day (Monday–Saturday).",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"preferred_day": {"type": "STRING", "description": "Day name, e.g. Monday or Today"}},
                    "required": ["preferred_day"]
                }
            },
            {
                "name": "book_appointment",
                "description": (
                    "Book a doctor appointment. Call ONLY after user confirms the slot. "
                    "Pass the exact confirmed day and time."
                ),
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "patient_name":   {"type": "STRING", "description": "Child's name only"},
                        "reason":         {"type": "STRING", "description": "Medical reason / sickness"},
                        "preferred_day":  {"type": "STRING", "description": "Confirmed day, e.g. Monday"},
                        "preferred_time": {"type": "STRING", "description": "Confirmed time, e.g. 06:40 PM"}
                    },
                    "required": ["patient_name", "reason", "preferred_day", "preferred_time"]
                }
            },
            {
                "name": "cancel_appointment",
                "description": "Cancel an existing appointment for a patient.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "patient_name":   {"type": "STRING"},
                        "contact_number": {"type": "STRING"}
                    },
                    "required": ["patient_name"]
                }
            },
            {
                "name": "reschedule_appointment",
                "description": "Reschedule an existing appointment to a new day and time.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "patient_name":   {"type": "STRING"},
                        "contact_number": {"type": "STRING"},
                        "new_day":        {"type": "STRING"},
                        "new_time":       {"type": "STRING"}
                    },
                    "required": ["patient_name", "new_day", "new_time"]
                }
            }
        ]
    }
]

# ── Regex constants ───────────────────────────────────────────────────────────
JUNK_RE = re.compile(
    r'\b(book_appointment|check_available_slots|arg_key|arg_value|tool_call|tool_response'
    r'|patient_name|preferred_day|preferred_time|patient_age|parent_name|contact_number'
    r'|reason|बेचारा|bechara)\b',
    re.IGNORECASE
)
SENT_RE = re.compile(r'(?<=[।.!?])\s*')

# ── Time → Hindi speech ───────────────────────────────────────────────────────
_HI_HOUR = {1:"एक", 2:"दो", 3:"तीन", 4:"चार", 5:"पाँच", 6:"छह",
             7:"सात", 8:"आठ", 9:"नौ", 10:"दस", 11:"ग्यारह", 12:"बारह"}
_HI_MIN  = {5:"पाँच", 10:"दस", 15:"पंद्रह", 20:"बीस", 25:"पच्चीस",
             30:"तीस", 35:"पैंतीस", 40:"चालीस", 45:"पैंतालीस", 50:"पचास", 55:"पचपन"}

_HI_DAY = {
    "Monday":    "सोमवार",  "Tuesday":  "मंगलवार", "Wednesday": "बुधवार",
    "Thursday":  "गुरुवार", "Friday":   "शुक्रवार", "Saturday":  "शनिवार",
    "Sunday":    "रविवार",  "Today":    "आज",       "Tomorrow":  "कल",
}

def _day_to_hindi(day_str: str) -> str:
    """'Tuesday' → 'मंगलवार', 'Tomorrow' → 'कल', today's weekday → 'आज'"""
    today = datetime.now().strftime("%A")
    if day_str == today or day_str in ("Today", "today", "आज"):
        return "आज"
    return _HI_DAY.get(day_str, day_str)

def _time_to_hindi(time_str: str) -> str:
    """'06:10 PM' → 'शाम के छह बजकर दस मिनट'"""
    try:
        dt  = datetime.strptime(time_str.strip(), "%I:%M %p")
        h24, m = dt.hour, dt.minute
        h12 = h24 % 12 or 12
        period = ("सुबह"   if h24 < 12 else
                  "दोपहर"  if h24 < 17 else
                  "शाम"    if h24 < 20 else "रात")
        if m == 0:
            return f"{period} के {_HI_HOUR[h12]} बजे"
        elif m == 15:
            return f"{period} के सवा {_HI_HOUR[h12]} बजे"
        elif m == 30:
            return f"{period} के साढ़े {_HI_HOUR[h12]} बजे"
        elif m == 45:
            nxt = h12 % 12 + 1
            return f"{period} के पौने {_HI_HOUR[nxt]} बजे"
        else:
            min_hi = _HI_MIN.get(m, str(m))
            return f"{period} के {_HI_HOUR[h12]} बजकर {min_hi} मिनट"
    except Exception:
        return time_str

# Words that count as explicit slot confirmation (substring match on user turn)
CONFIRMATION_WORDS = frozenset({
    'हाँ', 'हां', 'हाँ जी', 'जी हाँ', 'जी हां',
    'haan', 'han', 'yes', 'yeah',
    'ठीक', 'theek', 'ठीक है', 'ठीक रहेगा', 'ठीक बात', 'ठीक बात है',
    'okay', 'ok', 'bilkul', 'sure', 'बिल्कुल',
    'चलेगा', 'चलेगा जी', 'हो जाए', 'कर दो', 'बुक कर दो',
    'मंज़ूर', 'मंजूर', 'बढ़िया', 'अच्छा',
})

# ── Call recorder (timeline-based mono mix) ──────────────────────────────────
class _TimelineRecorder:
    """
    Stereo PCM-16 LE @ 8 kHz.
    Left channel = caller, Right channel = Priya.

    Each channel has its own head pointer.  New audio is placed at:
        pos = max(wall_clock_byte_offset, channel_head)
    This preserves natural silence gaps while preventing any chunk from
    overwriting audio that was already written but hasn't finished playing
    yet (the main cause of garbled recordings when TTS chunks arrive faster
    than real-time playback speed).
    """
    __slots__ = ('_caller', '_priya', '_start', '_caller_head', '_priya_head')

    def __init__(self):
        self._caller      = bytearray()
        self._priya       = bytearray()
        self._start       = time.perf_counter()
        self._caller_head = 0   # byte offset after last caller write
        self._priya_head  = 0   # byte offset after last priya write

    def _place(self, buf: bytearray, pcm: bytes, head: int) -> int:
        """Write pcm at max(wall_clock, head); return new head."""
        wc = int((time.perf_counter() - self._start) * 8000) * 2
        pos = max(wc, head)
        end = pos + len(pcm)
        if len(buf) < end:
            buf.extend(b'\x00' * (end - len(buf)))
        buf[pos:end] = pcm
        return end

    def write_caller(self, pcm: bytes):
        """Record caller audio (left channel)."""
        self._caller_head = self._place(self._caller, pcm, self._caller_head)

    def write_priya(self, pcm: bytes):
        """Record Priya TTS audio (right channel)."""
        self._priya_head = self._place(self._priya, pcm, self._priya_head)

    def write(self, pcm: bytes):
        """Backward-compat alias → caller channel."""
        self.write_caller(pcm)

    def save(self, path: str):
        import array as _array
        n = max(len(self._caller), len(self._priya))
        n = (n + 1) & ~1                                    # round to whole 2-byte samples
        caller_b = bytes(self._caller) + b'\x00' * (n - len(self._caller))
        priya_b  = bytes(self._priya)  + b'\x00' * (n - len(self._priya))
        caller_s = _array.array('h', caller_b)
        priya_s  = _array.array('h', priya_b)
        stereo   = _array.array('h')
        for c, p in zip(caller_s, priya_s):
            stereo.append(c)   # left  = caller
            stereo.append(p)   # right = Priya
        with wave.open(path, 'wb') as wf:
            wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(8000)
            wf.writeframes(stereo.tobytes())

    def __bool__(self):
        return bool(self._caller) or bool(self._priya)


# ── Persistent HTTP session ───────────────────────────────────────────────────
_HTTP_SESSION: aiohttp.ClientSession | None = None

def _http() -> aiohttp.ClientSession:
    global _HTTP_SESSION
    if _HTTP_SESSION is None or _HTTP_SESSION.closed:
        _HTTP_SESSION = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=20, ttl_dns_cache=300)
        )
    return _HTTP_SESSION


# ── Sarvam helpers ────────────────────────────────────────────────────────────

async def _sarvam_tts(text: str):
    if not text:
        return None
    payload = {"inputs": [text], "target_language_code": "hi-IN", "speaker": "anushka",
               "speech_sample_rate": 8000, "model": "bulbul:v2"}
    try:
        async with _http().post(SARVAM_TTS_URL, json=payload,
                                headers={"api-subscription-key": SARVAM_API_KEY}) as r:
            return (await r.json())["audios"][0] if r.status == 200 else None
    except Exception:
        return None

async def _sarvam_chat(messages: list) -> dict:
    headers = {"Content-Type": "application/json", "api-subscription-key": SARVAM_API_KEY}
    payload = {"model": "sarvam-30b", "messages": messages,
               "tools": SARVAM_TOOLS, "temperature": 0.1}
    try:
        async with _http().post(SARVAM_CHAT_URL, json=payload, headers=headers) as r:
            return (await r.json())["choices"][0]["message"] if r.status == 200 \
                   else {"role": "assistant", "content": "माफ़ी, एक समस्या आई।"}
    except Exception:
        return {"role": "assistant", "content": "माफ़ी, एक समस्या आई।"}

async def _sarvam_stream_once(messages: list):
    """Single attempt to stream completions. Yields ("text", str) or ("tool", dict)."""
    headers  = {"Content-Type": "application/json", "api-subscription-key": SARVAM_API_KEY}
    payload  = {"model": "sarvam-30b", "messages": messages,
                "tools": SARVAM_TOOLS, "temperature": 0.1, "stream": True}
    timeout  = aiohttp.ClientTimeout(total=12)
    tool_bufs: dict = {}
    try:
        async with _http().post(SARVAM_CHAT_URL, json=payload, headers=headers,
                                timeout=timeout) as r:
            ct = r.headers.get("Content-Type", "")
            if "application/json" in ct:
                data = await r.json()
                msg  = data["choices"][0]["message"]
                if msg.get("content"):
                    yield ("text", msg["content"])
                for tc in msg.get("tool_calls", []):
                    yield ("tool", tc)
                return
            async for raw in r.content:
                line = raw.decode("utf-8").strip()
                if not line.startswith("data: "):
                    continue
                s = line[6:]
                if s == "[DONE]":
                    break
                try:
                    chunk = json.loads(s)
                    delta = chunk["choices"][0]["delta"]
                    if delta.get("content"):
                        yield ("text", delta["content"])
                    for tc in delta.get("tool_calls", []):
                        i = tc.get("index", 0)
                        if i not in tool_bufs:
                            tool_bufs[i] = {"id": "", "name": "", "arguments": ""}
                        if tc.get("id"):
                            tool_bufs[i]["id"] = tc["id"]
                        fn = tc.get("function", {})
                        if fn.get("name"):
                            tool_bufs[i]["name"] = fn["name"]
                        if fn.get("arguments"):
                            tool_bufs[i]["arguments"] += fn["arguments"]
                except Exception:
                    pass
    except Exception as e:
        print(f"[STREAM ERROR] {e}")
        return
    for i in sorted(tool_bufs):
        buf = tool_bufs[i]
        if buf["name"]:
            yield ("tool", {
                "id": buf["id"], "type": "function",
                "function": {"name": buf["name"], "arguments": buf["arguments"]}
            })


async def _sarvam_stream(messages: list):
    """Stream completions with one automatic retry on empty response."""
    had_output = False
    async for kind, val in _sarvam_stream_once(messages):
        had_output = True
        yield kind, val
    if not had_output:
        print("[SARVAM RETRY] Empty response — retrying once")
        async for kind, val in _sarvam_stream_once(messages):
            yield kind, val


# ── Sarvam pipeline handler ──────────────────────────────────────────────────

async def sarvam_handler(request):
    ws        = web.WebSocketResponse(protocols=['audio.drachtio.org'])
    await ws.prepare(request)
    caller_id = request.query.get("caller_id", "Unknown")
    sid, dg_ws = None, None

    # ── Call state ─────────────────────────────────────────────────────────
    is_responding      = False
    is_speaking        = False
    speak_task         = None
    partial_hyp        = ""
    pending_transcript = None   # last utterance dropped while busy — replayed after response
    call_metrics  = None        # set after stream SID is known
    poll_task     = None
    tts_chars = 0               # total chars sent to TTS this call (for cost)
    recorder  = _TimelineRecorder()  # full call timeline (caller + Priya)
    call_start_time = time.time()

    # ── System prompt ──────────────────────────────────────────────────────
    now = datetime.now()

    # Check if this caller already has an existing booking (same session)
    _existing = [
        appt for appt in APPOINTMENTS_DB["appointments"].values()
        if str(appt.get("contact_number", "")) == str(caller_id)
    ]
    _caller_ctx = ""
    if _existing:
        _booking_strs = ", ".join(
            f"{a['patient_name']} on {a['preferred_day']} at {a['preferred_time']}"
            for a in _existing
        )
        _caller_ctx = (
            f"\n\nCALLER CONTEXT: This caller already has a booked appointment: {_booking_strs}. "
            "As soon as the call connects, ask: 'आपका पहले से appointment है — क्या आप उसी के बारे में बात करना चाहते हैं, या नया appointment चाहिए?'"
        )

    _prompt_header = (
        f"{APP_CONFIG['agent']['system_prompt']}\n\n"
        f"REAL-TIME: {now.strftime('%I:%M %p')} on {now.strftime('%A')}."
        + (_caller_ctx if _caller_ctx else "")
        + "\n\n"
    )
    system_instructions = _prompt_header + (
        "STRICT SYSTEM RULES:\n"
        "1. NO REPETITION: NEVER repeat the same sentence twice. Say each thing ONCE only.\n"
        "2. NO PITY WORDS: NEVER say 'Bechara', 'बेचारा', 'Oh', 'poor thing'. "
        "One calm acknowledgement, then move on.\n"
        "3. GREETING RULE: If caller says ONLY 'Hello', 'Hi', 'हेलो', 'हाँ', 'जी' → "
        "say EXACTLY 'जी, बताइए।' — NOTHING ELSE. NEVER say 'नमस्ते' again after the "
        "greeting was already played. NEVER re-introduce yourself mid-call.\n"
        "4. MEMORY RULE: Once the caller mentions the child's name OR the problem/symptom, "
        "it is captured — do NOT ask for it again. Even if the transcription sounds garbled, "
        "accept it and move on. Only ask for the name a second time if NO name was heard at all.\n"
        "5. BOOKING FLOW — follow IN ORDER:\n"
        "   Step 1 — Extract child NAME and REASON from the ENTIRE conversation above.\n"
        "     Rules for extraction:\n"
        "     • Any health complaint (तबीयत ख़राब, बुखार, पेट दर्द, खाँसी, उल्टी, etc.) = REASON — do NOT ask again.\n"
        "     • Any child's name mentioned ('नाम X है', 'X को दिखाना', 'मेरी बच्ची/बेटा X') = NAME — do NOT ask again.\n"
        "     • NAME CORRECTION: If user says 'X नहीं Y है', 'नाम Y है', 'Y नाम है' — the LATEST mentioned name is correct. Use it.\n"
        "     Decision:\n"
        "       → BOTH known: skip all questions, go DIRECTLY to Step 2.\n"
        "       → Only REASON known: ask ONLY 'बच्चे का नाम क्या है?'\n"
        "       → Only NAME known: ask ONLY 'क्या तकलीफ है?'\n"
        "       → NEITHER known: ask 'बच्चे का नाम और क्या तकलीफ है?'\n"
        "     NEVER ask for information already present in the conversation. NEVER repeat the question.\n"
        "   Step 2 — IMMEDIATELY call check_available_slots(preferred_day='Today').\n"
        "            NEVER ask the caller for the day or date — you already know from REAL-TIME.\n"
        "            → Slots come as {time_en, time_hi}. ALWAYS say time_hi to the caller.\n"
        "   Step 3 — Offer ONE slot: 'क्या [time_hi] का समय ठीक रहेगा?'\n"
        "            → If caller says no, offer the NEXT slot's time_hi.\n"
        "   Step 4 — ONLY after explicit YES → call book_appointment with time_en (English format).\n"
        "   NEVER call book_appointment before asking.\n"
        "6. CANCEL: If caller says cancel / रद्द / cancel करो → IMMEDIATELY call "
        "cancel_appointment(patient_name=...). The contact_number is already known — "
        "NEVER ask the caller for their number.\n"
        "6b. NAME CORRECTION after booking: If caller corrects the child's name AFTER a booking "
        "was already made (says 'X नहीं Y है' or 'नाम Y है'):\n"
        "    → call cancel_appointment for the OLD name\n"
        "    → IMMEDIATELY call book_appointment with the CORRECTED name, SAME reason and SAME "
        "time slot that are already in the conversation\n"
        "    → Do NOT ask for reason or slot again — they are ALREADY KNOWN from history\n"
        "    → Say: 'जी, [corrected_name] का appointment book कर दिया।'\n"
        "7. MEMORY: You have the full conversation above. NEVER ask for name or symptom "
        "that was already mentioned. If caller says 'बता चुके हैं' or 'अभी तो बताया था', "
        "use what is already in the conversation — DO NOT ask again.\n"
        "8. TIME FORMAT: NEVER say '11:30 AM' or '06:10 PM'. "
        "Always Hindi: 'सुबह के साढ़े ग्यारह बजे', 'शाम के छह बजे'.\n"
        "9. ONE QUESTION at a time. Responses under 10 words. Move FAST.\n"
        "10. CLINIC HOURS: Doctor works ONLY in two slots:\n"
        "    • सुबह: 10:00 AM – 12:00 PM\n"
        "    • शाम: 06:00 PM – 08:00 PM\n"
        "    Sunday: CLOSED.\n"
        "    If caller asks for a time OUTSIDE these hours (जैसे दोपहर 2 बजे, 3 बजे, 4 बजे, "
        "5 बजे) say: 'डॉक्टर सुबह दस से बारह और शाम छह से आठ बजे मिलते हैं।' then offer "
        "the next available slot from check_available_slots.\n"
        "    After 12:00 PM, morning slots are GONE — NEVER offer them. "
        "Offer the first available EVENING slot instead (शाम के छह बजे या उसके बाद)."
    )
    history = [{"role": "system", "content": system_instructions}]

    async def clear_audio():
        if sid and not ws.closed:
            try:
                await ws.send_str(json.dumps({"event": "clearAudio", "streamId": sid}))
            except Exception:
                pass

    async def speak(t: str):
        nonlocal is_speaking, tts_chars
        if not t:
            return
        raw = t
        t = re.sub(r'<[^>]+>', '', t).strip()
        t = JUNK_RE.sub('', t)
        t = re.sub(r'\s+', ' ', t).strip()
        if not t or len(t) < 2:
            print(f"[SPEAK] stripped to empty — raw was: {raw!r}")
            return
        tts_chars += len(t)
        audio = await _sarvam_tts(t)
        if not audio:
            print(f"[SPEAK] TTS returned None for: {t!r}")
            return
        if audio and sid:
            is_speaking = True
            try:
                print(f"🤖 Priya: {t}")
                pcm = base64.b64decode(audio)
                if pcm.startswith(b'RIFF'):
                    # Parse WAV properly — header can be >44 bytes (extended fmt chunks)
                    try:
                        import io as _io
                        with wave.open(_io.BytesIO(pcm), 'rb') as _wf:
                            pcm = _wf.readframes(_wf.getnframes())
                    except Exception:
                        pcm = pcm[44:]   # fallback
                recorder.write_priya(pcm)          # always record regardless of WS state
                if not ws.closed:
                    mulaw = audioop.lin2ulaw(pcm, 2)
                    await ws.send_str(json.dumps({
                        "event": "playAudio", "streamId": sid,
                        "media": {"contentType": "audio/x-mulaw", "sampleRate": 8000,
                                  "payload": base64.b64encode(mulaw).decode("utf-8")}
                    }))
                    # Hold is_speaking=True for actual playback duration.
                    # asyncio.sleep is a cancellation point — a barge-in cancel()
                    # will interrupt here immediately, not wait for the sleep to finish.
                    playback_secs = len(mulaw) / 8000.0
                    await asyncio.sleep(playback_secs)
            finally:
                is_speaking = False

    # Words that are pure ambient noise / line-test greetings — handled without LLM
    _GREETING_WORDS = frozenset({
        "hello", "hi", "हेलो", "हाय", "namaste", "नमस्ते", "hey",
        "hello?", "hi?", "हेलो?", "हाय?",
    })

    async def handle_transcript(transcript: str):
        nonlocal is_responding, speak_task, pending_transcript
        if is_responding:
            pending_transcript = transcript   # save latest; replayed after current turn
            print(f"💾 [QUEUED]: {transcript}")
            return

        # ── Greeting intercept: single-word greetings never need LLM ──────────
        tr_lower = transcript.strip().lower().rstrip(".")
        if tr_lower in _GREETING_WORDS:
            print(f"👤 User (greeting): {transcript}")
            await speak("जी, बताइए।")
            return

        pending_transcript = None
        is_responding = True
        t_start = time.time()
        turn_llm_ms = turn_tts_ms = turn_tool_ms = None
        try:
            print(f"👤 User: {transcript}")
            history.append({"role": "user", "content": transcript})
            if call_metrics:
                call_metrics.record_turn("user", transcript)

            if len(history) > 12:
                history[1:] = history[-11:]  # keep system prompt + last 11 messages

            t_llm     = time.time()
            full_text = ""
            tool_calls = []
            sent_buf  = ""

            async def flush_sent(s: str):
                nonlocal speak_task
                s = s.strip()
                if s:
                    speak_task = asyncio.create_task(speak(s))
                    await speak_task

            async for kind, val in _sarvam_stream(history):
                if kind == "text":
                    full_text += val
                    sent_buf  += val
                    parts = SENT_RE.split(sent_buf)
                    for p in parts[:-1]:
                        await flush_sent(p)
                    sent_buf = parts[-1]
                elif kind == "tool":
                    tool_calls.append(val)

            if sent_buf.strip() and not tool_calls:
                await flush_sent(sent_buf)

            turn_llm_ms = int((time.time() - t_llm) * 1000)
            print(f"⏱  LLM+TTS : {turn_llm_ms} ms")
            if not full_text and not tool_calls:
                print(f"⚠  [LLM EMPTY] No text and no tool calls after {turn_llm_ms}ms — Sarvam API may have returned nothing")

            # ── Hallucination guard ────────────────────────────────────────
            if full_text and not tool_calls:
                hall_triggers = {"patient_name", "preferred_day", "preferred_time", "arg_key"}
                if any(k in full_text.lower() for k in hall_triggers):
                    print(f"⚠ [HALLUC] Detected: {full_text[:80]}")
                    if call_metrics:
                        call_metrics.record_hallucination()
                    xml_pairs = re.findall(
                        r'<arg_key>\s*(\w+)\s*</arg_key>\s*<arg_value>\s*(.*?)\s*</arg_value>',
                        full_text, re.DOTALL
                    )
                    fn_match = re.search(r'\b(book_appointment|check_available_slots)\b', full_text)
                    fn_name  = fn_match.group(1) if fn_match else None
                    if xml_pairs and fn_name:
                        extracted = {k: v.strip() for k, v in xml_pairs}
                        print(f"⚠ [HALLUC] Extracted → {fn_name}({extracted})")
                        tool_calls = [{"id": "halluc_0", "type": "function",
                                       "function": {"name": fn_name, "arguments": json.dumps(extracted)}}]
                    full_text = ""

            # Build assistant history entry
            asst: dict = {"role": "assistant", "content": full_text or None}
            if tool_calls:
                asst["tool_calls"] = [
                    {"id": tc.get("id", f"tc_{i}"), "type": "function", "function": tc["function"]}
                    for i, tc in enumerate(tool_calls)
                ]
            history.append(asst)
            if call_metrics and full_text:
                call_metrics.record_turn("assistant", full_text)

            # ── Execute tool calls ─────────────────────────────────────────
            if tool_calls:
                booking_confirmed  = False
                booking_args       = {}
                slots_res          = None   # set if check_available_slots was called

                for i, tc in enumerate(tool_calls):
                    fn   = tc["function"]["name"]
                    args = json.loads(tc["function"]["arguments"])
                    if fn == "book_appointment":
                        if not args.get("preferred_time"): args["preferred_time"] = "06:00 PM"
                        if not args.get("preferred_day"):  args["preferred_day"]  = "Today"
                        args.update({"patient_age": "5", "parent_name": "Guardian",
                                     "contact_number": caller_id})
                    elif fn in ("cancel_appointment", "reschedule_appointment"):
                        # Auto-inject caller's number — never ask the user for it
                        if not args.get("contact_number"):
                            args["contact_number"] = caller_id
                    print(f"🔧 Tool: {fn}({args})")
                    t_tool = time.time()
                    res = await asyncio.to_thread(FUNCTION_MAP[fn], **args)
                    turn_tool_ms = int((time.time() - t_tool) * 1000)
                    if call_metrics:
                        call_metrics.record_tool_call(fn, args, res, turn_tool_ms)
                    if fn == "check_available_slots" and isinstance(res, dict):
                        slots_res = res
                        # Build a Hindi-labelled version for the LLM so it speaks times naturally.
                        # Keep time_en alongside so the LLM knows what to pass to book_appointment.
                        hi_res = dict(res)
                        if hi_res.get("available_slots"):
                            hi_res["available_slots"] = [
                                {"time_en": s, "time_hi": _time_to_hindi(s)}
                                for s in hi_res["available_slots"]
                            ]
                        if hi_res.get("urgent_message"):
                            # urgent_message already in Hindi — keep as-is
                            pass
                        llm_content = json.dumps(hi_res, ensure_ascii=False)
                    else:
                        llm_content = json.dumps(res)
                    history.append({"role": "tool", "tool_call_id": tc.get("id", f"tc_{i}"),
                                    "name": fn, "content": llm_content})
                    if fn == "book_appointment" and isinstance(res, dict) and res.get("success"):
                        booking_confirmed = True
                        booking_args      = args

                if booking_confirmed:
                    # Use scripted confirmation — no LLM follow-up needed
                    tmpl = APP_CONFIG.get("scripts", {}).get(
                        "booking_confirmation",
                        "{day} {time} बजे {patient_name} का appointment मैंने book कर दिया है। "
                        "आप please 15 minutes पहले आ जाइए। तब तक बच्चे का ध्यान रखिएगा।"
                    )
                    raw_time = booking_args.get("preferred_time", "")
                    raw_day  = booking_args.get("preferred_day", "")
                    confirmation = tmpl.format(
                        day=_day_to_hindi(raw_day),
                        time=_time_to_hindi(raw_time) if raw_time else "",
                        patient_name=booking_args.get("patient_name", ""),
                    )
                    await flush_sent(confirmation)
                    history.append({"role": "assistant", "content": confirmation})
                    if call_metrics:
                        call_metrics.record_turn("assistant", confirmation)
                elif slots_res is not None:
                    # Build slot-offer directly — skip second LLM round-trip entirely
                    if slots_res.get("urgent_message"):
                        slot_reply = slots_res["urgent_message"]
                    elif slots_res.get("available_slots"):
                        first    = slots_res["available_slots"][0]
                        first_hi = _time_to_hindi(first)
                        slot_reply = f"क्या आज {first_hi} का समय ठीक रहेगा?"
                    else:
                        # Today is empty — fetch tomorrow's real slots
                        tmr_res = await asyncio.to_thread(
                            FUNCTION_MAP["check_available_slots"], preferred_day="Tomorrow"
                        )
                        if tmr_res.get("available_slots"):
                            first       = tmr_res["available_slots"][0]
                            first_hi    = _time_to_hindi(first)
                            tmr_day_en  = tmr_res.get("day", "Tomorrow")
                            tmr_day_hi  = _HI_DAY.get(tmr_day_en, "कल")
                            slot_reply  = f"आज appointment नहीं है। क्या {tmr_day_hi} {first_hi} का समय ठीक रहेगा?"
                            # ── Critical: update the tool-result history entry so the LLM
                            # knows these slots are for tomorrow, not today.
                            hi_tmr = dict(tmr_res)
                            hi_tmr["available_slots"] = [
                                {"time_en": s, "time_hi": _time_to_hindi(s)}
                                for s in hi_tmr["available_slots"]
                            ]
                            history[-1]["content"] = json.dumps(hi_tmr, ensure_ascii=False)
                            slots_res = tmr_res
                        else:
                            slot_reply = "आज और कल कोई slot नहीं है। किसी और दिन के लिए बताएं?"
                    print(f"[SLOTS] Direct reply: {slot_reply!r}")
                    await flush_sent(slot_reply)
                    history.append({"role": "assistant", "content": slot_reply})
                    if call_metrics:
                        call_metrics.record_turn("assistant", slot_reply)
                else:
                    # Stream LLM follow-up for non-booking tools (slots check, cancel, etc.)
                    followup      = ""
                    f_buf         = ""
                    t_tts         = time.time()
                    spoke_any     = False
                    followup_tools = []
                    async for kind, val in _sarvam_stream(history):
                        if kind == "text":
                            followup += val
                            f_buf    += val
                            parts = SENT_RE.split(f_buf)
                            for p in parts[:-1]:
                                if p.strip():
                                    spoke_any = True
                                await flush_sent(p)
                            f_buf = parts[-1]
                        elif kind == "tool":
                            followup_tools.append(val)
                    if f_buf.strip():
                        spoke_any = True
                        await flush_sent(f_buf)
                    turn_tts_ms = int((time.time() - t_tts) * 1000)
                    print(f"[FOLLOWUP] spoke={spoke_any} text={followup[:80]!r} tools={[t['function']['name'] for t in followup_tools]}")

                    # Record assistant message — include tool_calls if present so history is valid
                    asst_followup: dict = {"role": "assistant", "content": followup or None}
                    if followup_tools:
                        asst_followup["tool_calls"] = [
                            {"id": ftc.get("id", f"ft_{j}"), "type": "function", "function": ftc["function"]}
                            for j, ftc in enumerate(followup_tools)
                        ]
                    history.append(asst_followup)
                    if call_metrics and followup:
                        call_metrics.record_turn("assistant", followup)

                    # ── Execute book_appointment from followup if cancel triggered it ──
                    # (name-correction rebook: cancel succeeded, LLM wants to rebook immediately)
                    last_fn = tool_calls[-1]["function"]["name"] if tool_calls else ""
                    if last_fn == "cancel_appointment" and followup_tools:
                        for ftc in followup_tools:
                            if ftc["function"]["name"] == "book_appointment":
                                fargs = json.loads(ftc["function"]["arguments"] or "{}")
                                if not fargs.get("preferred_time"): fargs["preferred_time"] = "06:00 PM"
                                if not fargs.get("preferred_day"):  fargs["preferred_day"]  = "Today"
                                fargs.update({"patient_age": "5", "parent_name": "Guardian",
                                              "contact_number": caller_id})
                                print(f"🔧 [REBOOK] {ftc['function']['name']}({fargs})")
                                fres = await asyncio.to_thread(FUNCTION_MAP["book_appointment"], **fargs)
                                history.append({"role": "tool",
                                                "tool_call_id": ftc.get("id", "ft_0"),
                                                "name": "book_appointment",
                                                "content": json.dumps(fres, ensure_ascii=False)})
                                if isinstance(fres, dict) and fres.get("success"):
                                    conf_msg = fres.get("confirmation_message") or (
                                        f"{_day_to_hindi(fargs['preferred_day'])} "
                                        f"{_time_to_hindi(fargs['preferred_time'])} "
                                        f"{fargs.get('patient_name','')} का appointment "
                                        "मैंने book कर दिया है। आप please 15 minutes पहले आ जाइए।"
                                    )
                                    await flush_sent(conf_msg)
                                    history.append({"role": "assistant", "content": conf_msg})
                                    if call_metrics:
                                        call_metrics.record_turn("assistant", conf_msg)
                                    spoke_any = True
                                break  # only process the first book_appointment

                    # ── Fallback: LLM produced no speech after tool call ──────
                    if not spoke_any:
                        last_res = json.loads(history[-2]["content"]) if len(history) >= 2 else {}
                        if last_fn == "check_available_slots":
                            if last_res.get("urgent_message"):
                                fb = last_res["urgent_message"]
                            elif last_res.get("available_slots"):
                                first    = last_res["available_slots"][0]
                                first_hi = _time_to_hindi(first)
                                fb = f"क्या आज {first_hi} का समय ठीक रहेगा?"
                            else:
                                fb = "आज कोई slot नहीं है। कल सुबह दस बजे का समय ठीक रहेगा?"
                        elif last_fn == "cancel_appointment":
                            fb = "जी, appointment cancel हो गई।"
                        else:
                            fb = "जी, हो गया।"
                        print(f"[FALLBACK] Speaking directly: {fb!r}")
                        await flush_sent(fb)
                        history.append({"role": "assistant", "content": fb})
                        if call_metrics:
                            call_metrics.record_turn("assistant", fb)

            e2e_ms = int((time.time() - t_start) * 1000)
            print(f"⏱  E2E    : {e2e_ms} ms")

            if call_metrics:
                call_metrics.turn_latencies.append(TurnLatency(
                    turn_index=call_metrics._current_turn_index,
                    llm_ms=turn_llm_ms,
                    tts_ms=turn_tts_ms,
                    tool_ms=turn_tool_ms,
                    e2e_ms=e2e_ms,
                ))
                call_metrics._current_turn_index += 1

        except asyncio.CancelledError:
            print("🚫 [BARGE-IN] Response cancelled — user spoke")
        finally:
            is_responding = False
            # Replay the last utterance dropped while we were busy
            if pending_transcript:
                pt, pending_transcript = pending_transcript, None
                print(f"▶️  [REPLAY]: {pt}")
                asyncio.create_task(handle_transcript(pt))

    async def vobiz_keep_alive():
        silence = base64.b64encode(audioop.lin2ulaw(b'\x00' * 160, 2)).decode("utf-8")
        while not ws.closed:
            if sid:
                await ws.send_str(json.dumps({
                    "event": "playAudio", "streamId": sid,
                    "media": {"contentType": "audio/x-mulaw", "sampleRate": 8000, "payload": silence}
                }))
            await asyncio.sleep(0.8)

    async def dg_receiver():
        nonlocal partial_hyp, speak_task
        try:
            async for raw in dg_ws:
                d        = json.loads(raw)
                msg_type = d.get("type", "")

                if msg_type == "SpeechStarted":
                    print("🎤 [VAD] Speech started")
                    # Do NOT cancel here — SpeechStarted fires on any audio energy
                    # (fan, AC, background TV). Barge-in is triggered only when a
                    # real interim transcript with ≥2 words arrives (see below).
                    continue

                if msg_type == "UtteranceEnd":
                    print("🔇 [VAD] Utterance end")
                    ph = partial_hyp.strip()
                    partial_hyp = ""
                    if ph and len(ph.split()) >= 2:
                        # Require at least 2 words on UtteranceEnd flush —
                        # single-word noise pops ("हाँ", "Hello", random murmur) are
                        # handled by the greeting intercept or ignored
                        asyncio.create_task(handle_transcript(ph))
                    elif ph:
                        # Single word — let the greeting intercept handle it
                        asyncio.create_task(handle_transcript(ph))
                    continue

                tr = (d.get("channel", {})
                       .get("alternatives", [{}])[0]
                       .get("transcript", "")
                       .strip())
                if not tr:
                    continue

                # Capture Deepgram confidence score
                conf = (d.get("channel", {})
                         .get("alternatives", [{}])[0]
                         .get("confidence"))
                if conf is not None and call_metrics:
                    call_metrics.deepgram_confidences.append(round(conf * 100, 1))

                # Drop very low-confidence transcripts — ambient noise, DTMF, line hiss
                if conf is not None and conf < 0.55:
                    print(f"⚡ [LOW-CONF] Dropped ({conf:.2f}): {tr!r}")
                    continue

                if not d.get("is_final", False):
                    partial_hyp = tr
                    print(f"\r〰  {tr}          ", end="", flush=True)
                    # Barge-in: real speech (≥2 words in interim) while Priya is speaking.
                    # Fan noise / ambient audio rarely produces ≥2 coherent words.
                    if (is_speaking and speak_task and not speak_task.done()
                            and len(tr.split()) >= 2):
                        print(f"\n🚫 [BARGE-IN] Interim transcript — cancelling bot speech")
                        if call_metrics:
                            call_metrics.record_interruption()
                        speak_task.cancel()
                        asyncio.create_task(clear_audio())
                else:
                    # Short finals (< 4 words) often mid-sentence — wait for UtteranceEnd
                    if len(tr.split()) >= 4:
                        partial_hyp = ""
                        asyncio.create_task(handle_transcript(tr))
                    else:
                        partial_hyp = tr   # hold; UtteranceEnd will flush
        except Exception:
            pass

    try:
        DG_URL = (
            "wss://api.deepgram.com/v1/listen"
            "?model=nova-3&language=hi&encoding=mulaw&sample_rate=8000"
            "&interim_results=true&utterance_end_ms=1500&vad_events=true"
            "&endpointing=500&smart_format=true&numerals=true"
        )
        dg_ws = await websockets.connect(
            DG_URL, additional_headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"}
        )
        asyncio.create_task(dg_receiver())
        asyncio.create_task(vobiz_keep_alive())

        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get("event") == "start":
                    sid = (data.get("streamSid") or data.get("streamId")
                           or data.get("start", {}).get("streamSid")
                           or data.get("start", {}).get("streamId"))
                    print(f"--- [SARVAM]: Started {sid} ---")
                    call_metrics = store.start_call(sid, "sarvam", caller_id)
                    poll_task    = asyncio.create_task(resource_poller(call_metrics))
                    asyncio.create_task(speak(APP_CONFIG["scripts"]["greeting"]))
                elif data.get("event") == "media" and sid and dg_ws:
                    raw = base64.b64decode(data["media"]["payload"])
                    await dg_ws.send(raw)
                    recorder.write_caller(audioop.ulaw2lin(raw, 2))  # caller → left channel

    except Exception:
        traceback.print_exc()
    finally:
        if poll_task:
            poll_task.cancel()
        # Give any in-flight TTS/speak task time to write its audio before saving
        if speak_task and not speak_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(speak_task), timeout=3.0)
            except Exception:
                pass
        if sid and call_metrics:
            cost = calculate_cost("sarvam", perf_counter() - call_metrics.call_start_perf,
                                  tts_chars=tts_chars)
            # Save full-call recording
            if recorder:
                try:
                    os.makedirs('recordings', exist_ok=True)
                    rec_name = f"{sid[:8]}_{int(time.time())}.wav"
                    recorder.save(f"recordings/{rec_name}")
                    call_metrics.recording_path = rec_name
                    print(f"🎙  Recording saved: {rec_name}")
                except Exception as re_:
                    print(f"[REC ERROR] {re_}")
            store.end_call(sid, cost.total_usd)
        # Send call transcript summary email
        try:
            duration = int(time.time() - call_start_time)
            transcript_lines = [
                f"{'Caller' if m['role'] == 'user' else 'Priya'}: {m['content']}"
                for m in history
                if m.get('role') in ('user', 'assistant') and m.get('content')
            ]
            if transcript_lines:
                summary = (f"Caller: {caller_id} | Duration: {duration}s "
                           f"| Turns: {len(transcript_lines)}")
                asyncio.create_task(asyncio.to_thread(
                    send_call_summary_email, summary, "\n".join(transcript_lines)
                ))
        except Exception:
            pass
        if dg_ws: await dg_ws.close()
        if not ws.closed: await ws.close()
    return ws


# ── Google Gemini pipeline handler ───────────────────────────────────────────

async def gemini_handler(request):
    caller_id = request.query.get("caller_id", "Unknown")
    ws        = web.WebSocketResponse(protocols=['audio.drachtio.org'])
    await ws.prepare(request)

    sid            = None
    call_metrics   = None
    poll_task      = None
    g_task         = None
    transcript_log = []
    start_time     = time.time()
    recorder       = _TimelineRecorder()  # full call timeline (caller + Priya)

    now            = datetime.now()
    date_str       = now.strftime("%A, %B %d, %Y (%I:%M %p)")
    greeting_text  = APP_CONFIG.get("scripts", {}).get(
        "greeting", "नमस्ते! नेहा चाइल्ड केयर में आपका स्वागत है। मैं प्रिया बोल रही हूँ।"
    )
    system_prompt  = (
        f"{APP_CONFIG['agent']['system_prompt']}\n\n"
        f"REAL-TIME: {date_str}. Caller: {caller_id}.\n\n"
        f"CALL START: When you receive [CALL_START], say this greeting EXACTLY and NOTHING ELSE:\n"
        f"'{greeting_text}'\n\n"
        "STRICT RULES:\n"
        "1. NO REPETITION: Never say the same sentence twice.\n"
        "2. NO PITY WORDS: No 'Bechara', 'Oh', 'poor thing'. One calm acknowledgement only.\n"
        "3. GREETING RULE: If caller says ONLY 'Hello'/'Hi'/'हेलो'/'हाँ'/'जी' → say 'जी, बताइए।' only.\n"
        "4. NEVER ASK FOR CONTACT NUMBER OR PHONE NUMBER. It is always captured automatically "
        "from the incoming call. The caller's number is already known.\n"
        "5. BOOKING FLOW (follow in order):\n"
        "   a) Extract child NAME and REASON from the conversation:\n"
        "      • Any health complaint (तबीयत ख़राब, बुखार, पेट दर्द, बॉडी पेन, etc.) = REASON captured.\n"
        "      • Any child name mentioned = NAME captured.\n"
        "      → If BOTH known: skip to step (b) IMMEDIATELY.\n"
        "      → If only REASON: ask ONLY 'बच्चे का नाम क्या है?'\n"
        "      → If only NAME: ask ONLY 'क्या तकलीफ है?'\n"
        "      → NEVER ask for something already mentioned in the conversation.\n"
        "   b) Call check_available_slots → if result has 'urgent_message', say it VERBATIM.\n"
        "      Otherwise offer ONE slot: 'क्या [day] को [time] ठीक रहेगा?'\n"
        "   c) User is confirmed when they say ANY of: हाँ / हां / yes / ठीक / ठीक है / ठीक रहेगा / "
        "ठीक बात है / theek / okay / ok / bilkul / sure / चलेगा / हो जाए / बुक कर दो / कर दो / "
        "ji haan / haan / जी हाँ / ठीक रहेगा / हाँ ठीक है.\n"
        "      → Book IMMEDIATELY on any of these — do NOT ask again.\n"
        "      → ONLY re-ask if user says no/नहीं/रुको/wait. Then offer the NEXT slot.\n"
        "   d) ONLY after confirmation → call book_appointment with confirmed day + time.\n"
        "   e) When book_appointment returns success, read the 'confirmation_message' field "
        "from the result VERBATIM — word for word. Do NOT paraphrase, do NOT add anything. "
        "Do NOT say ANY booking confirmation before calling the tool. "
        "If you say 'appointment book हो गया' without the tool call, the booking is FAKE "
        "and will NOT appear in the calendar.\n"
        "   f) After reading confirmation_message, STOP — do not ask for more information.\n"
        "6. CANCEL: Say cancel/रद्द → IMMEDIATELY call cancel_appointment. "
        "Contact number is already known — NEVER ask for it.\n"
        "7. TIME FORMAT: Always Hindi — 'सुबह के साढ़े ग्यारह बजे', never '11:30 AM'.\n"
        "8. CLINIC HOURS: Morning 10am–12pm, Evening 6pm–8pm only. Sunday closed.\n"
        "   After 12pm, offer evening slots only. If user asks for 2/3/4/5pm, explain hours "
        "and offer evening.\n"
        "9. ONE QUESTION at a time. Responses under 10 words."
    )

    try:
        async with websockets.connect(GEMINI_WS_URL) as gemini_ws:
            setup_msg = {
                "setup": {
                    "model": "models/gemini-3.1-flash-live-preview",
                    "generationConfig": {
                        "responseModalities": ["AUDIO"],
                        "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Aoede"}}}
                    },
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "tools": GEMINI_TOOLS,
                    "inputAudioTranscription":  {},
                    "outputAudioTranscription": {}
                }
            }
            await gemini_ws.send(json.dumps(setup_msg))
            setup_resp = await gemini_ws.recv()
            print(f"--- [GEMINI]: Setup: {setup_resp[:200]}")

            # Trigger Priya's greeting — neutral signal that won't match rule 3
            await gemini_ws.send(json.dumps({"realtimeInput": {"text": "[CALL_START]"}}))

            upsample_state   = None
            downsample_state = None
            state            = {"last_ai_audio": 0.0}

            async def from_vobiz():
                nonlocal sid, upsample_state
                try:
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            cur_id = (data.get("streamId") or data.get("streamSid")
                                      or (data.get("start", {}).get("streamId"))
                                      or (data.get("start", {}).get("streamSid")))
                            if cur_id and not sid:
                                sid = cur_id
                                print(f"--- [GEMINI]: Started {sid} ---")
                                nonlocal call_metrics, poll_task
                                call_metrics = store.start_call(sid, "google", caller_id)
                                poll_task    = asyncio.create_task(resource_poller(call_metrics))

                            if data.get("event") == "media" and sid:
                                payload = (data.get("media", {}).get("payload")
                                           or data.get("payload"))
                                if payload:
                                    mulaw = base64.b64decode(payload)
                                    pcm8  = audioop.ulaw2lin(mulaw, 2)
                                    recorder.write_caller(pcm8)  # caller → left channel
                                    if time.time() - state["last_ai_audio"] >= 1.0:
                                        pcm16, upsample_state = audioop.ratecv(
                                            pcm8, 2, 1, 8000, 16000, upsample_state
                                        )
                                        await gemini_ws.send(json.dumps({
                                            "realtimeInput": {
                                                "audio": {
                                                    "data": base64.b64encode(pcm16).decode("utf-8"),
                                                    "mimeType": "audio/pcm;rate=16000"
                                                }
                                            }
                                        }))
                        elif msg.type == aiohttp.WSMsgType.CLOSE:
                            break
                except Exception as e:
                    print(f"[GEMINI] from_vobiz error: {e}")

            _BOOKING_CONFIRM_KW = ("book कर दिया", "बुक कर दिया", "appointment मैंने", "appointment book")

            async def from_gemini():
                nonlocal downsample_state
                # Buffers: collect partial transcription fragments per turn
                priya_buf  = []
                caller_buf = []
                _turn_booked = False   # True if book_appointment tool call succeeded this turn

                def _flush_caller():
                    if not caller_buf:
                        return
                    combined = "".join(caller_buf).strip()
                    caller_buf.clear()
                    if combined:
                        print(f"\n[USER]: {combined}")
                        transcript_log.append(f"Caller: {combined}")
                        if call_metrics:
                            call_metrics.record_turn("user", combined)

                def _flush_priya():
                    if not priya_buf:
                        return
                    combined = "".join(priya_buf).strip()
                    priya_buf.clear()
                    if combined:
                        print(f"\n[PRIYA]: {combined}")
                        transcript_log.append(f"Priya: {combined}")
                        if call_metrics:
                            call_metrics.record_turn("assistant", combined)

                try:
                    async for raw in gemini_ws:
                        resp = json.loads(raw)

                        # User transcript — buffer fragments until model responds
                        transcription = (
                            resp.get("inputAudioTranscription")
                            or resp.get("serverContent", {}).get("inputTranscription")
                        )
                        if transcription and isinstance(transcription, dict):
                            t = transcription.get("text", "")
                            if t:
                                caller_buf.append(t)

                        # Priya transcript — flush caller first, then buffer Priya
                        out_transcription = (
                            resp.get("outputAudioTranscription")
                            or resp.get("serverContent", {}).get("outputTranscription")
                        )
                        if out_transcription and isinstance(out_transcription, dict):
                            t = out_transcription.get("text", "")
                            if t:
                                if caller_buf:
                                    _flush_caller()  # caller's turn is now complete
                                priya_buf.append(t)

                        # Audio output
                        sc = resp.get("serverContent")
                        if sc:
                            mt = sc.get("modelTurn")
                            if mt:
                                for part in mt.get("parts", []):
                                    if "inlineData" in part:
                                        state["last_ai_audio"] = time.time()
                                        pcm24 = base64.b64decode(part["inlineData"]["data"])
                                        pcm8, downsample_state = audioop.ratecv(
                                            pcm24, 2, 1, 24000, 8000, downsample_state
                                        )
                                        pcm8 = audioop.mul(pcm8, 2, 1.4)
                                        recorder.write_priya(pcm8)   # Priya → right channel
                                        mulaw = audioop.lin2ulaw(pcm8, 2)
                                        if sid and not ws.closed:
                                            print("🔊", end="", flush=True)
                                            await ws.send_str(json.dumps({
                                                "event": "playAudio", "streamId": sid,
                                                "media": {
                                                    "contentType": "audio/x-mulaw",
                                                    "sampleRate": 8000,
                                                    "payload": base64.b64encode(mulaw).decode("utf-8")
                                                }
                                            }))

                        # Flush transcript buffers when model turn is complete
                        if sc and sc.get("turnComplete"):
                            _flush_caller()   # any remaining caller fragments
                            _flush_priya()    # Priya's full sentence for this turn
                            # Hallucination guard: if Priya said booking words but tool was never called
                            priya_said = " ".join(
                                e[7:] for e in transcript_log if e.startswith("Priya: ")
                            ).lower()
                            if not _turn_booked and any(kw in priya_said for kw in _BOOKING_CONFIRM_KW):
                                print("⚠ [BOOKING HALLUCINATION] Priya said booking confirmation "
                                      "without calling book_appointment — calendar was NOT updated!")

                        # Tool calls
                        tool_call = resp.get("toolCall") or resp.get("tool_call")
                        if tool_call:
                            fn_calls      = tool_call.get("functionCalls") or tool_call.get("function_calls", [])
                            responses     = []
                            _turn_booked  = False   # reset for this batch of tool calls
                            for call in fn_calls:
                                name = call["name"]
                                args = call.get("args") or call.get("arguments") or {}
                                cid  = call.get("id") or call.get("call_id")

                                # Server-side confirmation guard for booking
                                if name == "book_appointment":
                                    last_user = next(
                                        (e[8:].lower() for e in reversed(transcript_log)
                                         if e.startswith("Caller: ")), ""
                                    )
                                    if not any(w in last_user for w in CONFIRMATION_WORDS):
                                        print(f"⚠ [BOOKING GUARD] No confirmation in last turn — blocking")
                                        responses.append({"name": name, "id": cid, "response": {
                                            "result": (
                                                "BLOCKED: User has not confirmed the slot yet. "
                                                "Ask: 'क्या यह समय ठीक रहेगा?' and wait for हाँ."
                                            )
                                        }})
                                        continue

                                # Auto-fill contact / parent for booking calls
                                if name in ("book_appointment", "cancel_appointment", "reschedule_appointment"):
                                    if not args.get("contact_number"):
                                        args["contact_number"] = caller_id
                                if name == "book_appointment":
                                    if not args.get("parent_name"):
                                        args["parent_name"] = args.get("patient_name", "Guardian")
                                    if not args.get("patient_age"):
                                        args["patient_age"] = "5"

                                print(f"\n🔧 [GEMINI] Tool: {name}({args})")
                                t_tool = time.time()
                                if fn := FUNCTION_MAP.get(name):
                                    try:
                                        result = fn(**args)
                                        tool_ms = int((time.time() - t_tool) * 1000)
                                        if call_metrics:
                                            call_metrics.record_tool_call(name, args, result, tool_ms)
                                        if name == "book_appointment" and isinstance(result, dict) and result.get("success"):
                                            _turn_booked = True
                                        responses.append({"name": name, "id": cid,
                                                          "response": {"result": result}})
                                    except Exception as te:
                                        print(f"[GEMINI] Tool error: {te}")
                                        responses.append({"name": name, "id": cid,
                                                          "response": {"error": str(te)}})

                            await gemini_ws.send(json.dumps(
                                {"toolResponse": {"functionResponses": responses}}
                            ))

                except Exception as e:
                    print(f"[GEMINI] from_gemini error: {e}")
                finally:
                    # Flush any remaining partial transcripts at call end
                    _flush_caller()
                    _flush_priya()

            v_task = asyncio.create_task(from_vobiz())
            g_task = asyncio.create_task(from_gemini())
            await asyncio.wait([v_task, g_task], return_when=asyncio.FIRST_COMPLETED)

    except Exception:
        traceback.print_exc()
    finally:
        if poll_task:
            poll_task.cancel()
        # Wait briefly for the Gemini audio coroutine to write its final chunks
        try:
            if g_task and not g_task.done():
                await asyncio.wait_for(asyncio.shield(g_task), timeout=2.0)
        except Exception:
            pass
        if sid and call_metrics:
            duration = time.time() - start_time
            cost = calculate_cost("google", duration)
            if recorder:
                try:
                    os.makedirs('recordings', exist_ok=True)
                    rec_name = f"{sid[:8]}_{int(time.time())}.wav"
                    recorder.save(f"recordings/{rec_name}")
                    call_metrics.recording_path = rec_name
                    print(f"🎙  Recording saved: {rec_name}")
                except Exception as re_:
                    print(f"[REC ERROR] {re_}")
            store.end_call(sid, cost.total_usd)
        duration = int(time.time() - start_time)
        if transcript_log:
            summary = f"Caller: {caller_id} | Duration: {duration}s | Turns: {len(transcript_log)}"
            full    = "\n".join(transcript_log)
            try:
                asyncio.create_task(asyncio.to_thread(
                    send_call_summary_email, summary, full
                ))
            except Exception:
                pass
        if not ws.closed:
            await ws.close()
    return ws


# ── HTTP / Dashboard routes ───────────────────────────────────────────────────

async def handle_answer(request):
    """Vobiz webhook — routes to the active pipeline's WebSocket."""
    host     = request.headers.get("X-Forwarded-Host") or request.host
    provider = APP_CONFIG.get("active_provider", "sarvam")
    path     = "/gemini-stream" if provider == "google" else "/sarvam-stream"

    try:
        body = await request.post()
        raw  = body.get("From") or body.get("CallerName") or "Unknown"
        cid  = str(raw).replace("+", "").strip()
        if "sip:" in cid:
            cid = cid.split("sip:")[1].split("@")[0]
    except Exception:
        cid = "Unknown"

    ws_url = f"wss://{host}{path}?caller_id={cid}"
    xml    = (f'<?xml version="1.0" encoding="UTF-8"?>'
              f'<Response><Stream bidirectional="true" keepCallAlive="true" '
              f'contentType="audio/x-mulaw;rate=8000">{ws_url}</Stream></Response>')
    print(f"[INCOMING] Provider={provider}  Caller={cid}")
    return web.Response(text=xml, content_type='text/xml')


async def home_page(request):
    provider = APP_CONFIG.get("active_provider", "sarvam")
    sa_active = "active" if provider == "sarvam" else ""
    goo_active = "active" if provider == "google" else ""
    sa_badge  = '<span class="badge">● ACTIVE</span>' if provider == "sarvam" else ""
    goo_badge = '<span class="badge">● ACTIVE</span>' if provider == "google" else ""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Priya — Voice Agent</title>
<style>
  *,*::before,*::after{{box-sizing:border-box}}
  body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
       background:#f0f2f5;margin:0;padding:32px;color:#1a1a1a}}
  h1{{margin:0 0 4px;font-size:1.8rem}}
  .sub{{color:#888;margin-bottom:28px;font-size:.9rem}}
  .card{{background:white;border-radius:14px;padding:24px;
         box-shadow:0 2px 10px rgba(0,0,0,.07);margin-bottom:20px}}
  .card h2{{margin:0 0 16px;font-size:1.1rem}}
  .grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
  .provider{{border:2px solid #ddd;border-radius:10px;padding:20px;
             cursor:pointer;transition:all .15s;background:#fafafa;text-align:left}}
  .provider:hover{{background:#f5f5f5}}
  .provider.active.sarvam{{border-color:#2e7d32;background:#f1f8f1}}
  .provider.active.google{{border-color:#1565c0;background:#f0f4ff}}
  .provider h3{{margin:0 0 4px;font-size:1rem}}
  .provider p{{margin:0;font-size:.78rem;color:#888;line-height:1.4}}
  .badge{{display:inline-block;margin-top:10px;padding:3px 10px;border-radius:20px;
          font-size:.7rem;font-weight:700;background:#2e7d32;color:white}}
  .provider.google .badge{{background:#1565c0}}
  .links{{display:flex;gap:12px;flex-wrap:wrap}}
  .btn{{padding:10px 22px;border-radius:8px;font-size:.9rem;text-decoration:none;
        display:inline-block;border:none;cursor:pointer}}
  .btn-primary{{background:#1a73e8;color:white}}
  .btn-outline{{background:white;color:#1a73e8;border:1px solid #1a73e8}}
  .status{{font-size:.82rem;color:#888;margin-top:12px;min-height:1.2em}}
</style>
</head>
<body>
<h1>Priya — Voice Agent</h1>
<p class="sub">Neha Child Care · AI Receptionist · Port {PORT}</p>

<div class="card">
  <h2>Active Pipeline</h2>
  <div class="grid">
    <div class="provider {sa_active} sarvam" onclick="switchProvider('sarvam')">
      <h3>Sarvam AI</h3>
      <p>Deepgram Nova-2 STT → Sarvam 30B LLM → Sarvam Bulbul v2 TTS</p>
      {sa_badge}
    </div>
    <div class="provider {goo_active} google" onclick="switchProvider('google')">
      <h3>Google Gemini</h3>
      <p>Gemini Multimodal Live — native end-to-end audio (lowest latency)</p>
      {goo_badge}
    </div>
  </div>
  <p class="status" id="status"></p>
</div>

<div class="card">
  <h2>Monitoring</h2>
  <div class="links">
    <a href="/metrics" class="btn btn-primary">Metrics Dashboard</a>
    <a href="/metrics/data" class="btn btn-outline">Raw JSON</a>
  </div>
</div>

<script>
async function switchProvider(p) {{
  document.getElementById('status').textContent = 'Switching to ' + p + '…';
  const r = await fetch('/api/set-provider', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{provider: p}})
  }});
  const d = await r.json();
  if (d.ok) {{ location.reload(); }}
  else {{ document.getElementById('status').textContent = 'Error: ' + (d.error || 'unknown'); }}
}}
</script>
</body>
</html>"""
    return web.Response(text=html, content_type='text/html')


async def set_provider(request):
    try:
        data     = await request.json()
        provider = data.get("provider", "").strip().lower()
    except Exception:
        return web.json_response({"ok": False, "error": "Invalid JSON"}, status=400)

    if provider not in ("sarvam", "google"):
        return web.json_response({"ok": False, "error": "Must be 'sarvam' or 'google'"}, status=400)

    APP_CONFIG["active_provider"] = provider
    try:
        with open('app_config.json', 'w', encoding='utf-8') as f:
            json.dump(APP_CONFIG, f, ensure_ascii=False, indent=4)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

    print(f"🔄 Provider switched → {provider}")
    return web.json_response({"ok": True, "provider": provider})


async def metrics_page(request):
    return web.Response(text=METRICS_DASHBOARD_HTML, content_type='text/html')


async def metrics_data(request):
    records = store.recent_calls(200)

    def _pct(data, p):
        vals = sorted(x for x in data if x is not None)
        if not vals:
            return None
        return round(vals[min(int(len(vals) * p / 100), len(vals) - 1)])

    def _avg(lst):
        clean = [x for x in lst if x is not None]
        return round(sum(clean) / len(clean), 2) if clean else None

    def _build(recs):
        if not recs:
            return {"call_count": 0}
        tl_all = [t for r in recs for t in r.get("turn_latencies", [])]
        recent = []
        for r in recs[-10:]:
            e2es = [t.get("e2e_ms") for t in r.get("turn_latencies", []) if t.get("e2e_ms")]
            recent.append({
                "ts":               r.get("call_start_wall"),
                "caller":           r.get("caller_id", "?"),
                "duration_s":       round(r.get("call_duration_s", 0)),
                "turns":            r.get("turn_count", 0),
                "booking":          r.get("booking_success", False),
                "cost_usd":         round(r.get("cost_usd") or 0, 4),
                "first_response_ms":round(r["first_response_ms"]) if r.get("first_response_ms") else None,
                "avg_e2e_ms":       round(_avg(e2es)) if e2es else None,
                "interrupts":       r.get("interruption_count", 0),
                "hallucinations":   r.get("hallucination_count", 0),
                "recording":        r.get("recording_path"),
                # Per-call detail for client-side checkbox filtering
                "turn_latencies":   r.get("turn_latencies", []),
                "dg_confidences":   r.get("deepgram_confidences", []),
            })
        bookings = [r for r in recs if r.get("booking_success")]
        costs    = [r.get("cost_usd") or 0 for r in recs if r.get("cost_usd")]
        confs    = [c for r in recs for c in r.get("deepgram_confidences", [])]
        n        = len(recs)
        return {
            "call_count":        n,
            "booking_count":     len(bookings),
            "booking_rate_pct":  round(100 * len(bookings) / n) if n else 0,
            "avg_duration_s":    _avg([r.get("call_duration_s", 0) for r in recs]),
            "avg_turns":         _avg([r.get("turn_count", 0) for r in recs]),
            "avg_interrupts":    _avg([r.get("interruption_count", 0) for r in recs]),
            "avg_hallucins":     _avg([r.get("hallucination_count", 0) for r in recs]),
            "avg_cost_usd":      _avg(costs),
            "cost_per_booking":  _avg([r.get("cost_usd") or 0 for r in bookings]),
            "avg_first_response_ms": _avg([r.get("first_response_ms") for r in recs]),
            "avg_dg_confidence": _avg(confs),
            "avg_cpu_pct":       _avg([r.get("avg_cpu_pct") for r in recs]),
            "peak_mem_mb":       _avg([r.get("peak_mem_rss_mb") for r in recs]),
            "latency": {
                k: {"p50": _pct([t.get(f"{k}_ms") for t in tl_all], 50),
                    "p95": _pct([t.get(f"{k}_ms") for t in tl_all], 95)}
                for k in ["stt", "llm", "tts", "e2e", "tool"]
            },
            "recent_calls": recent,
        }

    sarvam_recs = [r for r in records if r.get("provider") == "sarvam"]
    google_recs = [r for r in records if r.get("provider") == "google"]

    return web.json_response({
        "sarvam":      _build(sarvam_recs),
        "google":      _build(google_recs),
        "last_updated": time.time(),
        "total_calls": len(records),
    })


# ── App startup ───────────────────────────────────────────────────────────────

async def main():
    app = web.Application()
    app.router.add_get('/',               home_page)
    app.router.add_post('/answer',        handle_answer)
    app.router.add_post('/api/set-provider', set_provider)
    app.router.add_get('/sarvam-stream',  sarvam_handler)
    app.router.add_get('/gemini-stream',  gemini_handler)
    app.router.add_get('/metrics',        metrics_page)
    app.router.add_get('/metrics/data',   metrics_data)
    app.router.add_static('/recordings',  'recordings', show_index=True)

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

    provider = APP_CONFIG.get("active_provider", "sarvam")
    print(f"🚀 PRIYA ONLINE — PORT {PORT}")
    print(f"   Active pipeline : {provider.upper()}")
    print(f"   Dashboard       : http://localhost:{PORT}/")
    print(f"   Metrics         : http://localhost:{PORT}/metrics")
    await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
