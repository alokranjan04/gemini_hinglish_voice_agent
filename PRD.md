# Product Requirements Document (PRD)
# Hinglish Voice AI — Outbound Reminders + Inbound Booking for Delhi-NCR Clinics

**Product:** Clinic Voice AI  
**Version:** 1.0 — MVP  
**Author:** Founder  
**Date:** March 2026  
**Status:** Active — Pre-development

---

## 1. Executive Summary

Dental clinics and solo specialist doctors in Delhi-NCR lose ₹80,000–₹1.5 lakh monthly from two fixable problems: missed inbound calls (30–50% of calls go unanswered) and patient no-shows (20–30% of appointments). Current solutions — receptionists, IVR systems, SMS reminders — fail because they can't handle Hinglish, don't operate 24/7, and break under call load.

We are building a voice AI agent that answers every patient call in natural Hinglish, books appointments, and proactively calls patients before appointments to confirm or reschedule. It works via simple call forwarding — no hardware, no app, no IT setup required.

**Target:** Dental clinics (3,500–5,000 in Delhi-NCR) + solo specialist doctors (8,000–12,000 in Delhi-NCR)  
**Primary pain:** Missed bookings from unanswered calls + revenue lost to no-shows  
**Price point:** ₹2,999/month  
**Success definition:** Clinic recovers more in revenue than the subscription costs within 30 days

---

## 2. Problem Statement

### 2.1 Primary Problems

**Problem 1: Missed inbound calls**
- A typical Delhi dental clinic or specialist clinic receives 15–40 calls per day
- 30–50% of these calls go unanswered during peak hours, lunch breaks, and after-hours
- 85% of patients who can't reach a clinic don't call back
- Each missed call that would have been a booking = ₹800–₹2,500 in lost revenue
- After-hours calls (6pm–10pm, when many patients call after work) are universally missed

**Problem 2: No-shows**
- 20–30% of booked appointments are no-shows in Indian outpatient settings
- A clinic with 25 patients/day at ₹1,000/consultation loses ₹62,500–₹93,750/month to no-shows
- Manual reminder calls work (29–39% no-show reduction) but take 3–4 hours of staff time daily
- SMS reminders are unreliable (DLT delays, low engagement), WhatsApp is unmanaged

**Problem 3: Front-desk overload**
- One receptionist cannot simultaneously handle walk-ins, billing, paperwork, and phone calls
- Healthcare front-desk turnover is 25–40% annually — each departure disrupts the practice for 2–3 months
- Staff inconsistency leads to missed callbacks, double bookings, and scheduling errors

### 2.2 Root Cause

Existing tools (IVR, SMS, generic chatbots) fail the Delhi-NCR clinic because:

1. **Language failure:** Patients speak Hinglish (*"Kal morning appointment hai kya?"*). IVR forces "press 1 for Hindi, press 2 for English" — both wrong.
2. **No inbound intelligence:** SMS and WhatsApp can send reminders but can't answer inbound calls or handle real-time scheduling conversations
3. **No 24/7 coverage:** Clinics close. Patients' need to book doesn't.

---

## 3. Goals and Non-Goals

### 3.1 Goals (MVP)

1. Answer 100% of calls forwarded to the AI (zero call drops)
2. Successfully complete inbound appointment bookings end-to-end (book, confirm, send WhatsApp confirmation)
3. Execute outbound reminder campaigns 24h and 2h before appointments in Hinglish
4. Handle appointment rescheduling and cancellation over voice
5. Provide a clinic dashboard showing all AI activity, call logs, and appointment status
6. Deploy to a new clinic in under 5 minutes (call forwarding setup only)
7. Reduce no-shows by minimum 25% within 30 days for any clinic using the product

### 3.2 Non-Goals (MVP — explicitly out of scope)

- Clinical advice, triage, symptom checking (always escalated to human)
- Insurance / billing call handling (Phase 3)
- EMR / Practo / HealthPlix integration (Phase 2)
- ABDM / ABHA ID linking (Phase 2)
- Multi-location / hospital chain deployment (Phase 2)
- Patient-facing mobile app (Phase 3)
- Video consultation scheduling (Phase 3)
- Languages other than Hindi, English, Hinglish (Phase 2 adds Tamil, Bengali, Punjabi)

---

## 4. User Personas

### Persona 1: Dr. Priya Malhotra — Solo Dermatologist, South Delhi

**Background:** 12 years in practice, runs a 1-doctor clinic in Greater Kailash. 28–35 patients daily. One receptionist who also handles billing and walk-ins. Consultation fee ₹1,200.

**Pain:** Misses 8–12 calls daily. Loses entire Sundays to no-shows. Has tried WhatsApp reminders but patients ignore them. Knows she's losing money but doesn't know the exact amount.

**Motivation:** "If something can just pick up the calls and confirm appointments while I'm consulting, I'll try it."

**Objections:** Worried AI will give wrong information. Worried patients will complain. Doesn't want to learn new software.

**Success metric:** Zero missed calls. No-shows drop below 10%.

---

### Persona 2: Dr. Rahul Agarwal — Dental Clinic Owner, Noida Sector 18

**Background:** 3-chair dental clinic, 2 associates, 40–50 patients daily. Has a receptionist but she's overwhelmed. Consultation ₹800–₹1,500. Has tried Practo listing (gets some traffic) but most patients still call.

**Pain:** Receptionist can't handle peak-hour call volume. Patients who get voicemail don't call back. Keeps losing patients to competing clinics that answer faster.

**Motivation:** Heard from a colleague that a Bangalore clinic reduced no-shows significantly with AI reminders. Wants the same.

**Objections:** Price sensitive. Wants to see hard numbers before committing.

**Success metric:** Appointment fill rate goes from 78% to 90%+.

---

### Persona 3: Reena — Clinic Receptionist, Dwarka

**Background:** 3 years at the clinic. Handles calls, walk-ins, billing, insurance paperwork simultaneously. Gets 30–40 calls daily. Loves her job but is chronically stressed during peak hours.

**Pain:** Can't answer phone while handling walk-in patient. Misses calls, feels guilty, gets scolded. Spends 2 hours daily making reminder calls — most go unanswered.

**Motivation:** Wants to focus on patients in front of her, not the phone.

**Success metric:** Phone-related stress eliminated. Can focus on in-person experience.

---

### Persona 4: Patient — Ramesh Kumar, 45, Saket

**Background:** Office worker. Needs to book a dental appointment. Usually calls during lunch break (1–2pm) or evening (7–9pm). Comfortable with Hindi and basic English. Uses WhatsApp daily.

**Pain:** Calls the clinic 3 times, no answer. Goes to a different clinic.

**Motivation:** Wants to book quickly, confirm his slot, and get a reminder.

**Success metric:** Books appointment in one 90-second call, receives WhatsApp confirmation.

---

## 5. Feature Requirements

### 5.1 Feature Priority Framework

| Priority | Label | Meaning |
|----------|-------|---------|
| P0 | Must-have | MVP is unusable without this |
| P1 | Should-have | Core value delivery; high priority |
| P2 | Nice-to-have | Improves experience; Phase 2 candidate |
| P3 | Future | Post-MVP roadmap |

---

### 5.2 Feature List

#### FEATURE GROUP 1: Inbound Call Handling

**F1.1 — 24/7 Inbound Call Answering [P0]**
- System answers every forwarded call within 2 rings
- Greets patient in warm, natural Hinglish with clinic name
- Identifies call intent within first patient utterance
- Handles up to 10 concurrent calls per clinic (configurable)

Acceptance criteria:
- 100% of forwarded calls answered (no drops, no busy signal)
- Greeting delivered within 500ms of call connect
- System handles concurrent calls without audio degradation

---

**F1.2 — Appointment Booking Flow [P0]**
- Collects: preferred date, preferred time range, patient name, mobile number
- Checks real-time slot availability against clinic's schedule
- Offers up to 3 alternative slots if preferred time is unavailable
- Confirms booking verbally and sends WhatsApp confirmation

Acceptance criteria:
- End-to-end booking completed in under 3 minutes (happy path)
- Slot collision rate: 0% (no double bookings)
- Confirmation WhatsApp sent within 60 seconds of booking

User story:
> As a patient calling after-hours, I want to book an appointment without waiting for a human, so that I don't have to call back during work hours.

---

**F1.3 — Reschedule / Cancel Flow [P0]**
- Looks up patient's existing appointment by phone number
- Offers available alternative slots for rescheduling
- Cancels appointment and frees slot if patient can't attend
- Sends updated WhatsApp confirmation

Acceptance criteria:
- Patient identified by phone number in < 1 second
- Rescheduling completed in under 2 minutes
- Cancelled slot available for new bookings immediately

---

**F1.4 — Human Escalation [P0]**
- Immediately transfers to clinic staff in any of these cases:
  - Patient explicitly asks for human
  - Patient mentions pain, emergency, bleeding, or distress
  - AI fails to understand intent after 3 attempts
  - Call is about clinical advice, diagnosis, or medication
- Plays hold music during transfer; informs patient of transfer
- If no staff available: takes callback number and creates task in dashboard

Acceptance criteria:
- Emergency escalation latency: < 3 seconds from trigger
- 100% of "baat karni hai insaan se" intents result in transfer
- Zero instances of AI attempting to answer clinical questions

---

**F1.5 — FAQ Responses [P1]**
- Static responses for common questions (configurable per clinic):
  - Clinic hours
  - Location and directions
  - Consultation fees
  - Doctor names and specializations
  - Parking / access instructions
- Delivered in Hinglish in under 5 seconds

Acceptance criteria:
- FAQ responses accuracy: 100% (static, no generation)
- Clinic admin can update FAQ responses from dashboard in < 2 minutes

---

#### FEATURE GROUP 2: Outbound Reminder System

**F2.1 — T-24h Outbound Reminder Calls [P0]**
- Automatically calls all patients with next-day appointments
- Script: confirms appointment details, asks for yes/no confirmation
- Handles: confirmed (updates DB) / needs to reschedule (starts reschedule flow) / can't attend (cancels, frees slot)
- Retry logic: no-answer → retry after 2 hours (max 3 attempts)

Acceptance criteria:
- Reminder campaigns launch automatically based on appointment data (no manual trigger)
- 80%+ of patients reached within first 3 attempts
- Confirmation status updated in real-time in clinic dashboard

User story:
> As a clinic owner, I want the system to call all patients the day before their appointment so I know exactly how many chairs will be filled tomorrow.

---

**F2.2 — T-48h WhatsApp Reminder [P1]**
- Sends pre-approved WhatsApp template 48h before appointment
- Includes: patient name, doctor name, date, time, clinic address, map link
- Includes: confirm / reschedule links (web-based, no app required)
- Tracks open rate, delivery status

Acceptance criteria:
- WhatsApp delivery rate: > 95%
- Template message compliant with Meta Business API policies
- Link-based confirm/reschedule reflects in appointment DB within 30 seconds

---

**F2.3 — Day-of WhatsApp Nudge [P1]**
- Sends day-of reminder 2 hours before appointment time
- Shorter message: appointment time, doctor name, "See you soon!"
- No action required from patient

---

**F2.4 — Post-Consultation Follow-Up Call [P2]**
- Calls patient 24h after appointment
- Script: "How are you feeling? Any questions about your treatment? Doctor recommends follow-up in [X] weeks — shall I book it?"
- Creates warm lead for re-booking

---

**F2.5 — Lapsed Patient Re-engagement Campaign [P2]**
- Identifies patients who haven't visited in 6+ months
- Outbound call: "Aapki last visit [date] thi. Dr. [Name] recommend karte hain ki aap checkup ke liye aayein. Kya main appointment book karun?"
- Configurable campaign frequency and targeting

---

#### FEATURE GROUP 3: Clinic Dashboard

**F3.1 — Today's Appointment View [P0]**
- Calendar view of all appointments for the day
- Real-time confirmation status (confirmed / unconfirmed / cancelled)
- Color-coded: green = confirmed, amber = unconfirmed, red = cancelled
- Manual override: staff can edit any appointment

---

**F3.2 — Call Log [P0]**
- List of every call handled by AI (inbound and outbound)
- For each call: timestamp, patient name/phone, intent, outcome, duration
- Audio playback and full text transcript for every call
- Search and filter by date, outcome, patient

---

**F3.3 — AI Performance Dashboard [P1]**
- Key metrics: calls handled today / this week / this month
- Booking conversion rate (calls that resulted in appointments)
- Show rate before vs after (rolling 30-day comparison)
- Estimated revenue recovered (no-shows prevented × avg consultation fee)
- Escalation rate (% calls transferred to human)

---

**F3.4 — Reminder Campaign Manager [P1]**
- Toggle reminder types on/off (T-24h call, T-48h WhatsApp, day-of WhatsApp)
- Customize reminder script per clinic
- View campaign history and delivery stats
- Manual campaign trigger for ad-hoc reminders

---

**F3.5 — Clinic Settings [P0]**
- Working hours per day
- Doctor profiles (name, specialization, available days)
- Slot duration (default 15/20/30 min, configurable)
- Consultation fee (used in revenue recovery calculations)
- AI voice preference (female/male, language formality)
- Forwarding number setup instructions

---

**F3.6 — Multi-staff Access [P1]**
- Owner account: full access
- Staff account: view appointments + call logs, limited settings access
- Phone OTP login (no passwords)

---

#### FEATURE GROUP 4: Notifications & Comms

**F4.1 — Patient WhatsApp Confirmations [P0]**
- Automated WhatsApp after every booking: appointment details, doctor name, clinic address
- Automated WhatsApp after reschedule/cancel
- All messages in Hinglish with clinic branding (name, logo)

---

**F4.2 — Clinic Staff Notifications [P1]**
- WhatsApp/SMS to clinic staff when:
  - New appointment booked by AI
  - Patient cancels
  - Emergency escalation triggered
  - Reminder campaign completed (summary)

---

**F4.3 — Daily Summary Report [P2]**
- Automated WhatsApp to clinic owner every evening (7pm)
- "Aaj ka summary: 12 appointments confirmed, 2 cancelled, 3 calls AI ne handle kiye after-hours."

---

### 5.3 Language Requirements [P0]

- **Primary:** Hinglish (Hindi-English code-switched — the dominant mode in Delhi-NCR)
- **Secondary:** Pure Hindi (for patients who don't code-switch)
- **Tertiary:** Pure English (for English-only callers)
- Auto-detect language from first utterance; don't require patient to choose
- Medical terminology recognition in both scripts (Devanagari concept, Roman transliteration)
- Correct pronunciation of Delhi-NCR locality names (Lajpat Nagar, Indirapuram, Sector 18)
- Correct pronunciation of common Indian names

---

### 5.4 Voice Quality Requirements [P0]

- Voice must sound like a trained human receptionist — warm, professional, not robotic
- Response latency: < 1.5 seconds from end of patient speech to AI response start
- No background noise, static, or audio artifacts
- Natural pacing — not rushed, not artificially slow
- Handles: fast speech, slow speech, speech with background noise, elderly speakers

---

## 6. User Stories — Full List

### Inbound Booking

- US-001: As a patient, I want to call a clinic after-hours and successfully book an appointment so that I don't have to call back during work hours
- US-002: As a patient, I want to speak naturally in Hinglish without being forced into a menu so that booking feels easy
- US-003: As a patient, I want to receive a WhatsApp confirmation immediately after booking so that I have a record
- US-004: As a patient, I want to reschedule my appointment over the phone without waiting for a human so that I can manage my schedule
- US-005: As a patient, I want to be transferred to a human staff member if I have a clinical question so that I get the right answer

### Outbound Reminders

- US-006: As a clinic owner, I want all patients to be called the day before their appointment so that I can predict tomorrow's clinic load
- US-007: As a patient, I want to receive a reminder call in my own language so that I don't forget my appointment
- US-008: As a patient, I want to reschedule directly during the reminder call so that I don't have to call back separately
- US-009: As a clinic owner, I want to see which patients confirmed, cancelled, or didn't respond so that I can fill gaps in the schedule

### Dashboard

- US-010: As a clinic owner, I want to see today's appointment status in real-time so that I can plan my day
- US-011: As a clinic owner, I want to listen to any AI call recording so that I can verify call quality
- US-012: As a clinic owner, I want to see how much revenue the AI has recovered so that I can justify the subscription
- US-013: As a clinic receptionist, I want to receive a WhatsApp notification when the AI books a new appointment so that I can prepare
- US-014: As a clinic owner, I want to set up the product by just forwarding my calls so that I don't need technical help

---

## 7. Acceptance Criteria — Critical Paths

### Happy Path 1: After-hours Booking

```
Precondition: Clinic is closed. Patient calls clinic number which forwards to AI.

1. Patient: [calls]
2. AI: "Namaste! Yeh Sharma Dental Clinic hai, main AI receptionist hoon. 
         Appointment book karna chahte hain?"
3. Patient: "Haan, kal ke liye"
4. AI: "Bilkul! Kal ke liye available slots hain — 
         10 baje, 11:30 baje, aur 4 baje. 
         Kaunsa time aapke liye sahi rahega?"
5. Patient: "Subah 10 wala"
6. AI: "Perfect. Aapka naam kya hai?"
7. Patient: "Ramesh Kumar"
8. AI: "Aur aapka mobile number?"
9. Patient: "9876543210"
10. AI: "Theek hai Ramesh ji. Kal 10 baje, Dr. Sharma ke saath 
          appointment confirm ho gayi. WhatsApp par details bhej raha hoon. 
          Koi aur madad?"
11. [WhatsApp confirmation sent within 60 seconds]
12. [Appointment created in DB, visible in clinic dashboard]

Pass criteria:
✓ Call answered within 2 rings
✓ Booking completed < 3 minutes
✓ Zero double-bookings
✓ WhatsApp sent < 60s
✓ Appointment visible in dashboard immediately
```

### Happy Path 2: Outbound Reminder → Reschedule

```
Precondition: Patient has appointment tomorrow at 10am. T-24h reminder fires.

1. AI: [calls patient's number]
2. AI: "Namaste Ramesh ji! Yeh Sharma Dental Clinic se call hai. 
         Kal 10 baje Dr. Sharma ke saath aapka appointment hai. 
         Kya aap aa paenge?"
3. Patient: "Aaj thoda busy hoon, kal nahi aa paunga"
4. AI: "Koi baat nahi. Kya main aapke liye koi aur din book karun? 
         Parso 11 baje ya is week Saturday 3 baje available hai."
5. Patient: "Saturday theek rahega"
6. AI: "Done! Saturday ko 3 baje confirm kar diya. 
         WhatsApp par nayi details bhej raha hoon. Take care!"
7. [Original appointment cancelled, new appointment created]
8. [Freed slot available immediately for other patients]
9. [Updated WhatsApp confirmation sent]

Pass criteria:
✓ Original slot freed within 30 seconds
✓ New slot booked with no collision
✓ WhatsApp with updated details sent
✓ Dashboard reflects both changes
```

---

## 8. Success Metrics

### 8.1 Product Health Metrics

| Metric | Target (Month 1) | Target (Month 3) |
|--------|-----------------|-----------------|
| Call answer rate | 99.5% | 99.9% |
| Booking completion rate (inbound) | 70% | 80% |
| Outbound reach rate (per campaign) | 70% | 80% |
| No-show reduction (vs baseline) | 20% | 35% |
| Human escalation rate | < 25% | < 15% |
| AI response latency (p95) | < 2s | < 1.5s |
| NPS (clinic owners) | > 50 | > 65 |

### 8.2 Business Metrics

| Metric | Target (Month 1) | Target (Month 3) |
|--------|-----------------|-----------------|
| Paying clinics | 10 | 50 |
| MRR | ₹30,000 | ₹1,50,000 |
| Churn rate | < 10% | < 5% |
| Calls handled per clinic/day | 15+ | 20+ |
| Average revenue recovered per clinic/month | ₹30,000+ | ₹50,000+ |

---

## 9. Out-of-Scope Scenarios (Explicit Guardrails)

The AI must **never** do the following. These are hard product guardrails:

1. Provide medical advice, diagnoses, or treatment recommendations
2. Prescribe or advise on medication dosage
3. Tell a patient whether they need to see a doctor urgently vs wait
4. Confirm or deny any clinical information about a previous appointment
5. Share one patient's information with another caller
6. Process payments or discuss payment plans (Phase 3)
7. Handle insurance pre-authorization or TPA queries (Phase 3)

If any of these are attempted by the caller, the AI responds:
*"Yeh cheez main nahi bata sakta — aapko directly clinic staff se baat karni chahiye. Main transfer karta hoon."*

---

## 10. Launch Criteria (Definition of Done — MVP)

The MVP is considered shippable when all of the following are true:

- [ ] Happy Path 1 (inbound booking) passes 100 consecutive test calls with 0 failures
- [ ] Happy Path 2 (outbound reminder → reschedule) passes 50 consecutive test calls with 0 failures
- [ ] Emergency escalation transfers in < 3 seconds for 100% of test triggers
- [ ] No double-bookings detected across 500 simulated concurrent bookings
- [ ] Dashboard loads in < 2 seconds on a 4G mobile connection
- [ ] Call recordings accessible and playable for 100% of logged calls
- [ ] WhatsApp confirmations delivered for 95%+ of bookings in test environment
- [ ] 5 real clinics have completed 30-day free pilot with NPS > 7/10
- [ ] System handles 20 concurrent calls without audio degradation
- [ ] DPDP Act consent flow implemented and auditable
