# Priya — AI Voice Receptionist for Neha Child Care

> A fully working AI receptionist for a children's clinic in India, built for almost ₹0.

She answers calls, books appointments, updates Google Calendar & Sheets, sends confirmation emails, and speaks fluent Hinglish.

---

## The Problem

Small clinics in India miss 40–60% of incoming calls. Receptionists are expensive, burned out, and unavailable at night. Parents calling about sick children get voicemail.

This project fixes that with AI — without the ₹50,000/month SaaS price tag.

---

## The Stack (nearly free)

| Component | Technology | Cost |
|---|---|---|
| AI Engine | Google Gemini 3.1 Flash Live (`BidiGenerateContent`) | Free tier |
| Telephony | Vobiz.ai (Indian market, 16kHz WebSocket) | Low cost |
| Calendar | Google Calendar API | Free |
| Booking Log | Google Sheets API | Free |
| Email | Gmail SMTP | Free |
| Backend | Python AsyncIO + WebSockets | Free |

**Total infra cost: ~$0/month on free tiers**

---

## Architecture

```
Caller → Vobiz WebSocket → Python Bridge → Gemini Live BidiGenerateContent
                                              ↓ (function calls)
                                    Google Calendar + Sheets + Gmail
```

No STT. No TTS. No orchestration layer.

Gemini receives raw PCM audio and returns raw PCM audio — one WebSocket, bidirectional. The `BidiGenerateContent` API eliminates the entire STT → LLM → TTS chain that makes most voice agents slow and expensive.

---

## What Priya Can Do

- Answer in natural Hinglish ("Namaste! Neha Child Care mein aapka swagat hai…")
- Book appointments — asks only 3 questions (child name, age, reason)
- Cancel & reschedule existing appointments
- Check real-time slot availability
- Auto-log every call to Google Sheets
- Add calendar events instantly
- Email call summaries after every call
- Handle emergencies ("Please call 112 immediately")

---

## Booking Flow

```
1. Child's name
2. Child's age
3. Reason for visit / problem
→ Check available slots
→ Book appointment (tool call)
→ Confirm verbally + Google Calendar + Sheets + Email
```

- Phone number is captured automatically from the caller ID — never asked
- Parent name is not collected — keeps the conversation short

---

## The Hard Part — Audio Pipeline

Vobiz sends **8kHz Mu-law** audio. Gemini wants **16kHz PCM**. Gemini responds at **24kHz PCM**. Vobiz needs **8kHz Mu-law** back.

Three sample rate conversions per call, bidirectionally, in real time, while preserving `ratecv` state across chunks to avoid audio artifacts at chunk boundaries.

```python
# Inbound: Vobiz → Gemini
mulaw_data = base64.b64decode(payload)
pcm_8k = audioop.ulaw2lin(mulaw_data, 2)
pcm_16k, upsample_state = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, upsample_state)

# Outbound: Gemini → Vobiz
pcm_8k, downsample_state = audioop.ratecv(pcm_24k, 2, 1, 24000, 8000, downsample_state)
mulaw_data = audioop.lin2ulaw(pcm_8k, 2)
```

---

## Project Structure

```
vobiz_main.py          — Main server, WebSocket bridge (Vobiz ↔ Gemini)
pharmacy_functions.py  — Booking logic: Sheets, Calendar, Email
app_config.json        — All script/persona config (edit this, not the code)
google-credentials.json — Google service account credentials
.env                   — API keys
```

### app_config.json
All agent behaviour lives here — greeting, system prompt, clinic hours, booking flow scripts. No code changes needed to customise the agent.

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure .env
```
GEMINI_API_KEY=your_key
GOOGLE_CALENDAR_ID=your_gmail@gmail.com
GMAIL_USER=your_gmail@gmail.com
GMAIL_APP_PASSWORD=your_app_password
DOCTOR_EMAIL=your_gmail@gmail.com
```

### 3. Add Google credentials
Place your service account JSON as `google-credentials.json` in the project root.

Share your Google Sheet and Google Calendar with the service account email.

### 4. Run
```bash
python vobiz_main.py
```

### 5. Expose with ngrok
```bash
ngrok http 5050
```

Set your Vobiz webhook Answer URL to:
```
https://your-ngrok-url.ngrok-free.app/answer
```

---

## Google Credentials

The service account needs:
- **Google Sheets**: Share the booking sheet with the service account email as Editor
- **Google Calendar**: Share your calendar with the service account email with "Make changes to events" permission

---

## Built by

**Alok Ranjan**

If you're building something similar, have questions about the stack, or just want to geek out about voice AI — feel free to connect on LinkedIn or open an issue.

---

## Tags

`voice-ai` `gemini-live` `hinglish` `healthcare-ai` `india` `python` `asyncio` `zero-cost` `vobiz` `google-calendar` `appointment-booking`
