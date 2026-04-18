# Priya — AI Voice Receptionist for Neha Child Care

> A production Hindi voice agent that answers real clinic phone calls, books appointments, and manages a live Google Calendar — with two switchable AI pipelines and a built-in metrics dashboard.

Priya speaks natural conversational Hindi (Devanagari script), handles appointment booking / cancellation / rescheduling, checks real-time slot availability against Google Calendar, logs every booking to Google Sheets, sends .ics email invites, and emails a call transcript after every call — all over a live phone line.

---

## The Problem

Small clinics in India miss 40–60% of incoming calls. Receptionists are expensive and unavailable at night. Parents calling about sick children get voicemail.

This project replaces that with AI — at a fraction of SaaS pricing, with full control over the voice, language, and booking logic.

---

## Architecture Overview

```
Phone call (Vobiz)
        │
        ▼
  POST /answer  ←─── Vobiz webhook (call arrives)
        │
        ▼
  app_config.json ──► active_provider = "sarvam" | "google"
        │
   ┌────┴────┐
   │         │
   ▼         ▼
Pipeline A  Pipeline B
(Sarvam)   (Gemini)
```

A single `aiohttp` server on **port 5050** handles both pipelines. The active pipeline is selected per-call from `app_config.json` — switchable live via dashboard or API with no restart.

---

## Pipeline A — Sarvam (Primary / Production)

```
Vobiz WebSocket (mulaw 8 kHz)
  │
  ├──► Deepgram Nova-3  (STT WebSocket, Hindi, interim + final transcripts)
  │         │
  │    ┌────┴──────────────────────────────────────┐
  │    │  Transcript processing                     │
  │    │  • Confidence filter  (< 0.55 → dropped)  │
  │    │  • Greeting intercept (hello/हेलो → skip LLM)│
  │    │  • Barge-in detection (≥ 2-word interim)  │
  │    └────┬──────────────────────────────────────┘
  │         │  final transcript
  │         ▼
  │    Sarvam 30B LLM  (sarvam-30b, streaming, tool calling)
  │         │
  │    ┌────┴───────────────────────────────────────────┐
  │    │  Tool execution (pharmacy_functions.py)         │
  │    │  • check_available_slots → Google Calendar      │
  │    │  • book_appointment   → Sheets + Calendar + Email│
  │    │  • cancel_appointment → Sheets + Calendar        │
  │    │  • reschedule_appointment → cancel + re-book    │
  │    └────┬───────────────────────────────────────────┘
  │         │  Hindi text response
  │         ▼
  │    Sarvam Bulbul v2 TTS  (bulbul:v2, hi-IN, 8 kHz mulaw)
  │         │
  └─────────┤
            ▼
     Vobiz WebSocket  (playAudio event → phone speaker)
```

| Component | Technology |
|---|---|
| STT | Deepgram **Nova-3** — WebSocket, `language=hi`, mulaw 8 kHz, interim results |
| LLM | Sarvam **sarvam-30b** — OpenAI-compatible API, streaming, function calling |
| TTS | Sarvam **Bulbul v2** — `bulbul:v2`, `hi-IN`, 8 kHz mulaw output |
| Language | Hindi (Devanagari) — never transliteration |
| Barge-in | Interim transcript ≥ 2 words cancels in-flight TTS task |
| Keep-alive | 20 ms silence sent every 0.8 s to prevent Vobiz hangup |

---

## Pipeline B — Google Gemini Multimodal Live

```
Vobiz WebSocket (mulaw 8 kHz)
  │
  ├──► upsample 8kHz → 16kHz ──► Gemini BidiGenerateContent WebSocket
  │                                   │  (STT + LLM + TTS in one connection)
  │                                   │  tool calls → pharmacy_functions.py
  │                                   │  audio output (PCM 24 kHz)
  │         downsample 24kHz → 8kHz ◄─┘
  │         + audioop.mul amplify
  └─────────────────────────────────►  Vobiz WebSocket (playAudio)
```

| Component | Technology |
|---|---|
| Model | Gemini **gemini-3.1-flash-live-preview** |
| Voice | Aoede (built-in Gemini voice) |
| Protocol | BidiGenerateContent WebSocket (`v1beta`) |
| Audio in | mulaw 8 kHz → PCM 16 kHz (upsample via `audioop.ratecv`) |
| Audio out | PCM 24 kHz → mulaw 8 kHz (downsample + 1.4× amplify) |
| Advantage | Lowest latency — single WebSocket, no pipeline stages |

---

## Call Flow (Sarvam Pipeline — Full Sequence)

```
1. Phone rings → Vobiz fires POST /answer
2. Server checks active_provider → redirects to /sarvam-stream WebSocket
3. Deepgram WebSocket opened → keep-alive loop starts
4. Priya speaks greeting: "नमस्ते! नेहा चाइल्ड केयर में आपका स्वागत है..."
5. Caller speaks → Deepgram streams interim transcripts
     └─ Confidence < 0.55  → dropped (ambient noise filter)
     └─ Single greeting word → "जी, बताइए।" (no LLM needed)
     └─ ≥ 2 words interim, Priya is speaking → BARGE-IN: cancel TTS task
6. Final transcript arrives → handle_transcript()
     └─ is_responding = True  (queue any new transcript until done)
     └─ History appended → LLM streamed
7. LLM streams response text + optional tool_call
     └─ Text sentences flushed sentence-by-sentence to TTS
     └─ speak() called: TTS → PCM → recorder.write_priya() → mulaw → WebSocket
     └─ asyncio.sleep(playback_secs) holds is_speaking=True for barge-in window
8. Tool call detected → execute IMMEDIATELY (no extra LLM round-trip):
     check_available_slots → direct slot-offer reply (skip second LLM call)
     book_appointment      → scripted confirmation from tool result
     cancel_appointment    → if followup LLM wants book_appointment, execute it
                             (name-correction rebook — no user re-confirmation needed)
9. Booking guard: book_appointment only fires if last user turn ∈ CONFIRMATION_WORDS
10. Past-time guard: book_appointment rejects slots where appt_dt ≤ now()
11. Call ends → finally block:
     → wait for in-flight speak_task (up to 3 s) before saving recording
     → _TimelineRecorder.save() → stereo WAV (caller left, Priya right)
     → send_call_summary_email() with full transcript
     → store.end_call() → metrics logged
```

---

## Booking Flow (LLM Rules)

```
Step 1 — Extract NAME and REASON from conversation history
          • Any symptom mentioned = REASON — never ask again
          • Any child name mentioned = NAME — never ask again
          • Name correction "X नहीं Y है" → use Y (latest name wins)
          → BOTH known: skip to Step 2
          → Only one known: ask for the missing one only
          → Neither known: ask both in one question

Step 2 — call check_available_slots(preferred_day='Today')
          Never ask caller for day — use REAL-TIME clock

Step 3 — Offer ONE slot: "क्या [time_hi] का समय ठीक रहेगा?"
          If no → offer next slot

Step 4 — ONLY after explicit YES → call book_appointment
          YES words: हाँ, ठीक है, ठीक रहेगा, okay, हो जाए, बिल्कुल, चलेगा, ...

Step 5 — book_appointment runs concurrently:
          Google Sheets append + Calendar event + Email with .ics

Step 6 — Speak confirmation_message from tool result verbatim
```

**Name-correction rebook:** If the caller corrects the name after a booking, Priya calls `cancel_appointment` for the old name and **immediately** calls `book_appointment` with the corrected name, same reason, same slot — no re-confirmation needed.

---

## Google Sheets Column Layout

Every booking appends one row to `Sheet1`:

| Column | Field | Example |
|--------|-------|---------|
| A | Patient Name | Trishna |
| B | Patient Problems | बुखार |
| C | Parents Name | Guardian |
| D | Is appointment Booked | Yes / Cancelled |
| E | Booking time | 2026-04-15 10:20 |
| F | Child Age | 5 |
| G | Booking Slot | 10:20 AM |
| H | Contact Number | 917042915552 |

`cancel_appointment` marks column D as "Cancelled" and deletes the Google Calendar event.

---

## Recording — Stereo Timeline WAV

Every call produces a stereo `.wav` saved to `recordings/`:

```
Left channel  = caller audio  (mulaw decoded, 8 kHz PCM)
Right channel = Priya audio   (TTS PCM before mulaw encoding)
Sample rate   = 8000 Hz
Bit depth     = 16-bit PCM LE
```

`_TimelineRecorder` uses wall-clock timestamps to place each audio chunk at its real position — no overlaps, no silence gaps. The `finally` block waits up to 3 seconds for any in-flight TTS task to finish writing before saving.

---

## Emails Sent

| Trigger | Subject | Content |
|---------|---------|---------|
| Booking confirmed | `Appointment Booked: {patient_name}` | Details + .ics calendar invite |
| Call ends | `Call Summary: Neha Child Care` | Caller ID, duration, full transcript |

---

## Performance & Logic Tuning

The agent has been optimized for "World Class" speed and accuracy to handle clinical stress:

### 1. Speed (Latency)
-   **Parallel TTS**: Switched from serial (Wait for TTS to finish) to parallel (Start TTS immediately). Priya starts speaking as soon as the first sentence is generated.
-   **Aggressive Endpointing**: Reduced `utterance_end_ms` to **1000ms** (from 1500ms). This cuts the response delay by nearly half a second.
-   **Calendar Caching**: `check_available_slots` caches Google Calendar results for **30 seconds**. Subsequent checks within the same turn are instantaneous (<50ms).
-   **Short Scripts**: Reduced wording in greetings and confirmations to minimize audio generation time.

### 2. Logic & Reliability
-   **Strict Confirmation Guard**: `book_appointment` will **NEVER** fire based on an assumption. It requires an explicit 'Yes' (Haan, Theek hai, Okay) first.
-   **Hallucination Shield**: Priya is strictly forbidden from talking about non-clinic topics (interests, fees, etc.). She redirect all "weird" STT transcrips back to appointment booking.
-   **One-Slot Policy**: To keep conversations fast, she offers only **one** best slot at a time instead of long lists.
-   **Barge-in Sensitivity**: Threshold set to **100ms**. If you speak, Priya stops "Thinking" and "Talking" immediately to listen to you.
-   **VAD confidence**: STT confidence threshold raised to **65%** to filter out fan noise or background TV.

---

## Key Design Patterns

| Pattern | Implementation |
|---------|---------------|
| **Barge-in** | Interim transcript ≥ 2 words → `speak_task.cancel()` + `clearAudio` event |
| **Noise filter** | Deepgram confidence < 0.55 → transcript dropped |
| **Greeting shortcut** | Single-word greetings (hello/नमस्ते) → hardcoded reply, no LLM |
| **Direct slot reply** | After `check_available_slots`, slot offer built in Python — no second LLM call |
| **Scripted booking confirm** | Confirmation text comes from `tool.result.confirmation_message`, not LLM |
| **Followup tool execution** | After `cancel_appointment`, if LLM returns `book_appointment` in followup → executed immediately |
| **Booking guard** | `book_appointment` only executes if previous user turn is in `CONFIRMATION_WORDS` |
| **Past-time guard** | `book_appointment` rejects `appt_dt ≤ datetime.now()` |
| **Repeat-caller detection** | `APPOINTMENTS_DB` checked at call start — existing booking surfaced in system prompt |
| **Keep-alive** | 20 ms silence sent every 0.8 s to prevent Vobiz from hanging up |
| **WAV header strip** | TTS returns RIFF WAV — `wave.open(BytesIO)` extracts raw PCM before playback |
| **ratecv state** | `audioop.ratecv()` state preserved across chunks — no resampling artifacts |
| **Concurrent booking** | `ThreadPoolExecutor` runs Sheets + Calendar + Email in parallel (~3× faster) |

---

## Project Structure

```
app.py                    — Main server (aiohttp, port 5050, both pipelines)
app_config.json           — Agent persona, clinic hours, scripts, active_provider
pharmacy_functions.py     — Tool implementations (booking, cancel, reschedule, slots)

metrics/
  collector.py            — CallMetrics, MetricsStore singleton, resource poller
  cost_calculator.py      — Cost math (Deepgram + Sarvam + Gemini pricing)
  dashboard_html.py       — Chart.js live metrics dashboard

recordings/               — Stereo WAV files, one per call (gitignored)
benchmarks/               — Offline scenario harness (gitignored)

.env                      — All API keys (gitignored — never commit)
google-credentials.json   — Google service account JSON (gitignored — never commit)
.env.example              — Template showing required keys (safe to commit)
requirements.txt          — Python dependencies
```

---

## app_config.json

All agent behaviour lives here. Change persona, hours, or scripts without touching code:

```json
{
  "agent": {
    "name": "Priya",
    "role": "Senior Receptionist",
    "business": "Neha Child Care",
    "system_prompt": "आप प्रिया हैं — नेहा चाइल्ड केयर की रिसेप्शनिस्ट..."
  },
  "clinic": {
    "hours": {
      "morning": "10:00 AM to 12:00 PM",
      "evening": "06:00 PM to 08:00 PM",
      "sunday": "Closed"
    }
  },
  "scripts": {
    "greeting": "नमस्ते! नेहा चाइल्ड केयर में आपका स्वागत है...",
    "booking_confirmation": "{day} {time} {patient_name} का appointment मैंने book कर दिया है।..."
  },
  "active_provider": "sarvam"
}
```

---

## Setup

### 1. Python version

Use **Python 3.10–3.12**. Python 3.13 removed `audioop` which this project depends on.

### 2. Clone and create virtual environment

```bash
git clone https://github.com/alokranjan04/gemini_hinglish_voice_agent.git
cd gemini_hinglish_voice_agent

python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure `.env`

Create a `.env` file in the project root (never commit this):

```env
# Sarvam pipeline
DEEPGRAM_API_KEY=your_deepgram_key
SARVAM_API_KEY=your_sarvam_key

# Gemini pipeline
GEMINI_API_KEY=your_gemini_key

# Google integrations (both pipelines)
GOOGLE_CALENDAR_ID=your_calendar_id@gmail.com
GOOGLE_SPREADSHEET_ID=1NWx5XXBokgbqS_Rou0VGu78B4e8OdntXNZvYCGYiZcU

# Google Credentials (Base64 or Inline JSON)
# Used by the container to rebuild google-credentials.json at startup
GOOGLE_CREDENTIALS={"type":"service_account","project_id":"testcnx-169610",...}

# Email (Gmail SMTP)
GMAIL_USER=your@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
DOCTOR_EMAIL=doctor@example.com
```

### 5. Google Cloud service account

1. [Google Cloud Console](https://console.cloud.google.com/) → Enable **Sheets API** + **Calendar API**
2. IAM & Admin → Service Accounts → Create → download JSON key
3. Save as `google-credentials.json` in project root
4. Share your Google Sheet and Calendar with the service account email as **Editor**

### 6. Google Sheet setup

Create a sheet named `Sheet1` with these headers in row 1:

```
A: Patient Name  |  B: Patient Problems  |  C: Parents Name  |  D: Is appointment Booked
E: Booking time  |  F: Child Age         |  G: Booking Slot  |  H: Contact Number
```

### 7. Run

```bash
python app.py
```

Dashboard at `http://localhost:5050/`

## Production Deployment (Google Cloud GCE + Docker)

The agent is designed to run on a **GCE Instance** (Ubuntu 22.04) using **Docker**. Deployment is fully automated via GitHub Actions.

### 1. VM Setup
1. Create a GCE instance (e.g., `e2-medium`).
2. Install Docker and GCloud SDK.
3. Configure Docker to authenticate with Artifact Registry.

### 2. GitHub Actions Setup
Configure these **Secrets** in your GitHub repository:
- `GCP_PROJECT_ID`: `testcnx-169610`
- `GCE_INSTANCE_IP`: `34.122.77.178`
- `GCP_SA_KEY`: Your service account JSON key.
- `SSH_PRIVATE_KEY`: Private key for SSH access to the VM.
- `SARVAM_API_KEY`, `DEEPGRAM_API_KEY`, `GEMINI_API_KEY`, etc.

### 3. Automated Deployment
Any push to the `main` branch triggers the following:
1. **Build**: Creates a secure, non-root Docker image.
2. **Push**: Uploads the image to `us-central1-docker.pkg.dev`.
3. **Deploy**: SSH into GCE, prunes old images, pulls the latest, and restarts the container with fresh environment variables.

### 4. Vobiz Integration
Set Vobiz **Answer URL** to:
```
http://34.122.77.178:5050/answer
```
*(Note: Use `http` and `ws` unless you have configured SSL/WSS on the VM.)*

---

## Switching Pipelines

**Dashboard** (live, no restart):
```
http://localhost:5050/
```

**REST API**:
```bash
curl -X POST http://localhost:5050/api/set-provider \
     -H "Content-Type: application/json" \
     -d '{"provider": "sarvam"}'   # or "google"
```

**app_config.json**:
```json
{ "active_provider": "sarvam" }
```

---

## API Routes

| Method | Route | Purpose |
|--------|-------|---------|
| POST | `/answer` | Vobiz webhook — call arrives here |
| GET | `/sarvam-stream` | WebSocket — Sarvam pipeline handler |
| GET | `/gemini-stream` | WebSocket — Gemini pipeline handler |
| POST | `/api/set-provider` | Switch pipeline live |
| GET | `/` | Web dashboard |
| GET | `/metrics` | Metrics dashboard |
| GET | `/metrics/data` | JSON metrics API |
| GET | `/recordings/` | Browse call recordings |

---

## API Keys Required

| Key | Pipeline | Source |
|-----|----------|--------|
| `DEEPGRAM_API_KEY` | Sarvam (STT) | [deepgram.com](https://deepgram.com) |
| `SARVAM_API_KEY` | Sarvam (LLM + TTS) | [sarvam.ai](https://www.sarvam.ai) |
| `GEMINI_API_KEY` | Google | [aistudio.google.com](https://aistudio.google.com) |
| `GOOGLE_CALENDAR_ID` | Both | Google Calendar settings |
| `GOOGLE_SPREADSHEET_ID` | Both | Google Sheets URL |
| `GMAIL_APP_PASSWORD` | Both | [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) |

---

## Cost Estimate (per 5-minute call)

| Pipeline | STT | LLM | TTS | Approx Total |
|----------|-----|-----|-----|-------------|
| Sarvam | $0.039 (Deepgram) | ~$0.010 (Sarvam 30B) | ~$0.006 (Bulbul v2) | **~$0.055** |
| Google | — | $0.012 (Gemini Live blended) | — | **~$0.012** |

*Estimates as of April 2026. Gemini is cheaper; Sarvam gives finer control and better Hindi transcription accuracy.*

---

## Security

- `.env` and `google-credentials.json` are gitignored — **never commit them**
- Service account credentials should use **minimum required scopes** only (Sheets Editor + Calendar Editor)
- If a credential file is accidentally committed, **revoke the key immediately** in Google Cloud Console → IAM & Admin → Service Accounts → Keys

---

## Built by

**Alok Ranjan**

Questions, feedback, or building something similar — open an issue or connect on LinkedIn.

---

`hindi` `voice-ai` `gemini-live` `sarvam-ai` `deepgram` `google-calendar` `google-sheets` `appointment-booking` `healthcare-ai` `india` `asyncio` `aiohttp` `websocket` `vobiz`
