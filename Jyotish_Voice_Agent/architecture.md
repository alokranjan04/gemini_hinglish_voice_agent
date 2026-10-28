# Jyotish Mitra — System Architecture

**Version:** 2.5 | **Last Updated:** April 2026

---

## 1. System Overview

Jyotish Mitra is a two-component AI product:

| Component | Stack | Interface |
|---|---|---|
| **Voice Agent** | Python + Gemini Live API + Vobiz | Phone call (`+918065481243`) |
| **Web App** | Next.js 15 + Gemini API + React 19 | Browser (desktop & mobile) |

Both components share the same AI persona, conversation flow, and email delivery logic. They operate independently.

---

## 2. High-Level Call Flow (Voice Agent)

```
User dials +918065481243
        │
        ▼
Vobiz Telephony Platform
  POST /answer → returns XML with WebSocket URL
        │
        ▼
Python Bridge (Cloud Run)
  WebSocket /vobiz-stream?caller_id=XXX
        │
        ├──► Audio IN:  G.711 μ-law 8kHz → 16kHz PCM → Gemini Live
        │
        ├──► Audio OUT: Gemini Live 24kHz PCM → 8kHz PCM → G.711 μ-law → Vobiz
        │
        └──► Tool Calls: send_astrology_report / save_user_profile
                │
                ├──► Gemini REST API (gemini-1.5-flash) → 1500-word report
                ├──► Gmail SMTP → HTML email with chart + transcript
                └──► user_memory.json → persistent caller profile
```

---

## 3. Component Architecture

### 3.1 Vobiz Telephony Layer

- Provides the virtual Indian number (`+918065481243`)
- On incoming call: POST to `/answer` with caller metadata (`From`, `CallerName`)
- Bridge responds with XML `<Stream>` directive containing a WSS URL
- Establishes bidirectional WebSocket carrying G.711 μ-law audio at 8kHz

**Caller ID normalisation** (handled in `handle_answer`):
```
+918012345678  →  8012345678   (strip +91, keep 10 digits)
sip:user@host  →  user         (strip SIP URI)
```

---

### 3.2 Python Bridge (Cloud Run)

**File:** `main.py`

The bridge is a single `aiohttp` async server with two routes:

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Health check |
| `/answer` | POST | Receives Vobiz webhook, returns XML |
| `/vobiz-stream` | GET (WS upgrade) | Bidirectional audio bridge |

**Session State Object:**
```python
state = {
    "transcript":      [],       # Full conversation log
    "captured_email":  None,     # Confirmed email address
    "user_name":       "User",   # Extracted from conversation
    "greeted":         False,    # Prevents duplicate greeting on reconnect
    "dob":             "N/A",    # Date of birth (confirmed)
    "tob":             "N/A",    # Time of birth with AM/PM (confirmed)
    "pob":             "N/A",    # Place of birth (confirmed)
    "planets":         "",       # Planet positions string: Sun=X,Moon=X,...
    "last_topic":      "",       # Career / Paise / Love / Health
    "report_sent":     False,    # Prevents duplicate post-call email
}
```

**Reconnect Logic:**
The outer `while not ws.closed` loop reconnects to Gemini if the WebSocket drops mid-call. `state["greeted"] = True` persists across reconnects so the greeting is not repeated.

---

### 3.3 Audio Resampling Pipeline

All resampling uses Python's `audioop` stdlib module (Python 3.11) with `audioop-lts` as a fallback for Python 3.13+.

```
┌─────────────────────────────────────────────────────┐
│  INBOUND (User → AI)                                │
│                                                     │
│  Vobiz WebSocket                                    │
│    → base64 decode                                  │
│    → audioop.ulaw2lin()     8kHz μ-law → 8kHz PCM  │
│    → audioop.ratecv()       8kHz PCM  → 16kHz PCM  │
│    → base64 encode                                  │
│    → Gemini realtimeInput audio (mimeType pcm;rate=16000)
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│  OUTBOUND (AI → User)                               │
│                                                     │
│  Gemini serverContent modelTurn inlineData          │
│    → base64 decode                                  │
│    → audioop.ratecv()       24kHz PCM → 8kHz PCM   │
│    → audioop.lin2ulaw()     8kHz PCM  → 8kHz μ-law │
│    → base64 encode                                  │
│    → Vobiz playAudio event                          │
└─────────────────────────────────────────────────────┘
```

---

### 3.4 Gemini Live API Integration

**Model:** `models/gemini-3.1-flash-live-preview`
**Protocol:** Bidirectional WebSocket (`wss://generativelanguage.googleapis.com/...`)

**Setup message fields:**
```json
{
  "setup": {
    "model": "models/gemini-3.1-flash-live-preview",
    "generationConfig": {
      "responseModalities": ["AUDIO"],
      "speechConfig": { "voiceConfig": { "prebuiltVoiceConfig": { "voiceName": "Aoede" } } }
    },
    "systemInstruction": { "parts": [{ "text": "<dynamic_prompt>" }] },
    "tools": [ ... ],
    "inputAudioTranscription": {},
    "outputAudioTranscription": {}
  }
}
```

**Dynamic prompt construction:**
```
{SYSTEM_PROMPT from app_config.json}
+
{RETURNING USER context block if caller_id found in memory}
+
"Caller: {caller_id}. Today: {date}."
```

**Heartbeat:** A background coroutine pings Gemini every 30 seconds to prevent Cloud Run idle timeouts on long sessions.

---

### 3.5 Barge-In Mechanism

Two-layer barge-in ensures audio stops the moment the user speaks:

**Layer 1 — Gemini interrupt signal:**
```python
if server_content.get("interrupted") and stream_sid:
    await ws.send_str(json.dumps({"event": "clearAudio", "streamId": stream_sid}))
```
Fires as soon as Gemini's VAD detects the user speaking — before transcription.

**Layer 2 — User transcription confirmation:**
```python
if user_trans:
    await ws.send_str(json.dumps({"event": "clearAudio", "streamId": stream_sid}))
```
Fires when the user's speech is transcribed — catches any residual buffered audio.

Both layers send a `clearAudio` event to Vobiz which discards any audio queued in its playback buffer.

---

### 3.6 Tool Calling Architecture

Two tools are exposed to Gemini:

#### `send_astrology_report`
Called by Gemini after completing the full verbal analysis.

**Parameters:**
| Field | Type | Description |
|---|---|---|
| `to_email` | string | Confirmed user email |
| `name` | string | User's full name |
| `dob` | string | Date of birth |
| `tob` | string | Time of birth with AM/PM |
| `pob` | string | City/town of birth |
| `planets` | string | `Sun=X,Moon=X,...` house positions (1–12) |
| `analysis_html` | string | Brief HTML summary from live session |

**What happens on invocation:**
1. State is updated (`captured_email`, `planets`, `report_sent = True`)
2. Full transcript is captured from `state["transcript"]`
3. `asyncio.create_task` fires `send_astrology_report()` in a thread (non-blocking)
4. Tool response `{"result": "Success"}` returned to Gemini immediately
5. In the thread: Gemini REST API generates 1,500-word detailed report → email assembled → sent via Gmail SMTP

#### `save_user_profile`
Called by Gemini at the end of every conversation.

**Parameters:**
| Field | Type | Required |
|---|---|---|
| `name`, `dob`, `tob`, `pob`, `email` | string | Yes |
| `last_topic` | string | No — Career/Paise/Love/Health |
| `planets` | string | No — planet positions |
| `conversation_summary` | string | No — 2–3 sentence session summary |

**Memory merge logic:**
```python
existing = memory.get(caller_id, {})
args["last_call_date"] = datetime.now().strftime("%d %B %Y")
args["call_count"] = existing.get("call_count", 0) + 1
memory[caller_id] = {**existing, **args}   # merge, not overwrite
```

---

### 3.7 Report Generation Pipeline

When `send_astrology_report()` is called in `email_utils.py`:

```
Step 1: generate_detailed_analysis(name, dob, tob, pob)
        │
        └─► POST https://generativelanguage.googleapis.com/
                v1beta/models/gemini-1.5-flash:generateContent
                Prompt: 7-section 1500-word Hindi Kundali in HTML
                Temperature: 0.7 | MaxTokens: 4096
                Timeout: 90s

Step 2: build_kundali_table(planets_str)
        │
        └─► Parse "Sun=X,Moon=X,..." into house_contents dict
            Build South Indian 4×4 HTML <table>
            Planets coloured individually (9 unique colours)

Step 3: format_transcript_html(transcript)
        │
        └─► Split by <br> or \n
            "User:" → gold left-border bubble
            "Jyotish Mitra:" → amber left-border bubble

Step 4: Assemble HTML email
        │
        ├─► Header (Cinzel font, dark/gold theme)
        ├─► Birth details table
        ├─► Kundali chart (4×4 grid)
        ├─► Detailed analysis (7 sections, Hindi Devanagari)
        └─► Conversation transcript (styled bubbles)

Step 5: Send via Gmail SMTP (SSL port 465)
```

---

### 3.8 Memory & Personalization System

**Storage:** `user_memory.json` (file-based, instance-local)

**Memory record per caller:**
```json
{
  "9801234567": {
    "name": "Alok",
    "dob": "15 March 1981",
    "tob": "01:20 AM",
    "pob": "Delhi",
    "email": "alok@gmail.com",
    "planets": "Sun=1,Moon=4,Mars=8,Mercury=1,Jupiter=5,Venus=12,Saturn=7,Rahu=3,Ketu=9",
    "last_topic": "Career",
    "conversation_summary": "Predicted career change in 2026-27 during Jupiter Mahadasha. Advised to focus on communication skills.",
    "last_call_date": "27 April 2026",
    "call_count": 3
  }
}
```

**Returning caller greeting (built programmatically):**
```
"Namashkar {name} ji! Aapki kundali mere paas hai jo maine pichli baar banai thi.
 Mujhe yaad hai ki aapne {last_topic} ke baare mein poocha tha.
 Aaj main aapko kis tarah madad kar sakti hoon?"
```

**Auto-save in `finally` block:** Even if the AI never calls `save_user_profile` (e.g. user hangs up early), the bridge saves whatever state was captured before closing.

> **Production note:** `user_memory.json` is instance-local. For multi-instance Cloud Run deployments, replace with Firestore or Redis for shared memory.

---

### 3.9 Conversation State Machine

```
NEW CALLER:
[INTRO] → wait for "haan/yes"
    → [NAME] → [DOB] → [TOB] → [AM/PM confirm]
    → [POB] → [CONFIRMATION GATE — read all 4 back, wait YES]
    → [INCIDENT 1] → [INCIDENT 2]
    → [EMAIL] → [EMAIL CONFIRM]
    → [HOOK — 3 insights]
    → [CONCERN] → [DEEP ANALYSIS]
    → [SEND REPORT] → [SAVE MEMORY]

RETURNING CALLER:
[GREETING with name + last topic]
    → [CONCERN] → [DEEP ANALYSIS]
    → [SEND REPORT] → [SAVE MEMORY]

CONFIRMATION GATE (Rule 6 — hard block):
    Reads: "Naam: X. Janam Tithi: DD Month YYYY. Samay: HH:MM SUBAH/RAAT. Sheher: X."
    Waits for YES. If wrong → fix + re-read entire block.
    CANNOT proceed to email or analysis without YES.
```

---

## 4. Web App Architecture

**Path:** `c:\Users\Alok Ranjan\Documents\jyotish\`
**Stack:** Next.js 15, React 19, TypeScript, Tailwind CSS 4, Gemini SDK

### 4.1 Component Map

```
app/
├── page.tsx              ← Main chat UI (voice-only + text modes)
├── layout.tsx            ← Fonts (Cinzel, Noto Sans Devanagari)
└── api/
    ├── save-chat/route.ts   ← POST: saves chat JSON to Google Cloud Storage
    └── send-email/route.ts  ← POST: Gemini report generation + Gmail SMTP

lib/
├── constants.ts          ← SYSTEM_INSTRUCTION, INITIAL_MESSAGE, configs
└── types.ts              ← Message, BirthDetails types
```

### 4.2 Web App Barge-In Fix

Two refs solve the stale closure + double-fire problem:

```typescript
// currentUtteranceRef: null out onend before cancel to prevent double-fire
if (currentUtteranceRef.current) currentUtteranceRef.current.onend = null;
window.speechSynthesis.cancel();

// autoListenCallbackRef: assigned in render body (not useEffect)
// so onend always reads latest isLoading/isVoiceOnly state
autoListenCallbackRef.current = () => {
  if (isVoiceOnly && !isLoading && !isEmailSending) toggleRecording();
};
utterance.onend = () => { autoListenCallbackRef.current(); };
```

### 4.3 Web App Email Route

Same 7-section 1,500-word report generation as the voice agent, but additionally generates both Hindi and English versions side-by-side in one email. Planet positions parsed from a `PLANETS: Sun=X,...` line in the Gemini response.

---

## 5. Technology Stack Summary

### Voice Agent
| Layer | Technology | Purpose |
|---|---|---|
| Telephony | Vobiz | PSTN/SIP → WebSocket bridge |
| Audio codec | G.711 μ-law | Phone-compatible audio |
| Resampling | Python `audioop` | 8kHz ↔ 16kHz/24kHz PCM |
| AI (voice) | Gemini 3.1 Flash Live | Real-time multimodal voice |
| AI (report) | Gemini 1.5 Flash REST | 1500-word detailed report |
| Web framework | aiohttp | Async WebSocket server |
| Email | Gmail SMTP (SSL 465) | HTML report delivery |
| Memory | JSON file | Caller profile persistence |
| Infra | Google Cloud Run | Serverless containers |
| CI/CD | GitHub Actions | Auto-deploy on push to main |

### Web App
| Layer | Technology |
|---|---|
| Framework | Next.js 15 (App Router) |
| UI | React 19, Tailwind CSS 4 |
| AI | Google Generative AI SDK |
| Voice input | Web Speech API (SpeechRecognition) |
| Voice output | Web Speech API (SpeechSynthesis) |
| Storage | Google Cloud Storage (chat history) |
| Email | nodemailer + Gmail SMTP |

---

## 6. CI/CD & Deployment

```
GitHub push (main branch)
        │
        ▼
GitHub Actions (.github/workflows/deploy.yml)
    1. Checkout code
    2. Authenticate to Google Cloud (GCP_SA_KEY secret)
    3. Configure Docker for Artifact Registry
    4. docker build -t us-central1-docker.pkg.dev/testcnx-169610/...
    5. docker push
    6. gcloud run deploy jyotish-voice-agent
           --region us-central1
           --timeout 3600
           --set-env-vars GEMINI_API_KEY, GMAIL_USER, GMAIL_APP_PASSWORD
```

**Cloud Run configuration:**
- Region: `us-central1`
- Timeout: 3600s (supports 60-min consultations)
- Concurrency: default (each instance handles one call)
- Authentication: `--allow-unauthenticated`

---

## 7. Security

| Concern | Mitigation |
|---|---|
| API keys | GitHub Secrets → Cloud Run env vars |
| GCS credentials | Service account JSON excluded from git (`.gitignore`) |
| Gmail password | App Password (not account password) via env var |
| Caller data | Stored locally in `user_memory.json`; not transmitted to third parties |
| Audio | In-memory processing only; not persisted to disk |
