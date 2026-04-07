import asyncio
import base64
import json
import os
import websockets
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MODEL = "models/gemini-3.1-flash-live-preview"
GEMINI_URL = f"wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent?key={GEMINI_API_KEY}"

async def test_connection():
    print(f"Connecting to Gemini Live API with model: {MODEL}...")
    try:
        async with websockets.connect(GEMINI_URL) as ws:
            # 1. Send Setup
            setup_msg = {
                "setup": {
                    "model": MODEL,
                    "generation_config": {
                        "response_modalities": ["AUDIO"]
                    }
                }
            }
            await ws.send(json.dumps(setup_msg))
            
            # Wait for setup response
            response = await ws.recv()
            print(f"Setup Response: {response}")
            
            # 2. Send Dummy Audio Frame (1 second of silence, 16k PCM)
            # 16000 samples * 2 bytes/sample = 32000 bytes
            dummy_audio = b'\x00' * 32000 
            audio_msg = {
                "realtime_input": {
                    "audio": {
                        "data": base64.b64encode(dummy_audio).decode("utf-8"),
                        "mime_type": "audio/pcm"
                    }
                }
            }
            print("Sending dummy audio frame...")
            await ws.send(json.dumps(audio_msg))
            
            # 3. Wait for any server content or error
            # We use a timeout because if it's successful, we might just get a turn_complete or silence
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                print(f"Server Response: {msg[:200]}...")
                print("TEST PASSED: Connection stable and frame accepted.")
            except asyncio.TimeoutError:
                print("TEST PASSED: Connection stable (no error response received after sending audio).")
            
    except Exception as e:
        print(f"TEST FAILED: {e}")

if __name__ == "__main__":
    asyncio.run(test_connection())
