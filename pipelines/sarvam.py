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
from core.hindi_utils import JUNK_RE, SENT_RE, day_to_hindi, time_to_hindi, _HI_DAY
from pipelines.http_client import get_http
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
        async with get_http().post(
            SARVAM_TTS_URL, json=payload,
            headers={"api-subscription-key": SARVAM_API_KEY},
        ) as r:
            return (await r.json())["audios"][0] if r.status == 200 else None
    except Exception:
        return None


async def _sarvam_stream_once(messages: list):
    """
    Single streaming attempt against Sarvam 30B.
    Yields ("text", str) or ("tool", dict).
    Tool schemas are read from APP_CONFIG so they can be updated without code changes.
    """
    headers   = {"Content-Type": "application/json", "api-subscription-key": SARVAM_API_KEY}
    payload   = {
        "model": "sarvam-30b",
        "messages": messages,
        "tools": APP_CONFIG["tools"]["sarvam"],
        "temperature": 0.1,
        "stream": True,
    }
    timeout   = aiohttp.ClientTimeout(total=12)
    tool_bufs: dict = {}
    try:
        async with get_http().post(
            SARVAM_CHAT_URL, json=payload, headers=headers, timeout=timeout
        ) as r:
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
                "function": {"name": buf["name"], "arguments": buf["arguments"]},
            })


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
        caller_ctx = "\n\n" + APP_CONFIG["prompts"]["caller_context"].format(
            bookings=booking_strs
        )

    system_instructions = (
        f"{APP_CONFIG['agent']['system_prompt']}\n\n"
        f"REAL-TIME: {now.strftime('%I:%M %p')} on {now.strftime('%A')}."
        f"{caller_ctx}\n\n"
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

    async def handle_transcript(transcript: str):
        nonlocal is_responding, speak_task, pending_transcript

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
            if call_metrics:
                call_metrics.record_turn("user", transcript)

            if len(history) > 24:
                history[1:] = history[-23:]

            t_llm      = time.time()
            full_text  = ""
            tool_calls = []
            sent_buf   = ""

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
                print(f"⚠  [LLM EMPTY] No output after {turn_llm_ms}ms")

            # ── Hallucination guard ─────────────────────────────────────────
            if full_text and not tool_calls:
                hall_triggers = {"patient_name", "preferred_day", "preferred_time", "arg_key"}
                if any(k in full_text.lower() for k in hall_triggers):
                    print(f"⚠ [HALLUC] Detected: {full_text[:80]}")
                    if call_metrics:
                        call_metrics.record_hallucination()
                    xml_pairs = re.findall(
                        r"<arg_key>\s*(\w+)\s*</arg_key>\s*<arg_value>\s*(.*?)\s*</arg_value>",
                        full_text, re.DOTALL,
                    )
                    fn_match = re.search(r"\b(book_appointment|check_available_slots)\b", full_text)
                    fn_name  = fn_match.group(1) if fn_match else None
                    # Fallback: if AI outputs raw JSON instead of XML tags
                    if not xml_pairs and ("{" in full_text and "}" in full_text):
                        try:
                            json_body = full_text[full_text.find("{"):full_text.rfind("}")+1]
                            extracted = json.loads(json_body)
                            fn_name = fn_name or next((k for k in ["book_appointment", "check_available_slots", "cancel_appointment", "reschedule_appointment"] if k in full_text), None)
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
                        if not args.get("preferred_time"): args["preferred_time"] = "06:00 PM"
                        if not args.get("preferred_day"):  args["preferred_day"]  = "Today"
                        args.update({"patient_age": "5", "parent_name": "Guardian",
                                     "contact_number": caller_id})
                    elif fn in ("cancel_appointment", "reschedule_appointment"):
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
                        # Smart selection: if user mentioned a time, try to match it
                        best_slot = slots_res["available_slots"][0]
                        user_pref_lower = transcript.lower()
                        for s in slots_res["available_slots"]:
                            # basic match for strings like "7", "seven", "सात"
                            if any(x in user_pref_lower for x in [s.split(":")[0].lstrip("0"), time_to_hindi(s)]):
                                best_slot = s
                                break
                        
                        first_hi = time_to_hindi(best_slot)
                        slot_reply = f"क्या आज {first_hi} का समय ठीक रहेगा?"
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

                    # ── Name-correction rebook: cancel → rebook with new name
                    last_fn = tool_calls[-1]["function"]["name"] if tool_calls else ""
                    if last_fn == "cancel_appointment" and followup_tools:
                        for ftc in followup_tools:
                            if ftc["function"]["name"] == "book_appointment":
                                fargs = json.loads(ftc["function"]["arguments"] or "{}")
                                if not fargs.get("preferred_time"): fargs["preferred_time"] = "06:00 PM"
                                if not fargs.get("preferred_day"):  fargs["preferred_day"]  = "Today"
                                fargs.update({"patient_age": "5", "parent_name": "Guardian",
                                              "contact_number": caller_id})
                                print(f"🔧 [REBOOK] book_appointment({fargs})")
                                fres = await asyncio.to_thread(
                                    FUNCTION_MAP["book_appointment"], **fargs
                                )
                                history.append({
                                    "role": "tool", "tool_call_id": ftc.get("id", "ft_0"),
                                    "name": "book_appointment",
                                    "content": json.dumps(fres, ensure_ascii=False),
                                })
                                if isinstance(fres, dict) and fres.get("success"):
                                    conf_msg = fres.get("confirmation_message") or (
                                        f"{day_to_hindi(fargs['preferred_day'])} "
                                        f"{time_to_hindi(fargs['preferred_time'])} "
                                        f"{fargs.get('patient_name', '')} का appointment "
                                        "मैंने book कर दिया है। आप please 15 minutes पहले आ जाइए।"
                                    )
                                    await flush_sent(conf_msg)
                                    history.append({"role": "assistant", "content": conf_msg})
                                    if call_metrics:
                                        call_metrics.record_turn("assistant", conf_msg)
                                    spoke_any = True
                                break

                    # ── Fallback: no speech produced after tool ───────────────
                    if not spoke_any:
                        last_res = json.loads(history[-2]["content"]) if len(history) >= 2 else {}
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

    # ── Keep-alive silence packets ─────────────────────────────────────────

    async def vobiz_keep_alive():
        silence_mulaw = audioop.lin2ulaw(b"\x00" * 160, 2)
        silence_b64   = base64.b64encode(silence_mulaw).decode("utf-8")
        while not ws.closed:
            if sid:
                # Keep Vobiz alive
                await ws.send_str(json.dumps({
                    "event": "playAudio", "streamId": sid,
                    "media": {"contentType": "audio/x-mulaw", "sampleRate": 8000, "payload": silence_b64},
                }))
                # Keep Deepgram alive
                if dg_ws:
                    try:
                        await dg_ws.send(silence_mulaw)
                    except Exception:
                        pass
            await asyncio.sleep(0.8)

    # ── Deepgram receiver ─────────────────────────────────────────────────

    async def dg_receiver():
        nonlocal partial_hyp, speak_task
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
                if conf is not None and conf < 0.55:
                    print(f"⚡ [LOW-CONF] Dropped ({conf:.2f}): {tr!r}")
                    continue

                if not d.get("is_final", False):
                    partial_hyp = tr
                    print(f"\r〰  {tr}          ", end="", flush=True)
                    if (is_speaking and speak_task and not speak_task.done()
                            and len(tr.split()) >= 2):
                        print(f"\n🚫 [BARGE-IN] Cancelling bot speech")
                        if call_metrics:
                            call_metrics.record_interruption()
                        speak_task.cancel()
                        asyncio.create_task(clear_audio())
                else:
                    if len(tr.split()) >= 4:
                        partial_hyp = ""
                        asyncio.create_task(handle_transcript(tr))
                    else:
                        partial_hyp = tr
        except Exception as e:
            print(f"❌ [DEEPGRAM ERROR] Receiver died: {e}")
            traceback.print_exc()

    # ── Main WebSocket loop ────────────────────────────────────────────────

    try:
        dg_ws = await websockets.connect(
            DG_URL,
            additional_headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"},
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
                    recorder.write_caller(audioop.ulaw2lin(raw, 2))

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
