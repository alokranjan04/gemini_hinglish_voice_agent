# Product Requirements Document — Jyotish Mitra

**Version:** 2.5 | **Last Updated:** April 2026 | **Status:** Live in Production

---

## 1. Product Vision

> **"Make world-class Vedic astrological guidance available to every Indian, anytime, in their own language — through a simple phone call."**

Jyotish Mitra is a voice-first AI product that provides personalized Vedic astrology consultations over a standard phone call (no app required) and delivers a detailed kundali report to the user's email. It behaves like a warm, knowledgeable human astrologer — not a scripted IVR.

---

## 2. Market Context & Opportunity

### Why Now

| Metric | Data |
|---|---|
| India astrology app market (2024) | **$163M, growing at 49% CAGR → $1.8B by 2030** |
| Broader spiritual services market | **$4.8B, growing at 10% CAGR** |
| Indians who consult astrologers | **38% of the population** |
| Astro-tech startups in India | **950+ startups; only 65 funded** |
| AstroTalk FY24 revenue | **₹651 Cr — proving massive demand exists** |
| Traditional astrologer cost | **₹500–₹5,000+ per session** |
| GenAI market in India | **$1.1B (2025) → $8.3B by 2030 at 34.4% CAGR** |

### Why Voice-First

| Metric | Data |
|---|---|
| Monthly voice search users in India | **840M** |
| Voice adoption growth vs text | **3x faster** |
| Indians consuming Indic-language content | **870M (98% of internet users)** |
| Rural internet users | **488M, growing 2x faster than urban** |
| Smartphone penetration | **85.5% of households** |

**Key insight:** The astrology market's next billion users will not be won by a better UI. They will be won by a better conversation — in their language, on their device, at any hour.

---

## 3. Target Users

### Primary — The First-Time Caller
- Age 25–55, lives in Tier 1/2/3 Indian city
- Believes in astrology but finds quality astrologers expensive or hard to access
- Comfortable with Hindi/Hinglish
- Owns a smartphone; may not install new apps
- Has a specific concern: career stagnation, marriage timing, financial decision

**Goal:** Receive trustworthy, personalized astrological guidance quickly and affordably.

### Secondary — The Returning Caller
- Has already had one consultation
- Wants to follow up on previous predictions or ask about a new concern
- Expects the agent to remember their details without repeating them

**Goal:** Pick up the conversation where it left off, like calling a trusted astrologer back.

---

## 4. Functional Requirements

### FR1 — Introduction & Consent
- **FR1.1** The agent MUST introduce itself before collecting any user data.
- **FR1.2** Introduction must explain: who the agent is, what value it provides, and why it needs birth details.
- **FR1.3** Agent must wait for user to agree ("haan", "yes", "theek hai") before proceeding to data collection.
- **FR1.4** The introduction must NOT immediately ask for the user's name.

### FR2 — Birth Detail Collection (One Question at a Time)
- **FR2.1** Collect Name, Date of Birth, Time of Birth, Place of Birth — one per turn.
- **FR2.2** NEVER ask two questions in the same response.
- **FR2.3** When asking for Time of Birth, ALWAYS ask AM/PM in the same question: *"Subah ka tha ya raat ka — dono bata dijiye."*
- **FR2.4** If user provides time without AM/PM, ask immediately before proceeding.
- **FR2.5** NEVER assume AM or PM.

### FR3 — Confirmation Gate (Non-Negotiable)
- **FR3.1** After collecting all 4 birth details, the agent MUST read them all back in one response:
  *"Ek baar confirm kar leti hoon — Naam: X. Janam Tithi: DD Month YYYY. Samay: HH:MM SUBAH/RAAT. Sheher: X. Kya ye sab bilkul sahi hai?"*
- **FR3.2** The full 4-digit year MUST be stated aloud (not "85", not "81" — always the full year).
- **FR3.3** The AM/PM must be stated as SUBAH (morning) or RAAT (night) — not "AM/PM".
- **FR3.4** Agent CANNOT proceed to email collection or analysis without an explicit YES from the user.
- **FR3.5** If the user corrects anything, the agent MUST fix it and read back the ENTIRE block again from scratch.

### FR4 — Birth Time Rectification
- **FR4.1** After confirmation, ask for 2 major life events to rectify the birth time.
- **FR4.2** Ask for events one at a time: marriage, job change, accident, major move, etc.
- **FR4.3** Both events must include approximate year and what happened.
- **FR4.4** Use events to refine the astrological interpretation (not just collect data).

### FR5 — Email Collection & Verification
- **FR5.1** After rectification, ask for the user's email address.
- **FR5.2** Verify the email in the NEXT response: *"Maine note kar liya: [email]. Kya ye sahi hai?"*
- **FR5.3** Do NOT proceed until user confirms.

### FR6 — Consultation Delivery
- **FR6.1** After email confirmed, deliver 2–3 sharp personality insights from the kundali.
- **FR6.2** Include 1 emotionally resonant observation (overthinking, trust issues, delayed success, etc.).
- **FR6.3** Ask ONE question: "Aapki sabse badi tension kya hai — Career, Paise, Love, ya Health?"
- **FR6.4** Give deep, specific insights on the chosen concern — one point at a time.
- **FR6.5** Reference current Mahadasha/Antardasha and give 1–2 year predictions.
- **FR6.6** Agent MUST position itself as the guide — never ask the user to "refer to their kundali" or check their own chart.

### FR7 — Report Generation & Email Delivery
- **FR7.1** After verbal analysis, send a full Kundali report to the confirmed email.
- **FR7.2** Report MUST include a South Indian 4×4 Kundali chart with planet positions calculated from birth details.
- **FR7.3** Report MUST include a detailed 1,500-word Hindi analysis with 7 sections (see §7).
- **FR7.4** Report MUST include the full conversation transcript, formatted as styled chat bubbles.
- **FR7.5** Report must be generated via a dedicated Gemini text API call (not the voice session output).
- **FR7.6** Email subject: `✦ [Name] Ji — Aapki Vistar Kundali Report | ज्योतिष मित्र`

### FR8 — Returning Caller Experience
- **FR8.1** Identify returning callers by their phone number (Caller ID).
- **FR8.2** Greet by name and reference the last topic discussed.
  *"Namashkar [Name] ji! Aapki kundali mere paas hai. Mujhe yaad hai ki aapne [last_topic] ke baare mein poocha tha. Aaj main aapko kis tarah madad kar sakti hoon?"*
- **FR8.3** Do NOT ask returning callers for birth details again — already stored.
- **FR8.4** Jump directly to concern selection and analysis.

### FR9 — Session Memory
- **FR9.1** At the end of every call, save: name, DOB, TOB, POB, email, last_topic, planets, conversation_summary, last_call_date, call_count.
- **FR9.2** Memory must be saved even if the call ends abruptly (auto-save in finally block).
- **FR9.3** Memory must MERGE with existing records — not overwrite.
- **FR9.4** `call_count` must increment on every call.

### FR10 — Barge-In Support
- **FR10.1** User must be able to interrupt the AI mid-sentence at any time.
- **FR10.2** On Gemini `interrupted` event: send `clearAudio` to Vobiz immediately.
- **FR10.3** On user transcription detected: send `clearAudio` again as a second layer.
- **FR10.4** AI must not repeat what it was saying before the interruption.

### FR11 — Voice Quality
- **FR11.1** Use Gemini's `Aoede` prebuilt voice (female, calm, empathetic).
- **FR11.2** Language: Hinglish (natural mix of Hindi and English).
- **FR11.3** Grammar: feminine forms — *"kar rahi hoon"*, *"bata rahi hoon"*, *"samajh sakti hoon"*.
- **FR11.4** Responses must be under 2–3 sentences (voice-optimised for phone).

---

## 5. Non-Functional Requirements

### NFR1 — Latency
- AI response must begin within **< 1 second** of user finishing speech (p50).
- Audio resampling must not introduce perceptible lag.

### NFR2 — Session Duration
- Sessions must remain stable for up to **60 minutes**.
- WebSocket heartbeat every **30 seconds** to prevent Cloud Run idle disconnection.
- Automatic Gemini reconnection on WebSocket drop, without losing session state.

### NFR3 — Report Quality
- Kundali analysis: minimum **1,500 words**, 7 sections, all in Hindi (Devanagari script).
- Planet positions must be **calculated from birth data**, not hardcoded defaults.
- Gemini text API call must use a **90-second timeout** to allow full generation.

### NFR4 — Accuracy
- Birth details must achieve **>95% collection accuracy** via the confirmation gate.
- AM/PM must be explicitly confirmed — never inferred.
- Year must be stated in full (4 digits) during confirmation.

### NFR5 — Reliability
- Post-call transcript email must be sent even if the report tool was never triggered.
- Memory auto-save must execute even if the conversation was cut short.
- `report_sent` flag prevents duplicate emails.

### NFR6 — Security
- All secrets (API keys, SMTP credentials, GCS keys) via environment variables / GitHub Secrets.
- GCS service account JSON excluded from version control via `.gitignore`.
- Audio processed in-memory only; not persisted to disk.

---

## 6. Conversation Flow Specification

```
STEP 0  INTRODUCTION
        Agent introduces itself, explains purpose and privacy.
        Waits for: "haan" / "yes" / "theek hai"

STEP 1  NAME
        "Bahut achha! Sabse pehle apna naam bataiye."

STEP 2  DATE OF BIRTH
        "Aapki janam tithi kya hai?"

STEP 3  TIME OF BIRTH + AM/PM
        "Aur janam ka samay? Subah ka tha ya raat ka — dono bata dijiye."
        If only time given → "Ye [X] subah ka tha ya raat ka?"

STEP 4  PLACE OF BIRTH
        "Aur janam ka sheher kaunsa tha?"

STEP 5  CONFIRMATION GATE  ← HARD BLOCK
        "Ek baar confirm kar leti hoon — Naam: X. Janam Tithi: DD Month YYYY.
         Samay: HH:MM SUBAH/RAAT. Sheher: X. Kya ye sab bilkul sahi hai?"
        Loop until YES. Fix and repeat if anything is wrong.

STEP 6  LIFE INCIDENT 1
        "Janam samay ko sahi karne ke liye 2 badi life events chahiye.
         Pehli ghatna — kab aur kya hua?"

STEP 7  LIFE INCIDENT 2
        "Aur ek aur badi ghatna?"

STEP 8  EMAIL
        "Aapka email address kya hai?"
        Verify next turn: "Maine note kar liya: X. Sahi hai?"

STEP 9  HOOK
        2–3 personality insights + 1 emotional trigger from kundali.

STEP 10 CONCERN
        "Aapki sabse badi tension kya hai — Career, Paise, Love, ya Health?"

STEP 11 DEEP ANALYSIS
        - Current Mahadasha / Antardasha
        - 1–2 year predictions
        - Key strength and challenge
        - Actionable insight

STEP 12 SEND REPORT
        "Main abhi aapki poori Kundali report bhej rahi hoon."
        → Call send_astrology_report tool

STEP 13 SAVE MEMORY
        → Call save_user_profile with full session data
```

---

## 7. Kundali Report Specification

The email report contains four sections:

### Section A — Birth Details Table
Name | Date of Birth | Time of Birth (with AM/PM) | Place of Birth

### Section B — Kundali Chart
South Indian 4×4 grid with:
- All 9 planets placed in their calculated houses (1–12)
- Each planet in its unique colour:

| Planet | Hindi | Colour |
|---|---|---|
| Sun | सूर्य | `#f97316` |
| Moon | चंद्र | `#93c5fd` |
| Mars | मंगल | `#ef4444` |
| Mercury | बुध | `#22c55e` |
| Jupiter | गुरु | `#fbbf24` |
| Venus | शुक्र | `#e879f9` |
| Saturn | शनि | `#94a3b8` |
| Rahu | राहु | `#a78bfa` |
| Ketu | केतु | `#fb923c` |

### Section C — Detailed Analysis (1,500+ words, Hindi Devanagari)
1. **व्यक्तित्व एवं स्वभाव** — Lagna, Rashi, Nakshatra, Ascendant Lord (200+ words)
2. **करियर एवं आर्थिक स्थिति** — 10th, 2nd, 11th house, Raj Yogas (250+ words)
3. **पारिवारिक जीवन एवं विवाह** — 7th, 4th house, Venus, Jupiter (200+ words)
4. **स्वास्थ्य एवं शारीरिक स्थिति** — 6th, 8th house, Moon indicators (150+ words)
5. **विशेष राजयोग एवं दोष** — All major Yogas and Doshas (200+ words)
6. **दशा एवं भविष्यफल** — Mahadasha, Antardasha, 1/3/5 year predictions (200+ words)
7. **ज्योतिषीय उपाय** — 6–7 remedies with mantras, gemstones, rituals (150+ words)

### Section D — Conversation Transcript
Full verbatim transcript of the call, formatted as styled chat bubbles:
- Gold border = user messages
- Amber border = Jyotish Mitra messages

---

## 8. Success Metrics

| Metric | Target |
|---|---|
| Confirmation gate compliance | 100% — no call proceeds without YES |
| AM/PM accuracy | >99% — always explicitly confirmed |
| Report delivery rate | >95% of completed calls |
| Report generation success | >90% (Gemini API) + fallback to voice analysis |
| Session stability (≤60 min) | >99% |
| Returning caller recognition | 100% of same-number calls |
| p50 voice response latency | <1 second |
| Transcript included in email | 100% |

---

## 9. Future Roadmap

### Phase 2 — Database & Scale
- Replace `user_memory.json` with **Firestore** for cross-instance memory
- Support concurrent calls with Cloud Run auto-scaling
- Add WhatsApp delivery channel for the report

### Phase 3 — Advanced Astrology
- Automated birth chart calculation (Swiss Ephemeris integration)
- Accurate Mahadasha/Antardasha calculator based on real birth data
- Navamsa (D9) and Dashamsa (D10) chart generation

### Phase 4 — Monetisation
- Pay-per-report model via UPI (Razorpay/PhonePe integration)
- Premium subscription: unlimited calls + PDF reports
- Referral system for astrologers to white-label

### Phase 5 — Multilingual
- Tamil, Telugu, Marathi, Bengali support
- Dialect-aware voice model selection
- Region-specific astrological traditions (Kerala style, South Indian, etc.)

---

## 10. Dependencies & Constraints

| Dependency | Risk | Mitigation |
|---|---|---|
| Gemini Live API availability | Medium | Reconnect loop with 1s retry |
| Gemini REST API (report gen) | Low | Fallback to voice analysis_html |
| Gmail SMTP | Low | App password; error logged and surfaced |
| Vobiz telephony uptime | Medium | Monitor via Vobiz dashboard |
| `user_memory.json` on Cloud Run | High at scale | Migrate to Firestore in Phase 2 |
| Python 3.11 `audioop` | Low | `audioop-lts` fallback for 3.13+ |
