# -*- coding: utf-8 -*-
"""
Sarvam pipeline WebSocket handler.

Call flow:
    Vobiz WS → Deepgram Nova-3 STT → Sarvam 30B LLM (streaming)
             → Sarvam Bulbul v2 TTS → Vobiz WS

System prompt and tool schemas are loaded from app_config.json at call-start
so they can be edited without redeploying code.
"""
import asyncio, audioop, base64, json, os, re, time, traceback, wave
from datetime import datetime
from time import perf_counter

import aiohttp
import websockets
from aiohttp import web

from config.settings import (
    APP_CONFIG, SARVAM_API_KEY, DEEPGRAM_API_KEY,
    SARVAM_CHAT_URL, SARVAM_TTS_URL, DG_URL,
)
from core.recorder import _TimelineRecorder
from core.hindi_utils import JUNK_RE, SENT_RE, day_to_hindi, time_to_hindi, hindi_to_time, _HI_DAY
from pipelines.http_client import get_http, reset_http
from pharmacy_functions import FUNCTION_MAP, send_call_summary_email, APPOINTMENTS_DB
from metrics.collector import store, resource_poller, TurnLatency
from metrics.cost_calculator import calculate_cost


# ── Sarvam API helpers ────────────────────────────────────────────────────────

async def _sarvam_tts(text: str) -> str | None:
    """Convert text to base64 PCM audio via Sarvam Bulbul v2. Returns None on failure."""
    if not text:
        return None
    payload = {
        "inputs": [text],
        "target_language_code": "hi-IN",
        "speaker": "anushka",
        "speech_sample_rate": 8000,
        "model": "bulbul:v2",
    }
    try:
        timeout = aiohttp.ClientTimeout(total=5, connect=2)
        async with get_http().post(
            SARVAM_TTS_URL, json=payload,
            headers={"api-subscription-key": SARVAM_API_KEY},
            timeout=timeout
        ) as r:
            if r.status != 200:
                print(f"❌ [TTS ERROR] Status {r.status}: {await r.text()}")
                return None
            res = await r.json()
            return res["audios"][0]
    except Exception as e:
        print(f"❌ [TTS EXCEPTION] {e}")
        return None


async def _sarvam_stream_once(messages: list):
    """
    Single streaming attempt against Sarvam 30B.
    Yields ("text", str) or ("tool", dict).
    Tool schemas are read from APP_CONFIG so they can be updated without code changes.
    """
    headers   = {"Content-Type": "application/json", "api-subscription-key": SARVAM_API_KEY}
    params    = APP_CONFIG.get("parameters", {}).get("sarvam", {})
    payload   = {
        "model": params.get("model", "sarvam-30b"),
        "messages": messages,
        "tools": APP_CONFIG["tools"]["sarvam"],
        "temperature": params.get("temperature", 0.1),
        "stream": True,
    }
    timeout   = aiohttp.ClientTimeout(total=8, sock_read=8)
    tool_bufs: dict = {}
    try:
        async with get_http().post(
            SARVAM_CHAT_URL, json=payload, headers=headers, timeout=timeout
        ) as r:
            # 1. Handle non-streaming fallback
            if "application/json" in r.headers.get("Content-Type", ""):
                data = await r.json()
                if "choices" in data:
                    msg = data["choices"][0]["message"]
                    if msg.get("content"):
                        yield "text", msg["content"]
                    for tc in msg.get("tool_calls", []):
                        yield "tool", tc.get("function", tc)
                return

            # 2. Handle SSE stream
            async for line_b in r.content:
                line = line_b.decode("utf-8").strip()
                if not line or not line.startswith("data:"):
                    continue
                
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                
                try:
                    data = json.loads(payload)
                    if not data.get("choices"): continue
                    
                    delta = data["choices"][0].get("delta", {})
                    
                    # A. Handle Text
                    if "content" in delta and delta["content"]:
                        yield "text", delta["content"]
                    
                    # B. Handle Tool Call Chunks
                    if "tool_calls" in delta:
                        for tc in delta["tool_calls"]:
                            idx = tc.get("index", 0)
                            if idx not in tool_bufs:
                                tool_bufs[idx] = {"name": "", "arguments": ""}
                            
                            fn = tc.get("function", {})
                            if fn.get("name"):
                                tool_bufs[idx]["name"] += fn["name"]
                            if fn.get("arguments"):
                                tool_bufs[idx]["arguments"] += fn["arguments"]
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"❌ [SARVAM ERROR] stream_once: {e}")
        reset_http()
    
    # 3. Yield buffered tools
    for idx in sorted(tool_bufs.keys()):
        yield "tool", tool_bufs[idx]


async def _sarvam_stream(messages: list):
    """Streaming with one automatic retry on empty response."""
    had_output = False
    async for kind, val in _sarvam_stream_once(messages):
        had_output = True
        yield kind, val
    if not had_output:
        print("[SARVAM RETRY] Empty response — retrying once")
        async for kind, val in _sarvam_stream_once(messages):
            yield kind, val


# ── Main handler ──────────────────────────────────────────────────────────────

async def sarvam_handler(request):
    ws        = web.WebSocketResponse(protocols=["audio.drachtio.org"])
    await ws.prepare(request)
    caller_id = request.query.get("caller_id", "Unknown")
    sid, dg_ws = None, None

    # ── Per-call state ─────────────────────────────────────────────────────
    is_responding      = False
    is_speaking        = False
    speak_task         = None
    worker_task        = None
    speak_queue        = asyncio.Queue()
    partial_hyp        = ""
    pending_transcript = None   # last utterance queued while bot was busy
    call_metrics       = None
    poll_task          = None
    tts_chars          = 0
    recorder           = _TimelineRecorder()
    call_start_time    = time.time()

    # ── Build system prompt from config ────────────────────────────────────
    now       = datetime.now()
    _existing = [
        appt for appt in APPOINTMENTS_DB["appointments"].values()
        if str(appt.get("contact_number", "")) == str(caller_id)
    ]
    caller_ctx = ""
    if _existing:
        booking_strs = ", ".join(
            f"{a['patient_name']} on {a['preferred_day']} at {a['preferred_time']}"
            for a in _existing
        )
        ctx_tmpl = APP_CONFIG["prompts"].get(
            "caller_context",
            "CALLER CONTEXT: This caller has an existing appointment: {bookings}."
        )
        caller_ctx = "\n\n" + ctx_tmpl.format(bookings=booking_strs)

    # ── Load Knowledge Base ────────────────────────────────────────────────
    kb_content = ""
    kb_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "knowledge_base")
    if os.path.exists(kb_dir):
        for f in os.listdir(kb_dir):
            if f.endswith(".extracted.txt"):
                try:
                    with open(os.path.join(kb_dir, f), "r", encoding="utf-8") as kb_file:
                        kb_content += f"\n--- DOCUMENT: {f.replace('.extracted.txt', '')} ---\n"
                        kb_content += kb_file.read() + "\n"
                except Exception:
                    pass
    
    kb_prompt = ""
    if kb_content:
        kb_prompt = f"\n\nKNOWLEDGE BASE (Use this to answer questions accurately):\n{kb_content}"

    system_instructions = (
        f"{APP_CONFIG['agent']['system_prompt']}\n\n"
        f"REAL-TIME: {now.strftime('%I:%M %p')} on {now.strftime('%A')}."
        f"{caller_ctx}\n\n"
        f"{kb_prompt}\n\n"
        f"{APP_CONFIG['prompts']['sarvam_rules']}"
    )
    history = [{"role": "system", "content": system_instructions}]

    # ── Inner helpers ───────────────────────────────────────────────────────

    _GREETING_WORDS = frozenset({
        "hello", "hi", "हेलो", "हाय", "namaste", "नमस्ते", "hey",
        "hello?", "hi?", "हेलो?", "हाय?",
    })

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
        t   = re.sub(r"<[^>]+>", "", t).strip()
        t   = JUNK_RE.sub("", t)
        t   = re.sub(r"\s+", " ", t).strip()
        if not t or len(t) < 2:
            print(f"[SPEAK] stripped to empty — raw: {raw!r}")
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
                if pcm.startswith(b"RIFF"):
                    try:
                        import io as _io
                        with wave.open(_io.BytesIO(pcm), "rb") as _wf:
                            pcm = _wf.readframes(_wf.getnframes())
                    except Exception:
                        pcm = pcm[44:]
                # Record BEFORE sending — captures last chunk even if WS closes
                recorder.write_priya(pcm)
                if not ws.closed:
                    mulaw = audioop.lin2ulaw(pcm, 2)
                    await ws.send_str(json.dumps({
                        "event": "playAudio", "streamId": sid,
                        "media": {
                            "contentType": "audio/x-mulaw",
                            "sampleRate": 8000,
                            "payload": base64.b64encode(mulaw).decode("utf-8"),
                        },
                    }))
                    await asyncio.sleep(len(mulaw) / 8000.0)
            finally:
                is_speaking = False

    async def speak_worker():
        nonlocal speak_task
        try:
            while True:
                t = await speak_queue.get()
                if t is None:
                    break
                # Each sentence gets its own task so it can be cancelled
                speak_task = asyncio.create_task(speak(t))
                await speak_task
                speak_queue.task_done()
        except asyncio.CancelledError:
            pass

    async def handle_transcript(transcript: str):
        nonlocal is_responding, speak_task, worker_task, pending_transcript, history, speak_queue

        if is_responding:
            pending_transcript = transcript
            print(f"💾 [QUEUED]: {transcript}")
            return

        tr_lower = transcript.strip().lower().rstrip(".")
        if tr_lower in _GREETING_WORDS:
            print(f"👤 User (greeting): {transcript}")
            await speak("जी, बताइए।")
            return

        pending_transcript = None
        is_responding      = True
        t_start = time.time()
        turn_llm_ms = turn_tts_ms = turn_tool_ms = None

        try:
            print(f"👤 User: {transcript}")
            history.append({"role": "user", "content": transcript})
        
        # Keep history manageable (System prompt + last 20 turns)
        if len(history) > 21:
            history = [history[0]] + history[-20:]
            if call_metrics:
                call_metrics.record_turn("user", transcript)

            if len(history) > 24:
                history[1:] = history[-23:]

            t_llm      = time.time()
            full_text  = ""
            tool_calls = []
            sent_buf   = ""

            # Tokens that indicate the LLM is hallucinating a tool call as text
            _HALLUC_TOKENS = frozenset({
                "arg_key", "arg_value", "book_appointment", "check_available_slots",
                "cancel_appointment", "reschedule_appointment",
                "patient_name", "preferred_time", "preferred_day",
            })

            async def flush_sent(s: str):
                s = s.strip()
                if not s:
                    return
                # Block sentences that are clearly tool-call artifacts leaking into TTS
                # We catch both underscore and space versions (e.g. 'preferred_day' and 'preferred day')
                _halluc_lower = s.lower()
                if any(t in _halluc_lower for t in _HALLUC_TOKENS) or \
                   any(t.replace("_", " ") in _halluc_lower for t in _HALLUC_TOKENS):
                    print(f"[SPEAK BLOCKED] Tool artifact: {s[:60]!r}")
                    return
                # Queue the sentence for the worker
                await speak_queue.put(s)
            
            # Start a fresh worker for this turn if needed
            if worker_task is None or worker_task.done():
                while not speak_queue.empty():
                    try: speak_queue.get_nowait()
                    except: break
                worker_task = asyncio.create_task(speak_worker())

            async for kind, val in _sarvam_stream(history):
                # ── BARGE-IN CHECK ──
                # If the user started speaking while LLM was thinking, abort immediately
                if not is_responding:
                    print("🛑 [LLM ABORT] User interrupted thinking")
                    return

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
                print(f"⚠  [LLM EMPTY] No output after {turn_llm_ms}ms")
                await flush_sent("जी, बताइए।")
                return

            # ── Hallucination guard ─────────────────────────────────────────
            if full_text and not tool_calls:
                hall_triggers = {"patient_name", "preferred_day", "preferred_time", "arg_key"}
                if any(k in full_text.lower() for k in hall_triggers):
                    print(f"⚠ [HALLUC] Detected: {full_text[:80]}")
                    if call_metrics:
                        call_metrics.record_hallucination()
                    fn_match = re.search(
                        r"\b(book_appointment|check_available_slots|cancel_appointment|reschedule_appointment)\b",
                        full_text,
                    )
                    fn_name = fn_match.group(1) if fn_match else None
                    xml_pairs = re.findall(
                        r"<arg_key>\s*(\w+)\s*</arg_key>\s*<arg_value>\s*(.*?)\s*</arg_value>",
                        full_text, re.DOTALL,
                    )
                    # ── XML path: Sarvam sometimes outputs tool calls as XML ──
                    if xml_pairs and fn_name:
                        args_dict = {k: v.strip() for k, v in xml_pairs}
                        tool_calls = [{"id": "halluc_xml", "type": "function",
                                       "function": {"name": fn_name,
                                                    "arguments": json.dumps(args_dict, ensure_ascii=False)}}]
                        print(f"[HALLUC→TOOL] XML converted: {fn_name}({args_dict})")
                    # ── JSON path: raw JSON object in output ─────────────────
                    elif not xml_pairs and ("{" in full_text and "}" in full_text):
                        try:
                            json_body = full_text[full_text.find("{"):full_text.rfind("}")+1]
                            extracted = json.loads(json_body)
                            if extracted and fn_name:
                                tool_calls = [{"id": "halluc_json", "type": "function",
                                               "function": {"name": fn_name, "arguments": json_body}}]
                        except Exception:
                            pass
                    full_text = ""

            asst: dict = {"role": "assistant", "content": full_text or None}
            if tool_calls:
                asst["tool_calls"] = [
                    {"id": tc.get("id", f"tc_{i}"), "type": "function", "function": tc["function"]}
                    for i, tc in enumerate(tool_calls)
                ]
            history.append(asst)
            if call_metrics and full_text:
                call_metrics.record_turn("assistant", full_text)

            # ── Execute tool calls ──────────────────────────────────────────
            if tool_calls:
                booking_confirmed = False
                booking_args      = {}
                slots_res         = None

                for i, tc in enumerate(tool_calls):
                    fn   = tc["function"]["name"]
                    args = json.loads(tc["function"]["arguments"])
                    if fn == "book_appointment":
                        if not args.get("preferred_day"):  args["preferred_day"]  = "Today"
                        if not args.get("reason"):         args["reason"]         = "General Checkup"
                        args.update({"patient_age": "5", "parent_name": "Guardian",
                                     "contact_number": caller_id})
                        # ── Time: normalise Hindi → English then scan history ─
                        # LLM sometimes passes time in Hindi ('सुबह के साढ़े दस बजे')
                        # which breaks _normalize_time and skips the conflict check.
                        # 1. Try converting the LLM's own Hindi value first.
                        # 2. Then scan full user history for the last spoken time.
                        pt = args.get("preferred_time", "")
                        _is_english_time = bool(re.match(r"^\d{1,2}:\d{2}\s*(AM|PM)$", pt.strip(), re.IGNORECASE))
                        if not _is_english_time:
                            # Scan all user turns in history for confirmed time
                            _full_user_text = " ".join(
                                m["content"] for m in history
                                if m.get("role") == "user" and m.get("content")
                            ) + " " + transcript
                            _spoken_time = (hindi_to_time(pt) or
                                            hindi_to_time(transcript) or
                                            hindi_to_time(_full_user_text))
                            if _spoken_time:
                                print(f"[TIME NORMALIZE] Hindi→English: {pt!r} → {_spoken_time!r}")
                                args["preferred_time"] = _spoken_time
                            else:
                                args["preferred_time"] = "06:00 PM"  # safe default
                        else:
                            # English format: still check recent history for user correction
                            _recent_text = " ".join(
                                m["content"] for m in history[-8:]
                                if m.get("role") == "user" and m.get("content")
                            ) + " " + transcript
                            _spoken_time = hindi_to_time(transcript) or hindi_to_time(_recent_text)
                            if _spoken_time and _spoken_time != pt:
                                print(f"[TIME OVERRIDE] LLM={pt!r} → spoke={_spoken_time!r}")
                                args["preferred_time"] = _spoken_time
                        # ── Day override for booking too ─────────────────────
                        _recent_user = " ".join(
                            m["content"] for m in history[-8:]
                            if m.get("role") == "user" and m.get("content")
                        ).lower()
                        if args.get("preferred_day") in ("Today", "today") or not args.get("preferred_day"):
                            if any(w in _recent_user for w in ["परसों", "parson"]):
                                args["preferred_day"] = "Day after tomorrow"
                            elif any(w in _recent_user for w in ["कल", "kal", "tomorrow"]):
                                args["preferred_day"] = "Tomorrow"
                                print(f"[DAY OVERRIDE] booking → Tomorrow")
                    elif fn in ("cancel_appointment", "reschedule_appointment"):
                        if not args.get("contact_number"):
                            args["contact_number"] = caller_id
                        if fn == "reschedule_appointment":
                            _recent_text = " ".join(
                                m["content"] for m in history[-5:]
                                if m.get("role") == "user" and m.get("content")
                            ) + " " + transcript
                            _spoken_time = hindi_to_time(transcript) or hindi_to_time(_recent_text)
                            if _spoken_time and _spoken_time != args.get("new_time"):
                                print(f"[TIME OVERRIDE] reschedule LLM={args.get('new_time')!r} → spoke={_spoken_time!r}")
                                args["new_time"] = _spoken_time

                    # ── Day override: if user mentioned কল/tomorrow in recent msgs ──
                    if fn == "check_available_slots":
                        recent_user = " ".join(
                            m["content"] for m in history[-8:]
                            if m.get("role") == "user" and m.get("content")
                        ).lower()
                        if any(w in recent_user for w in ["परसों", "parson", "day after tomorrow"]):
                            args["preferred_day"] = "Day after tomorrow"
                            print(f"[DAY OVERRIDE] User said परसों → Day after tomorrow")
                        elif any(w in recent_user for w in ["कल", "kal", "tomorrow"]):
                            args["preferred_day"] = "Tomorrow"
                            print(f"[DAY OVERRIDE] User said कल → Tomorrow")
                        if not args.get("preferred_day"):
                            args["preferred_day"] = "Today"

                    print(f"🔧 Tool: {fn}({args})")
                    t_tool = time.time()
                    # Start tool call immediately so it runs concurrently with any remaining TTS
                    _tool_task = asyncio.create_task(asyncio.to_thread(FUNCTION_MAP[fn], **args))
                    if speak_task and not speak_task.done():
                        await speak_task
                    
                    try:
                        res = await _tool_task
                        if not is_responding:
                            print(f"🛑 [TOOL ABORT] Interrupted during {fn}")
                            return
                    except Exception as te:
                        print(f"❌ [TOOL EXCEPTION] {fn}: {te}")
                        res = {"error": "failed"}
                    
                    turn_tool_ms = int((time.time() - t_tool) * 1000)
                    if call_metrics:
                        call_metrics.record_tool_call(fn, args, res, turn_tool_ms)

                    # ── Clear stale queue after any mutating action succeeds ──
                    # A queued correction that was pending while this tool ran
                    # is now obsolete — replaying it would double-cancel/rebook.
                    if (fn in ("book_appointment", "reschedule_appointment", "cancel_appointment")
                            and isinstance(res, dict) and res.get("success")):
                        if pending_transcript:
                            print(f"🗑  [QUEUE CLEARED] Discarding stale: {pending_transcript!r}")
                        pending_transcript = None

                    if fn == "check_available_slots" and isinstance(res, dict):
                        slots_res = res
                        hi_res = dict(res)
                        if hi_res.get("available_slots"):
                            hi_res["available_slots"] = [
                                {"time_en": s, "time_hi": time_to_hindi(s)}
                                for s in hi_res["available_slots"]
                            ]
                        llm_content = json.dumps(hi_res, ensure_ascii=False)
                    else:
                        llm_content = json.dumps(res)

                    history.append({"role": "tool",
                                    "tool_call_id": tc.get("id", f"tc_{i}"),
                                    "name": fn, "content": llm_content})

                    if fn == "book_appointment" and isinstance(res, dict) and res.get("success"):
                        booking_confirmed = True
                        booking_args      = args

                # ── Booking confirmed: scripted reply, skip LLM round-trip ──
                if booking_confirmed:
                    tmpl = APP_CONFIG.get("scripts", {}).get(
                        "booking_confirmation",
                        "{day} {time} बजे {patient_name} का appointment मैंने book कर दिया है। "
                        "आप please 15 minutes पहले आ जाइए।",
                    )
                    confirmation = tmpl.format(
                        day=day_to_hindi(booking_args.get("preferred_day", "")),
                        time=time_to_hindi(booking_args.get("preferred_time", "")),
                        patient_name=booking_args.get("patient_name", ""),
                    )
                    await flush_sent(confirmation)
                    history.append({"role": "assistant", "content": confirmation})
                    if call_metrics:
                        call_metrics.record_turn("assistant", confirmation)

                # ── Slot check: build offer directly, no second LLM call ────
                elif slots_res is not None:
                    if slots_res.get("urgent_message"):
                        slot_reply = slots_res["urgent_message"]
                    elif slots_res.get("available_slots"):
                        best_slot    = slots_res["available_slots"][0]
                        booked_slots = slots_res.get("booked_slots", [])

                        # Parse user's time preference from recent messages
                        recent_user_text = " ".join(
                            m["content"] for m in history[-6:]
                            if m.get("role") == "user" and m.get("content")
                        ) + " " + transcript
                        user_time = hindi_to_time(recent_user_text)

                        # Check if user's preferred time is already booked
                        preferred_was_booked = False
                        booked_time_hi = ""
                        if user_time:
                            try:
                                user_dt = datetime.strptime(user_time, "%I:%M %p")
                                for bk in booked_slots:
                                    bk_dt = datetime.strptime(bk, "%I:%M %p")
                                    if abs((user_dt - bk_dt).total_seconds()) < 600:
                                        preferred_was_booked = True
                                        booked_time_hi = time_to_hindi(bk)
                                        break
                            except Exception:
                                pass

                        # Try to match user's preferred time to an available slot
                        user_pref_lower = recent_user_text.lower()
                        for s in slots_res["available_slots"]:
                            if any(x in user_pref_lower for x in [s.split(":")[0].lstrip("0"), time_to_hindi(s)]):
                                best_slot = s
                                break

                        first_hi  = time_to_hindi(best_slot)
                        day_label = day_to_hindi(slots_res.get("day", "Today"))

                        if preferred_was_booked and booked_time_hi:
                            slot_reply = (
                                f"{booked_time_hi} की appointment पहले से book है। "
                                f"{first_hi} में doctor free हैं। "
                                f"क्या मैं {first_hi} का appointment book कर दूँ?"
                            )
                        else:
                            slot_reply = f"जी, {day_label} {first_hi} का slot है — ठीक रहेगा?"
                    else:
                        tmr = await asyncio.to_thread(
                            FUNCTION_MAP["check_available_slots"], preferred_day="Tomorrow"
                        )
                        if tmr.get("available_slots"):
                            first_hi   = time_to_hindi(tmr["available_slots"][0])
                            tmr_day_hi = _HI_DAY.get(tmr.get("day", "Tomorrow"), "कल")
                            slot_reply = f"आज appointment नहीं है। क्या {tmr_day_hi} {first_hi} का समय ठीक रहेगा?"
                            hi_tmr = dict(tmr)
                            hi_tmr["available_slots"] = [
                                {"time_en": s, "time_hi": time_to_hindi(s)}
                                for s in hi_tmr["available_slots"]
                            ]
                            history[-1]["content"] = json.dumps(hi_tmr, ensure_ascii=False)
                        else:
                            slot_reply = "आज और कल कोई slot नहीं है। किसी और दिन के लिए बताएं?"
                    print(f"[SLOTS] Direct reply: {slot_reply!r}")
                    await flush_sent(slot_reply)
                    history.append({"role": "assistant", "content": slot_reply})
                    if call_metrics:
                        call_metrics.record_turn("assistant", slot_reply)

                # ── Other tools (cancel, reschedule): LLM follow-up ─────────
                else:
                    followup       = ""
                    f_buf          = ""
                    t_tts          = time.time()
                    spoke_any      = False
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
                    print(f"[FOLLOWUP] spoke={spoke_any} text={followup[:80]!r} "
                          f"tools={[t['function']['name'] for t in followup_tools]}")

                    asst_followup: dict = {"role": "assistant", "content": followup or None}
                    if followup_tools:
                        asst_followup["tool_calls"] = [
                            {"id": ftc.get("id", f"ft_{j}"), "type": "function",
                             "function": ftc["function"]}
                            for j, ftc in enumerate(followup_tools)
                        ]
                    history.append(asst_followup)
                    if call_metrics and followup:
                        call_metrics.record_turn("assistant", followup)

                    # ── Fallback: no speech produced after tool ───────────────
                    if not spoke_any:
                        last_res = json.loads(history[-2]["content"]) if len(history) >= 2 else {}
                        last_fn = tool_calls[-1]["function"]["name"] if tool_calls else ""
                        if last_fn == "check_available_slots":
                            if last_res.get("urgent_message"):
                                fb = last_res["urgent_message"]
                            elif last_res.get("available_slots"):
                                fb = f"क्या आज {time_to_hindi(last_res['available_slots'][0])} का समय ठीक रहेगा?"
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
                    llm_ms=turn_llm_ms, tts_ms=turn_tts_ms,
                    tool_ms=turn_tool_ms, e2e_ms=e2e_ms,
                ))
                call_metrics._current_turn_index += 1

        except asyncio.CancelledError:
            print("🚫 [BARGE-IN] Response cancelled — user spoke")
        finally:
            is_responding = False
            if pending_transcript:
                pt, pending_transcript = pending_transcript, None
                print(f"▶️  [REPLAY]: {pt}")
                asyncio.create_task(handle_transcript(pt))

    # ── Keep-alive: Vobiz silence + Deepgram KeepAlive ───────────────────

    _DG_KEEPALIVE = json.dumps({"type": "KeepAlive"})

    async def vobiz_keep_alive():
        """Send silence to Vobiz every 0.8 s to prevent RTP timeout."""
        silence_mulaw = audioop.lin2ulaw(b"\x00" * 160, 2)
        silence_b64   = base64.b64encode(silence_mulaw).decode("utf-8")
        while not ws.closed:
            if sid:
                try:
                    await ws.send_str(json.dumps({
                        "event": "playAudio", "streamId": sid,
                        "media": {"contentType": "audio/x-mulaw", "sampleRate": 8000, "payload": silence_b64},
                    }))
                except Exception:
                    pass
            await asyncio.sleep(0.8)

    async def dg_keep_alive():
        """Send Deepgram KeepAlive text frame every 5 s.
        Runs from the moment dg_ws connects — independent of Vobiz sid.
        Deepgram disconnects after ~10 s of no data (error 1011 net0001).
        """
        while not ws.closed:
            if dg_ws:
                try:
                    await dg_ws.send(_DG_KEEPALIVE)
                except Exception:
                    break
            await asyncio.sleep(5)

    # ── Deepgram receiver ─────────────────────────────────────────────────

    async def dg_receiver():
        nonlocal partial_hyp, speak_task, is_responding
        try:
            async for raw in dg_ws:
                d        = json.loads(raw)
                msg_type = d.get("type", "")

                if msg_type == "SpeechStarted":
                    print("🎤 [VAD] Speech started")
                    continue

                if msg_type == "UtteranceEnd":
                    print("🔇 [VAD] Utterance end")
                    ph = partial_hyp.strip()
                    partial_hyp = ""
                    if ph:
                        asyncio.create_task(handle_transcript(ph))
                    continue

                tr = (d.get("channel", {})
                       .get("alternatives", [{}])[0]
                       .get("transcript", "")
                       .strip())
                if not tr:
                    continue

                conf = (d.get("channel", {})
                         .get("alternatives", [{}])[0]
                         .get("confidence"))
                if conf is not None and call_metrics:
                    call_metrics.deepgram_confidences.append(round(conf * 100, 1))
                
                # REJECT noise: Fan noise usually has low confidence.
                if conf is not None and conf < 0.4:
                    if len(tr.split()) < 2:
                        continue # ignore low-conf single-word noise
                
                # REJECT junk: 'हूँ', 'अह', 'जी?' as single words shouldn't interrupt
                if len(tr.split()) == 1 and JUNK_RE.match(tr):
                    continue

                is_final = d.get("is_final", False)
                if not is_final:
                    partial_hyp = tr
                    print(f"\r〰  {tr}          ", end="", flush=True)
                else:
                    partial_hyp = ""

                # ── BARGE-IN CHECK ──
                # If user speaks even 1 word while bot is thinking or talking, abort immediately.
                if (is_speaking or is_responding) and len(tr.split()) >= 1:
                    print(f"\n🚫 [BARGE-IN] User detected: {tr!r}")
                    is_responding = False # Stops current LLM turn
                    if call_metrics:
                        call_metrics.record_interruption()
                    
                    # Stop both the queue worker and the current active audio
                    if worker_task and not worker_task.done():
                        worker_task.cancel()
                    if speak_task and not speak_task.done():
                        speak_task.cancel()
                    
                    # Clear the queue
                    while not speak_queue.empty():
                        try: speak_queue.get_nowait()
                        except: break
                            
                    asyncio.create_task(clear_audio())

                # ── FINAL TRANSCRIPT HANDLING ──
                if is_final:
                    if len(tr.split()) >= 1:
                        asyncio.create_task(handle_transcript(tr))
                    else:
                        # Empty final transcript: could be silence after SpeechStarted
                        pass
        except Exception as e:
            print(f"❌ [DEEPGRAM ERROR] Receiver died: {e}")
            traceback.print_exc()

    # ── Main WebSocket loop ────────────────────────────────────────────────

    try:
        dg_ws = await websockets.connect(
            DG_URL,
            additional_headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"},
            ping_interval=20,
            ping_timeout=20
        )
        asyncio.create_task(dg_receiver())
        asyncio.create_task(dg_keep_alive())
        asyncio.create_task(vobiz_keep_alive())

        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get("event") == "start":
                    sid = (data.get("streamSid") or data.get("streamId")
                           or data.get("start", {}).get("streamSid")
                           or data.get("start", {}).get("streamId"))
                    print(f"🚀 [SESSION START] SID: {sid}")
                    call_metrics = store.start_call(sid, "sarvam", caller_id)
                    poll_task    = asyncio.create_task(resource_poller(call_metrics))
                    
                    async def do_greeting():
                        nonlocal is_responding, speak_task, pending_transcript
                        is_responding = True
                        try:
                            # Assign to speak_task so barge-in can cancel it
                            speak_task = asyncio.create_task(speak(APP_CONFIG["scripts"]["greeting"]))
                            await speak_task
                        except asyncio.CancelledError:
                            print("🚫 [BARGE-IN] Greeting cancelled")
                        finally:
                            is_responding = False
                            if pending_transcript:
                                pt, pending_transcript = pending_transcript, None
                                print(f"▶️  [REPLAY GREETING INTERRUPT]: {pt}")
                                asyncio.create_task(handle_transcript(pt))

                    asyncio.create_task(do_greeting())
                elif data.get("event") == "media" and sid and dg_ws:
                    try:
                        raw = base64.b64decode(data["media"]["payload"])
                        if not dg_ws.closed:
                            await dg_ws.send(raw)
                        recorder.write_caller(audioop.ulaw2lin(raw, 2))
                    except Exception as e:
                        print(f"⚠️ [DG SEND ERROR]: {e}")
                        break # Exit main loop to disconnect call gracefully if STT fails

    except Exception as e:
        print(f"❌ [HANDLER CRASH] {e}")
        traceback.print_exc()
    finally:
        if poll_task:
            poll_task.cancel()
        # Wait for in-flight TTS to finish writing before saving the recording
        if speak_task and not speak_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(speak_task), timeout=3.0)
            except Exception:
                pass
        if sid and call_metrics:
            print(f"--- [SARVAM]: Finished {sid} | WS Closed: {ws.closed} ---")
            cost = calculate_cost(
                "sarvam",
                perf_counter() - call_metrics.call_start_perf,
                tts_chars=tts_chars,
            )
            if recorder:
                try:
                    os.makedirs("recordings", exist_ok=True)
                    rec_name = f"{sid[:8]}_{int(time.time())}.wav"
                    recorder.save(f"recordings/{rec_name}")
                    call_metrics.recording_path = rec_name
                    print(f"🎙  Recording saved: {rec_name}")
                except Exception as exc:
                    print(f"[REC ERROR] {exc}")
            store.end_call(sid, cost.total_usd)
        try:
            duration = int(time.time() - call_start_time)
            transcript_lines = [
                f"{'Caller' if m['role'] == 'user' else 'Priya'}: {m['content']}"
                for m in history
                if m.get("role") in ("user", "assistant") and m.get("content")
            ]
            if transcript_lines:
                summary = (f"Caller: {caller_id} | Duration: {duration}s "
                           f"| Turns: {len(transcript_lines)}")
                asyncio.create_task(asyncio.to_thread(
                    send_call_summary_email, summary, "\n".join(transcript_lines)
                ))
        except Exception:
            pass
        if dg_ws:
            await dg_ws.close()
        if not ws.closed:
            await ws.close()
    return ws
