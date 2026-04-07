# 📄 Product Requirements Document: Smart Voice Receptionist

**Author:** Product Manager & Consultant  
**Status:** MVP v1.0 (Deployed)  
**Objective:** Automate the healthcare front-desk using Native Speech-to-Speech (S2S) AI.

---

## 1. Problem Statement
Small-to-medium medical clinics face high administrative overhead. Receptionists are often overwhelmed by routine appointment calls, leading to:
- 📉 **Missed Leads**: Calls go unanswered during peak hours.
- ⏳ **High Latency**: Traditional IVRs frustrate worried parents.
- ❌ **Human Error**: Appointment details are incorrectly entered into spreadsheets.

## 2. Solution Overview
A native Voice AI Assistant (Priya) that functions as a 24/7 front-desk agent. Unlike traditional bots, she speaks natural **Hinglish**, operates with **human-speed latency**, and has **full agency** to book appointments and log patient data.

## 3. Core User Personas
1.  **The Parent (End-User)**: Needs to book a slot quickly for their child without waiting on hold.
2.  **The Doctor (Stakeholder)**: Needs a clean, automated list of their daily appointments.
3.  **The Clinic Manager (Admin)**: Needs a transparent record of all incoming leads and calls.

## 4. Feature Requirements

### MVP (v1.0) - Currently Implemented
| Feature | Description | Business Value |
| :--- | :--- | :--- |
| **Native S2S** | Near-zero latency conversation. | Patient Trust & Retention. |
| **GCal Sync** | Direct booking on Google Calendar. | Operational Efficiency. |
| **GSheet Logs** | Instant row logging of call data. | Auditability & Lead Tracking. |
| **Email Summary** | Post-call clinical briefing for doctors. | Actionable Data. |
| **Localization** | Native Hinglish support. | Cultural Alignment & Accuracy. |

### Future (v2.0) - Roadmap
- **Multi-Cloud Fallback**: Switching between Google & Azure to ensure 100% uptime.
- **Sentiment Analysis**: Detecting high-urgency/emergency calls vs. routine ones.
- **Cost Dashboard**: Real-time tracking of token usage and cost-per-appointment.

## 5. Success Metrics (KPIs)
- **Latencv (TTFB)**: Response time < 500ms.
- **Booking Accuracy**: 95%+ correctness on name/number capture.
- **Task Completion Rate**: Percentage of calls resulting in a successful log.

---

## 6. Competitive Advantage
- **Platform Agnostic**: Not locked to a single cloud; designed for a Multi-Provider future.
- **Legacy Integration**: Built to work with the tools clinics already use (Sheets, Calendar).
