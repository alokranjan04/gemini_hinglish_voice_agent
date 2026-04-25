# Priya: AI Clinic Receptionist — Never Miss a Patient Call Again

> **Missed calls are missed patients.** Priya is a production-grade AI voice agent designed for Indian clinics to handle 100% of incoming calls, book appointments 24/7, and manage your Google Calendar automatically—even when your receptionist is busy or away.

Priya speaks natural conversational Hindi and Hinglish, handles booking/cancellation/rescheduling, checks real-time slot availability, logs every call to Google Sheets, and sends instant email confirmations—all over a live phone line.

---

## 🛑 The Problem: Missed Calls = Lost Revenue

Small to mid-sized clinics in India face a critical challenge:
*   **40–60% of incoming calls go unanswered** during peak hours or lunch breaks.
*   **Nighttime & Weekend calls** are completely lost to voicemail or go unpicked.
*   **Manual Booking** leads to human errors, double-bookings, and no-shows.
*   **Receptionists are expensive** and hard to train for 24/7 availability.

Priya solves this by providing a professional, empathetic, and always-available voice interface that works exactly like a senior receptionist.

---

## 🛠️ System Architecture

```
Phone call (Vobiz)
        │
        ▼
   POST /answer  ←─── Vobiz webhook (Call Arrives)
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

A single `aiohttp` server handles both pipelines. You can switch between providers live via the dashboard without any downtime.

---

## ⚡ Pipeline A — Sarvam (Hinglish Optimized)

```
Vobiz WebSocket (mulaw 8 kHz)
  │
  ├──► Deepgram Nova-3  (STT, Hindi/Hinglish, interim + final)
  │         │
  │    ┌────┴──────────────────────────────────────┐
  │    │  Transcript Processing                     │
  │    │  • Confidence filter  (< 0.65 → dropped)  │
  │    │  • Barge-in detection (Immediate stop)     │
  │    └────┬──────────────────────────────────────┘
  │         │  
  │    Sarvam 30B LLM  (Streaming, Tool calling)
  │         │
  │    ┌────┴───────────────────────────────────────────┐
  │    │  Tool execution (pharmacy_functions.py)         │
  │    │  • check_available_slots → Google Calendar      │
  │    │  • book_appointment   → Sheets + Calendar + Email│
  │    └────┬───────────────────────────────────────────┘
  │         │  
  │    Sarvam Bulbul v2 TTS  (Natural Hindi Voice)
  │         │
  └─────────┤
            ▼
     Vobiz WebSocket (playAudio)
```

| Component | Technology |
|---|---|
| **STT** | Deepgram **Nova-3** — Optimized for Indian accents and Hinglish. |
| **LLM** | Sarvam **sarvam-30b** — Best-in-class Hindi reasoning. |
| **TTS** | Sarvam **Bulbul v2** — Human-like Hindi voice. |
| **Barge-in** | Low-latency interruption handling (Priya stops talking the moment you do). |

---

## 🚀 Pipeline B — Google Gemini (Low Latency)

```
Vobiz WebSocket (mulaw 8 kHz)
  │
  ├──► Upsample 8kHz → 16kHz ──► Gemini Live WebSocket
  │                                   │  (STT + LLM + TTS in one)
  │                                   │  tool calls → pharmacy_functions.py
  │         Downsample 24kHz → 8kHz ◄─┘
  └─────────────────────────────────►  Vobiz WebSocket (playAudio)
```

| Component | Technology |
|---|---|
| **Model** | Gemini **3.1 Flash Live** |
| **Voice** | Aoede (Native Gemini Voice) |
| **Advantage** | Native multimodal support for fastest possible response times. |

---

## 📅 Smart Booking Logic

*   **Real-time Availability**: Checks your Google Calendar for current bookings before offering slots.
*   **Natural Time Parsing**: Understands "साढ़े छह" (6:30), "परसों" (day after tomorrow), and "कल सुबह" (tomorrow morning).
*   **Name Correction**: If a parent says "नहीं, बच्चे का नाम कबीर है" (No, the child's name is Kabir), Priya immediately updates the record.
*   **One-Slot Policy**: Offers the best available slot first to minimize conversation time.
*   **Past-Time Guard**: Never books an appointment for a time that has already passed.

---

## 📊 Knowledge Base (New!)

You can now upload **Clinic PDFs, Doctor Lists, or Fee Structures** via the dashboard. Priya will automatically read these documents and use them to answer caller questions accurately without any extra training.

---

## 📈 Dashboard & Monitoring

The built-in dashboard provides:
*   **Live Provider Switching**: Toggle between Sarvam and Gemini instantly.
*   **Knowledge Base Manager**: Upload and manage your clinic's documentation.
*   **Cost Analysis**: Track every cent spent on STT, LLM, and TTS.
*   **Call Recordings**: Listen to stereo recordings (Caller on Left, Priya on Right).
*   **Latency Metrics**: Monitor Time-to-First-Token (TTFT) and end-to-end response times.

---

## 🛠️ Project Structure

```
app.py                    — Main Server (aiohttp)
app_config.json           — Persona, Clinic Hours, and Prompts
pharmacy_functions.py     — Core Tools (Booking, Calendar, Sheets)
knowledge_base/           — Uploaded documents for AI context
recordings/               — Stereo call recordings
metrics/                  — Performance and cost tracking
```
state** | `audioop.ratecv()` state preserved across chunks — no resampling artifacts |
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
| `GEMINI_API_KEY` | Google | [Google AI](https://ai.google.dev/) |
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
