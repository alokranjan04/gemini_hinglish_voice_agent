# Product Requirements Document (PRD)
# Priya: AI Clinic Receptionist — Solving the Missed Call Problem

**Product:** Priya Voice AI  
**Version:** 1.0 — Production  
**Author:** Founder  
**Date:** April 2026  
**Status:** Active — Live in Production

---

## 1. Executive Summary

Neha Child Care is a pediatric clinic that receives inbound calls from parents booking appointments for their children. The clinic's front desk is often occupied during peak hours, and calls go unanswered after hours.

Priya is an AI voice receptionist that answers every forwarded call in natural Hinglish, collects patient details, checks slot availability, books appointments to Google Calendar, records the booking in a Google Sheet, and sends a confirmation email with a calendar invite to the doctor. Every call is recorded and summarised automatically.

Priya is live in production. This document reflects the implemented system as of April 2026.

---

## 2. Problem Statement

### 2.1 Primary Problems

**Problem 1: Missed inbound calls**
- Calls during peak consultation hours and after-hours go unanswered
- Parents who cannot reach the clinic often book elsewhere
- A single unanswered call can represent a lost appointment

**Problem 2: Front-desk overload**
- The receptionist handles walk-ins, billing, and phone calls simultaneously
- High call volume during morning hours creates a bottleneck
- Manual appointment entry is error-prone

**Problem 3: No call records or transcripts**
- There is no log of what was discussed on each call
- The doctor has no visibility into after-hours enquiries
- No automated summary reaches the doctor after each call

### 2.2 Root Cause

- Patients speak Hinglish — IVR and English-only systems fail them
- No system answers calls 24/7 without staff
- Appointment data is not captured automatically from phone calls

---

## 3. Goals

### Implemented (v1.0)

1. Answer 100% of forwarded calls with a warm, natural Hinglish greeting
2. Collect patient name, child's problem/reason, parent name, age, preferred slot, and contact number
3. Check real-time slot availability via Google Calendar
4. Book confirmed appointments to Google Calendar + Google Sheets
5. Cancel or reschedule existing appointments by name or phone number
6. Handle name-correction mid-conversation (e.g. caller says wrong name then corrects it)
7. Send a booking confirmation email with .ics calendar attachment to the doctor
8. Record every call as a stereo WAV (caller left, Priya right)
9. Generate and email an AI call summary + full transcript to the doctor after every call
10. Track call metrics (TTFT, duration, cost, outcome) in a live dashboard

### Not Implemented (Explicit Out-of-Scope)

- Outbound reminder calls (Phase 2)
- WhatsApp confirmations to patients (Phase 2)
- Multi-clinic support (Phase 2)
- Patient-facing portal or mobile app (Phase 3)
- Clinical advice or triage (never — hard guardrail)
- Insurance or billing handling (never)

---

## 4. User Personas

### Persona 1: Dr. Neha — Pediatrician, Clinic Owner

**Background:** Runs a solo pediatric practice. Sees 20–40 patients daily. One receptionist. Consultation bookings are the primary revenue driver.

**Pain:** Calls missed during consultations. No record of after-hours enquiries. Manual appointment entry occasionally creates double-bookings.

**Motivation:** "I want every call answered. And I want to know what was discussed without listening to every recording."

**Success metric:** Zero missed bookings. Automatic summary in inbox after every call. Clean appointment sheet with no column mix-ups.

---

### Persona 2: Receptionist

**Background:** Handles walk-ins, billing, and phone simultaneously. 3–4 hours of peak activity in the morning.

**Pain:** Cannot answer the phone while a parent is at the desk. Misses calls, feels responsible.

**Motivation:** Wants the AI to handle routine booking calls so she can focus on the in-person experience.

**Success metric:** Fewer interruptions. AI handles after-hours calls completely.

---

### Persona 3: Calling Parent

**Background:** Parent of a young child. Calls during lunch break or in the evening. Speaks Hinglish. Wants a quick booking without navigating a menu.

**Pain:** Calls go unanswered. Has to call multiple times.

**Motivation:** "Just book my child's appointment quickly."

**Success metric:** Appointment booked in one call under 3 minutes. Gets a confirmation.

---

## 5. Feature Requirements

### F1 — Inbound Call Handling [Implemented]

- System answers every forwarded call immediately
- Greets in warm Hinglish: *"Namaste! Neha Child Care mein aapka swagat hai..."*
- Identifies intent from first utterance (book / cancel / reschedule / info)
- Handles concurrent calls independently (each call is an isolated async session)

---

### F2 — Appointment Booking [Implemented]

Collects in natural conversation (any order):
- Patient (child) name
- Reason / symptoms / problems
- Parent name
- Child's age
- Preferred appointment slot
- Contact phone number

Then:
- Calls `check_availability` → confirms slot is free in Google Calendar
- Calls `book_appointment` → creates Calendar event + writes Sheet row + sends .ics email
- Verbally confirms the booking to the caller

**Name correction handling:**
If caller says the wrong name and then corrects it mid-conversation (e.g. "Krishna नहीं, Trishna है"), Priya:
1. Cancels the incorrectly-named appointment (`cancel_appointment`)
2. Immediately re-books with the correct name, same reason and slot (`book_appointment`)
3. Does not ask the caller to repeat the reason or slot — uses what was already collected

---

### F3 — Cancel / Reschedule [Implemented]

- Looks up appointment by patient name or contact number in Google Sheets
- `cancel_appointment`: marks Sheet column D as `Cancelled`, deletes Calendar event
- `reschedule_appointment`: cancel + rebook in sequence
- Handles cases where no existing appointment is found gracefully

---

### F4 — Post-Call Processing [Implemented]

After every call (in the `finally` block):

1. **Recording saved:** Stereo WAV to `recordings/` — caller (left) + Priya (right), wall-clock aligned
2. **AI summary generated:** Single-sentence outcome summary (Gemini Flash / Sarvam LLM)
3. **Call summary email sent:** HTML email to `DOCTOR_EMAIL` with summary + full transcript
4. **Metrics logged:** TTFT, duration, tool calls, outcome written to `metrics/call_log.jsonl`

---

### F5 — Metrics Dashboard [Implemented]

Served at `GET /` on the app server:
- Total calls, bookings, cancellations, reschedules
- Average TTFT, session duration
- Estimated API cost per call and total
- Recent call log with outcome and duration

---

### F6 — Call Recording Playback [Implemented]

- WAV files accessible at `GET /recordings/{filename}`
- Stereo format allows the doctor to hear both sides clearly
- Filenames keyed to call SID and timestamp

---

## 6. Google Sheets Column Layout

All bookings are written to `Sheet1` in this fixed column order:

| Column | Field |
|--------|-------|
| A | Patient Name (child) |
| B | Patient Problems / Reason |
| C | Parent's Name |
| D | Is Appointment Booked (`Yes` / `Cancelled`) |
| E | Booking Timestamp |
| F | Child Age |
| G | Preferred Slot |
| H | Contact Number |

Lookups search column A for name and column H for phone number. Cancelled rows are skipped in lookup.

---

## 7. AI Guardrails (Hard Rules)

Priya must **never** do the following — these are enforced in the system prompt and cannot be overridden by the caller:

1. Give medical advice, diagnoses, or treatment recommendations
2. Tell a parent whether a symptom is serious or not
3. Advise on medication, dosage, or home treatment
4. Confirm or deny anything about a previous consultation's clinical findings
5. Share one patient's information with another caller

If any of these are triggered:
*"Yeh cheez main nahi bata sakti — aapko directly doctor se baat karni chahiye."*

---

## 8. Call Flow (Happy Path — New Booking)

```
1. Parent calls clinic number → Vobiz forwards to Priya
2. Priya: "Namaste! Neha Child Care mein aapka swagat hai. 
           Main Priya hoon, AI receptionist. Kaise madad kar sakti hoon?"
3. Parent: "Appointment book karni hai"
4. Priya collects: child name, problem, parent name, age, preferred time
5. Priya: check_availability → "Kal 10 baje available hai"
6. Parent confirms slot
7. Priya: book_appointment → Calendar event created, Sheet row written
8. Priya: "Appointment confirm ho gayi. Dr. Neha ko email bhej di gayi hai."
9. Call ends
10. Post-call: recording saved, summary emailed to doctor, metrics logged
```

---

## 9. Call Flow — Name Correction

```
1. Parent books appointment for "Krishna"
2. book_appointment called → booking created for "Krishna"
3. Parent: "Ek second — naam Krishna nahi, Trishna hai"
4. Priya: cancel_appointment("Krishna") → cancels old booking
5. Priya: book_appointment("Trishna", same reason, same slot) → new booking
6. Priya: "Bilkul. Trishna ke naam se appointment update kar di."
   (Does NOT ask for reason or slot again)
```

---

## 10. Tech Stack Summary

| Component | Technology |
|-----------|-----------|
| Server | Python 3.11, aiohttp |
| Telephony | Vobiz.ai (16kHz Linear PCM) |
| STT | Deepgram Nova-3 (streaming) |
| LLM (primary) | Sarvam-2B-Instruct 30B (streaming) |
| TTS (primary) | Sarvam Bulbul v2 |
| LLM + audio (alternative) | Google Gemini 2.0 Flash Live |
| Calendar | Google Calendar API (service account) |
| Booking sheet | Google Sheets API |
| Confirmation email | Gmail SMTP + .ics attachment |
| Recording | WAV stereo PCM-16 LE 8kHz |
| Metrics | Local JSONL + HTML dashboard |

---

## 11. Deployment

### Google Compute Engine (Production)

- Region: `us-central1` (Iowa)
- Instance: GCE Ubuntu 22.04 LTS
- Format: Dockerized Container (Running as `priya` non-root)
- CI/CD: GitHub Actions → Artifact Registry → GCE SSH Auto-deploy on every push to `main`
- Persistence: Google Sheets & Calendar (Real-time sync)

### VPS / Self-Hosted

- Ubuntu 22.04 + nginx (TLS termination, WebSocket proxy) + systemd
- One-command setup: `sudo bash deploy/setup.sh your.domain.com`
- One-command update: `sudo bash deploy/update.sh`

---

## 12. Success Metrics (Production Targets)

| Metric | Target |
|--------|--------|
| Call answer rate | 100% (no drops) |
| Booking completion rate | > 80% of booking-intent calls |
| TTFT (p95) | < 1.5 seconds |
| Recording completeness | 100% of calls saved (no truncation) |
| Post-call email delivery | 100% (sent in `finally` block) |
| Zero double-bookings | Enforced by Calendar free/busy check |
| Name-correction success | 100% — old booking cancelled, new one created |
