import asyncio
import base64
import json
import os
import time
import websockets
import logging
try:
    import audioop
except ImportError:
    import audioop_lts as audioop
import traceback
from aiohttp import web
import aiohttp
from datetime import datetime
from dotenv import load_dotenv
from email_utils import send_astrology_report, send_transcript_email

load_dotenv()

# Basic logging
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(asctime)s %(message)s')

# Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_URL = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key={GEMINI_API_KEY}"
MEMORY_FILE = "user_memory.json"
# Minimum transcript lines required to trigger a post-call report/transcript send
MIN_TRANSCRIPT_LINES = int(os.getenv("MIN_TRANSCRIPT_LINES", "1"))
# Noise gate: audio chunks whose RMS is below this are replaced with silence.
# Fan/AC noise is typically 100-400 RMS; speech is 800+. Tune via env var.
NOISE_GATE_RMS = int(os.getenv("NOISE_GATE_RMS", "150"))

def load_app_config():
    try:
        with open('app_config.json', 'r') as f:
            return json.load(f)
    except:
        return {"agent": {"system_prompt": "You are Jyotish Mitra, an expert Vedic astrologer."}}

def load_user_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, 'r') as f:
                return json.load(f)
        except: return {}
    return {}

def save_user_memory(memory):
    try:
        with open(MEMORY_FILE, 'w') as f:
            json.dump(memory, f)
    except Exception as e:
        print(f"[ERROR] Saving memory: {e}")

APP_CONFIG = load_app_config()
SYSTEM_PROMPT = APP_CONFIG["agent"]["system_prompt"]

async def home_page(request):
    return web.Response(text="Jyotish Voice Agent Online", content_type='text/plain')

async def handle_answer(request):
    try:
        post_data = await request.post()
        raw_num = post_data.get("From") or post_data.get("CallerName") or "Unknown"
        caller_id = str(raw_num).replace("+", "").replace("sip:", "").split("@")[0].strip()
        if caller_id.startswith("91") and len(caller_id) > 10: caller_id = caller_id[2:]
        host = request.headers.get("X-Forwarded-Host") or request.host
        ws_url = f"wss://{host}/vobiz-stream?caller_id={caller_id}"
        logging.info(f"Constructed vobiz WS URL: {ws_url}")
        xml_response = f'<?xml version="1.0" encoding="UTF-8"?><Response><Stream bidirectional="true" keepCallAlive="true" contentType="audio/x-mulaw;rate=8000">{ws_url}</Stream></Response>'
        return web.Response(text=xml_response, content_type='text/xml')
    except Exception: return web.Response(text="Error", status=500)

async def vobiz_handler(request):
    caller_id = request.query.get("caller_id", "Unknown")
    # Log incoming request context for diagnostics (helps debug 401 handshake issues)
    try:
        logging.info(f"Incoming vobiz connection for caller={caller_id} from={request.remote}")
        # headers -> convert to plain dict for readable logging
        hdrs = {k: v for k, v in request.headers.items()}
        logging.info(f"Request headers: {hdrs}")
    except Exception:
        logging.exception("Failed to log request metadata")

    ws = web.WebSocketResponse()
    await ws.prepare(request)
    logging.info(f"--- [BRIDGE]: Connected to Caller {caller_id} ---")
    
    state = {"transcript": [], "captured_email": None, "user_name": "User", "greeted": False,
             "dob": "N/A", "tob": "N/A", "pob": "N/A", "planets": "", "last_topic": "", "report_sent": False,
             "current_ai_text": ""}
    memory = load_user_memory()
    user_data = memory.get(caller_id)
    if user_data:
        state["captured_email"] = user_data.get("email")
        state["user_name"] = user_data.get("name", "User")
        state["dob"] = user_data.get("dob", "N/A")
        state["tob"] = user_data.get("tob", "N/A")
        state["pob"] = user_data.get("pob", "N/A")
        state["planets"] = user_data.get("planets", "")
        state["last_topic"] = user_data.get("last_topic", "")
    
    try:
        while not ws.closed:
            try:
                async with websockets.connect(GEMINI_URL) as gemini_ws:
                    current_date_str = datetime.now().strftime("%A, %B %d, %Y")
                    memory_context = ""
                    if user_data:
                        call_count = user_data.get("call_count", 1)
                        memory_context = f"\n\nRETURNING USER — Call #{call_count}:"
                        memory_context += f"\nName: {user_data.get('name')}"
                        memory_context += f"\nDOB: {user_data.get('dob')}, TOB: {user_data.get('tob')}, POB: {user_data.get('pob')}"
                        memory_context += f"\nEmail: {user_data.get('email')}"
                        if user_data.get("last_topic"):
                            memory_context += f"\nLast Topic Discussed: {user_data.get('last_topic')}"
                        if user_data.get("last_call_date"):
                            memory_context += f"\nLast Call Date: {user_data.get('last_call_date')}"
                        if user_data.get("conversation_summary"):
                            memory_context += f"\nPrevious Session Summary: {user_data.get('conversation_summary')}"
                        if user_data.get("planets"):
                            memory_context += f"\nKundali Planets: {user_data.get('planets')}"
                        memory_context += "\nIMPORTANT: You already have their full kundali. Do NOT ask for birth details again. Greet them by name and reference their last topic."
                    
                    dynamic_prompt = f"{SYSTEM_PROMPT}{memory_context}\n\nCaller: {caller_id}. Today: {current_date_str}."
                    
                    TOOLS = [{
                        "function_declarations": [{
                            "name": "send_astrology_report",
                            "description": "Sends the premium Kundali HTML report to the user's email. Call this after the user confirms their email and you have completed the astrological analysis.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "to_email": {"type": "string", "description": "User's email address"},
                                    "name": {"type": "string", "description": "User's full name"},
                                    "dob": {"type": "string", "description": "Date of birth"},
                                    "tob": {"type": "string", "description": "Time of birth"},
                                    "pob": {"type": "string", "description": "Place of birth"},
                                    "planets": {"type": "string", "description": "Planet house positions calculated from birth details. Format: Sun=X,Moon=X,Mars=X,Mercury=X,Jupiter=X,Venus=X,Saturn=X,Rahu=X,Ketu=X where X is house number 1-12"},
                                    "analysis_html": {"type": "string", "description": "Full Hindi Kundali analysis in HTML with h2 headings for each section"}
                                },
                                "required": ["to_email", "name", "dob", "tob", "pob", "planets", "analysis_html"]
                            }
                        },
                        {
                            "name": "save_user_profile",
                            "description": "Saves user profile and session memory. Call this at the END of every conversation.",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "dob": {"type": "string"},
                                    "tob": {"type": "string"},
                                    "pob": {"type": "string"},
                                    "email": {"type": "string"},
                                    "last_topic": {"type": "string", "description": "Main concern discussed: Career / Paise / Love / Health / General"},
                                    "planets": {"type": "string", "description": "Planet positions string used in the report. Same format as send_astrology_report."},
                                    "conversation_summary": {"type": "string", "description": "2-3 sentence summary of the key insights and predictions given in this session."}
                                },
                                "required": ["name", "dob", "tob", "pob", "email"]
                            }
                        }]
                    }]

                    setup_msg = {
                        "setup": {
                            "model": "models/gemini-2.0-flash-live-001",
                            "generationConfig": {
                                "responseModalities": ["AUDIO"],
                                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Aoede"}}}
                            },
                            "systemInstruction": {"parts": [{"text": dynamic_prompt}]},
                            "tools": TOOLS,
                            "realtimeInputConfig": {
                                "automaticActivityDetection": {
                                    "endOfSpeechSensitivity": "END_SENSITIVITY_HIGH",
                                    "silenceDurationMs": 600
                                }
                            },
                            "inputAudioTranscription": {}, "outputAudioTranscription": {}
                        }
                    }
                    await gemini_ws.send(json.dumps(setup_msg))
                    ack = await gemini_ws.recv()
                    ack_data = json.loads(ack)
                    if "error" in ack_data:
                        logging.error(f"[GEMINI SETUP ERROR] {ack_data['error']}")
                        raise Exception(f"Gemini setup rejected: {ack_data['error']}")
                    logging.info("[GEMINI] Setup ACK received OK")
                    
                    if not state["greeted"]:
                        if user_data:
                            name = user_data.get("name", "")
                            last_topic = user_data.get("last_topic", "")
                            greeting = f"Namashkar {name} ji! Aapki kundali mere paas hai jo maine pichli baar banai thi."
                            if last_topic:
                                greeting += f" Mujhe yaad hai ki aapne {last_topic} ke baare mein poocha tha."
                            greeting += " Aaj main aapko kis tarah madad kar sakti hoon?"
                            trigger = f"Say this greeting exactly in Hinglish: '{greeting}'"
                        else:
                            trigger = "Start the new session with the opening greeting."
                        await gemini_ws.send(json.dumps({"realtimeInput": {"text": trigger}}))
                        state["greeted"] = True

                    stream_sid = None
                    upsample_state = None

                    async def vobiz_to_ai():
                        nonlocal stream_sid, upsample_state
                        try:
                            async for msg in ws:
                                if msg.type == aiohttp.WSMsgType.TEXT:
                                    data = json.loads(msg.data)
                                    current_id = data.get("streamId") or data.get("streamSid") or (data.get("start", {}).get("streamId") if data.get("event") == "start" else None)
                                    if current_id and not stream_sid: stream_sid = current_id
                                    if data.get("event") == "media" and stream_sid:
                                        payload = data.get("media", {}).get("payload") or data.get("payload")
                                        if payload:
                                            mulaw_data = base64.b64decode(payload)
                                            pcm_8k = audioop.ulaw2lin(mulaw_data, 2)
                                            # Noise gate: replace fan/AC hum with silence so Gemini VAD
                                            # doesn't mistake background noise for speech.
                                            if audioop.rms(pcm_8k, 2) < NOISE_GATE_RMS:
                                                pcm_8k = b'\x00' * len(pcm_8k)
                                            pcm_16k, upsample_state = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, upsample_state)
                                            await gemini_ws.send(json.dumps({"realtimeInput": {"audio": {"data": base64.b64encode(pcm_16k).decode("utf-8"), "mimeType": "audio/pcm;rate=16000"}}}))
                                elif msg.type == aiohttp.WSMsgType.CLOSE: break
                        except Exception as e:
                            print(f"[ERROR] in vobiz_to_ai: {e}")
                            traceback.print_exc()

                    async def ai_to_vobiz():
                        nonlocal downsample_state
                        try:
                            async for message in gemini_ws:
                                resp = json.loads(message)
                                if "toolCall" in resp:
                                    for call in resp["toolCall"]["functionCalls"]:
                                        if call["name"] == "send_astrology_report":
                                            args = call["args"]
                                            state["captured_email"] = args['to_email']
                                            state["user_name"] = args['name']
                                            state["dob"], state["tob"], state["pob"] = args['dob'], args['tob'], args['pob']
                                            state["planets"] = args.get('planets', '')
                                            state["report_sent"] = True
                                            full_transcript = "<br>".join(state["transcript"])
                                            # Fallback: if real-time transcription didn't capture anything,
                                            # use the analysis_html summary as conversation context
                                            if not full_transcript and args.get('analysis_html'):
                                                full_transcript = f"Jyotish Mitra: {args['analysis_html']}"
                                            asyncio.create_task(asyncio.to_thread(send_astrology_report, args['to_email'], args['name'], args['dob'], args['tob'], args['pob'], args['analysis_html'], args.get('planets', ''), full_transcript))
                                            await gemini_ws.send(json.dumps({"toolResponse": {"functionResponses": [{"name": "send_astrology_report", "id": call["id"], "response": {"result": "Success"}}]}}))
                                        elif call["name"] == "save_user_profile":
                                            args = call["args"]
                                            existing = memory.get(caller_id, {})
                                            args["last_call_date"] = datetime.now().strftime("%d %B %Y")
                                            args["call_count"] = existing.get("call_count", 0) + 1
                                            memory[caller_id] = {**existing, **args}
                                            save_user_memory(memory)
                                            state["last_topic"] = args.get("last_topic", state["last_topic"])
                                            if args.get("planets"): state["planets"] = args["planets"]
                                            await gemini_ws.send(json.dumps({"toolResponse": {"functionResponses": [{"name": "save_user_profile", "id": call["id"], "response": {"result": "Saved"}}]}}))
                                server_content = resp.get("serverContent")
                                if server_content:
                                    # Barge-in: Gemini detected user interrupted mid-response
                                    if server_content.get("interrupted"):
                                        if stream_sid: await ws.send_str(json.dumps({"event": "clearAudio", "streamId": stream_sid}))
                                        if state["current_ai_text"].strip():
                                            state["transcript"].append(f"Jyotish Mitra: {state['current_ai_text'].strip()}...")
                                            state["current_ai_text"] = ""
                                            
                                    if server_content.get("turnComplete"):
                                        if state["current_ai_text"].strip():
                                            state["transcript"].append(f"Jyotish Mitra: {state['current_ai_text'].strip()}")
                                            state["current_ai_text"] = ""

                                    user_trans = server_content.get("inputTranscription", {}).get("text")
                                    if user_trans:
                                        state["transcript"].append(f"User: {user_trans}")
                                        
                                    if "modelTurn" in server_content:
                                        for part in server_content["modelTurn"].get("parts", []):
                                            if "text" in part and part["text"].strip():
                                                # Accumulate AI text output instead of appending directly
                                                state["current_ai_text"] += part["text"]
                                            elif "inlineData" in part:
                                                pcm_24k = base64.b64decode(part["inlineData"]["data"])
                                                pcm_8k, downsample_state = audioop.ratecv(pcm_24k, 2, 1, 24000, 8000, downsample_state)
                                                mulaw_data = audioop.lin2ulaw(pcm_8k, 2)
                                                if stream_sid: await ws.send_str(json.dumps({"event": "playAudio", "streamId": stream_sid, "media": {"contentType": "audio/x-mulaw", "sampleRate": 8000, "payload": base64.b64encode(mulaw_data).decode("utf-8")}}))
                        except Exception as e:
                            print(f"[ERROR] in ai_to_vobiz: {e}")
                            traceback.print_exc()

                    downsample_state = None
                    async def heartbeat():
                        while not ws.closed:
                            await asyncio.sleep(30)
                            try: await gemini_ws.ping()
                            except: break
                    await asyncio.gather(vobiz_to_ai(), ai_to_vobiz(), heartbeat())
            except Exception as e:
                logging.error(f"[GEMINI RECONNECT] Connection failed: {e}")
                traceback.print_exc()
                await asyncio.sleep(1)
    except Exception: traceback.print_exc()
    finally:
        # Flush any remaining AI text
        if state.get("current_ai_text", "").strip():
            state["transcript"].append(f"Jyotish Mitra: {state['current_ai_text'].strip()}")

        # Auto-save whatever we captured in case save_user_profile was never called
        if state["user_name"] != "User" and state["dob"] != "N/A":
            existing = memory.get(caller_id, {})
            auto = {"name": state["user_name"], "dob": state["dob"], "tob": state["tob"],
                    "pob": state["pob"], "last_call_date": datetime.now().strftime("%d %B %Y"),
                    "call_count": existing.get("call_count", 0) + 1}
            if state["captured_email"]: auto["email"] = state["captured_email"]
            if state["planets"]: auto["planets"] = state["planets"]
            if state["last_topic"]: auto["last_topic"] = state["last_topic"]
            memory[caller_id] = {**existing, **auto}
            save_user_memory(memory)
            print(f"--- [POST-CALL]: Memory auto-saved for {state['user_name']} ---")

        # Send transcript-only email if report was never triggered during the call
        if state["captured_email"] and len(state["transcript"]) >= MIN_TRANSCRIPT_LINES and not state.get("report_sent"):
            print(f"--- [POST-CALL]: Sending transcript to {state['captured_email']} ---")
            full_text = "<br>".join(state["transcript"])
            await asyncio.to_thread(send_astrology_report, state["captured_email"], state["user_name"],
                                    state["dob"], state["tob"], state["pob"],
                                    "<p>Call ended before report was generated.</p>",
                                    state["planets"], full_text)

        # ALWAYS send the full conversation transcript as a separate email after call ends
        # No transcript guard — send even if empty so user always receives it
        if state["captured_email"]:
            print(f"--- [POST-CALL]: Sending transcript email to {state['captured_email']} (lines={len(state['transcript'])}) ---")
            await asyncio.to_thread(send_transcript_email, state["captured_email"], state["user_name"], state["transcript"])

        if not ws.closed: await ws.close()
    return ws

async def main():
    app = web.Application()
    app.router.add_get('/', home_page)
    app.router.add_post('/answer', handle_answer)
    app.router.add_get('/vobiz-stream', vobiz_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    while True: await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
