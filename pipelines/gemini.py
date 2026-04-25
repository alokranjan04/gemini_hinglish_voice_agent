# -*- coding: utf-8 -*-
"""
Gemini Multimodal Live pipeline WebSocket handler.

Uses Google's BidiGenerateContent WebSocket for full end-to-end audio I/O.
System prompt and tool schemas are loaded from app_config.json at call-start.
"""
import asyncio, audioop, base64, json, os, time, traceback
from datetime import datetime

import aiohttp
import websockets
from aiohttp import web

from config.settings import APP_CONFIG, GEMINI_WS_URL
from core.recorder import _TimelineRecorder
from core.hindi_utils import CONFIRMATION_WORDS
from pharmacy_functions import FUNCTION_MAP, send_call_summary_email
from metrics.collector import store, resource_poller
from metrics.cost_calculator import calculate_cost


async def gemini_handler(request):
    caller_id = request.query.get("caller_id", "Unknown")
    ws        = web.WebSocketResponse(protocols=["audio.drachtio.org"])
    await ws.prepare(request)

    sid            = None
    call_metrics   = None
    poll_task      = None
    g_task         = None
    transcript_log = []
    start_time     = time.time()
    recorder       = _TimelineRecorder()

    # ── Build system prompt from config ────────────────────────────────────
    now           = datetime.now()
    date_str      = now.strftime("%A, %B %d, %Y (%I:%M %p)")
    greeting_text = APP_CONFIG.get("scripts", {}).get(
        "greeting",
        "नमस्ते! नेहा चाइल्ड केयर में आपका स्वागत है। मैं प्रिया बोल रही हूँ।",
    )
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

    system_prompt = (
        f"{APP_CONFIG['agent']['system_prompt']}\n\n"
        f"REAL-TIME: {date_str}. Caller: {caller_id}.\n\n"
        f"CALL START: When you receive [CALL_START], say this greeting EXACTLY "
        f"and NOTHING ELSE:\n'{greeting_text}'\n\n"
        f"{kb_prompt}\n\n"
        f"{APP_CONFIG['prompts']['gemini_rules']}"
    )

    try:
        async with websockets.connect(GEMINI_WS_URL) as gemini_ws:
            params = APP_CONFIG.get("parameters", {}).get("google", {})
            setup_msg = {
                "setup": {
                    "model": params.get("model", "models/gemini-3.1-flash-live-preview"),
                    "generationConfig": {
                        "temperature": params.get("temperature", 0.1),
                        "responseModalities": ["AUDIO"],
                        "speechConfig": {
                            "voiceConfig": {
                                "prebuiltVoiceConfig": {"voiceName": "Aoede"}
                            }
                        },
                    },
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "tools": APP_CONFIG["tools"]["gemini"],
                    "inputAudioTranscription":  {},
                    "outputAudioTranscription": {},
                }
            }
            await gemini_ws.send(json.dumps(setup_msg))
            setup_resp = await gemini_ws.recv()
            print(f"--- [GEMINI]: Setup: {setup_resp[:200]}")

            # Neutral signal that triggers the greeting (won't match greeting-guard rule)
            await gemini_ws.send(json.dumps({"realtimeInput": {"text": "[CALL_START]"}}))

            upsample_state   = None
            downsample_state = None
            state            = {"last_ai_audio": 0.0}

            # ── Vobiz → Gemini audio forwarding ─────────────────────────────

            async def from_vobiz():
                nonlocal sid, upsample_state
                try:
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data   = json.loads(msg.data)
                            cur_id = (
                                data.get("streamId") or data.get("streamSid")
                                or data.get("start", {}).get("streamId")
                                or data.get("start", {}).get("streamSid")
                            )
                            if cur_id and not sid:
                                sid = cur_id
                                print(f"--- [GEMINI]: Started {sid} ---")
                                nonlocal call_metrics, poll_task
                                call_metrics = store.start_call(sid, "google", caller_id)
                                poll_task    = asyncio.create_task(resource_poller(call_metrics))

                            if data.get("event") == "media" and sid:
                                payload = (
                                    data.get("media", {}).get("payload")
                                    or data.get("payload")
                                )
                                if payload:
                                    mulaw = base64.b64decode(payload)
                                    pcm8  = audioop.ulaw2lin(mulaw, 2)
                                    recorder.write_caller(pcm8)
                                    # Only forward when Gemini is not actively speaking
                                    if time.time() - state["last_ai_audio"] >= 1.0:
                                        pcm16, upsample_state = audioop.ratecv(
                                            pcm8, 2, 1, 8000, 16000, upsample_state
                                        )
                                        await gemini_ws.send(json.dumps({
                                            "realtimeInput": {
                                                "audio": {
                                                    "data": base64.b64encode(pcm16).decode("utf-8"),
                                                    "mimeType": "audio/pcm;rate=16000",
                                                }
                                            }
                                        }))
                        elif msg.type == aiohttp.WSMsgType.CLOSE:
                            break
                except Exception as e:
                    print(f"[GEMINI] from_vobiz error: {e}")

            # ── Gemini → Vobiz audio + tool execution ────────────────────────

            _BOOKING_CONFIRM_KW = (
                "book कर दिया", "बुक कर दिया", "appointment मैंने", "appointment book"
            )

            async def from_gemini():
                nonlocal downsample_state
                priya_buf    = []
                caller_buf   = []
                _turn_booked = False

                def _flush_caller():
                    combined = "".join(caller_buf).strip()
                    caller_buf.clear()
                    if combined:
                        print(f"\n[USER]: {combined}")
                        transcript_log.append(f"Caller: {combined}")
                        if call_metrics:
                            call_metrics.record_turn("user", combined)

                def _flush_priya():
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

                        # Buffer caller transcript fragments
                        transcription = (
                            resp.get("inputAudioTranscription")
                            or resp.get("serverContent", {}).get("inputTranscription")
                        )
                        if transcription and isinstance(transcription, dict):
                            t = transcription.get("text", "")
                            if t:
                                caller_buf.append(t)

                        # Buffer Priya transcript fragments; flush caller first
                        out_transcription = (
                            resp.get("outputAudioTranscription")
                            or resp.get("serverContent", {}).get("outputTranscription")
                        )
                        if out_transcription and isinstance(out_transcription, dict):
                            t = out_transcription.get("text", "")
                            if t:
                                if caller_buf:
                                    _flush_caller()
                                priya_buf.append(t)

                        # Stream audio to Vobiz
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
                                        recorder.write_priya(pcm8)
                                        mulaw = audioop.lin2ulaw(pcm8, 2)
                                        if sid and not ws.closed:
                                            print("🔊", end="", flush=True)
                                            await ws.send_str(json.dumps({
                                                "event": "playAudio", "streamId": sid,
                                                "media": {
                                                    "contentType": "audio/x-mulaw",
                                                    "sampleRate": 8000,
                                                    "payload": base64.b64encode(mulaw).decode("utf-8"),
                                                },
                                            }))

                        # Flush transcript buffers at turn boundary
                        if sc and sc.get("turnComplete"):
                            _flush_caller()
                            _flush_priya()
                            priya_said = " ".join(
                                e[7:] for e in transcript_log if e.startswith("Priya: ")
                            ).lower()
                            if not _turn_booked and any(
                                kw in priya_said for kw in _BOOKING_CONFIRM_KW
                            ):
                                print("⚠ [BOOKING HALLUCINATION] Priya said booking "
                                      "confirmation without calling book_appointment!")

                        # Handle tool calls
                        tool_call = resp.get("toolCall") or resp.get("tool_call")
                        if tool_call:
                            fn_calls     = (
                                tool_call.get("functionCalls")
                                or tool_call.get("function_calls", [])
                            )
                            responses    = []
                            _turn_booked = False

                            for call in fn_calls:
                                name = call["name"]
                                args = call.get("args") or call.get("arguments") or {}
                                cid  = call.get("id") or call.get("call_id")

                                # Server-side booking guard: block if user hasn't confirmed
                                if name == "book_appointment":
                                    last_user = next(
                                        (e[8:].lower() for e in reversed(transcript_log)
                                         if e.startswith("Caller: ")), ""
                                    )
                                    if not any(w in last_user for w in CONFIRMATION_WORDS):
                                        print(f"⚠ [BOOKING GUARD] No confirmation — blocking")
                                        responses.append({"name": name, "id": cid, "response": {
                                            "result": (
                                                "BLOCKED: User has not confirmed the slot yet. "
                                                "Ask: 'क्या यह समय ठीक रहेगा?' and wait for हाँ."
                                            )
                                        }})
                                        continue

                                # Auto-fill contact / parent fields
                                if name in ("book_appointment", "cancel_appointment",
                                            "reschedule_appointment"):
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
                                        result  = fn(**args)
                                        tool_ms = int((time.time() - t_tool) * 1000)
                                        if call_metrics:
                                            call_metrics.record_tool_call(name, args, result, tool_ms)
                                        if (name == "book_appointment"
                                                and isinstance(result, dict)
                                                and result.get("success")):
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
        # Wait for the Gemini coroutine to write its last audio chunks
        if g_task and not g_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(g_task), timeout=2.0)
            except Exception:
                pass
        if sid and call_metrics:
            duration = time.time() - start_time
            cost     = calculate_cost("google", duration)
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
        duration = int(time.time() - start_time)
        if transcript_log:
            summary = (f"Caller: {caller_id} | Duration: {duration}s "
                       f"| Turns: {len(transcript_log)}")
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
