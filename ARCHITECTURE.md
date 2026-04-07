# 🏗️ Technical Architecture: Omni-Voice Native S2S

This document outlines the technical design of the Native Speech-to-Speech (S2S) bridge. The architecture is designed for **Near-Zero Latency** and **Legacy Compatibility.**

---

## 1. Dual-Protocol Audio Bridge

The core of the system is an asynchronous WebSocket bridge that translates between telephony standards and multimodal AI requirements.

*   **Ingress (Twilio)**: Streams 8kHz G.711 Mu-law audio.
*   **Translation Layer**: Uses `audioop` to convert Mu-law to 16-bit PCM (Linear16).
*   **Egress (Gemini)**: Streams 16-bit PCM at 24kHz to the `BidiGenerateContent` endpoint.
*   **Synthesis**: Gemini generates the response natively as PCM audio, which the bridge downsamples back to 8kHz Mu-law for the Twilio stream.

## 2. Asynchronous Event Loop

Built on `asyncio`, the system manages three concurrent tasks during a live call:
1.  **Twilio Receiver**: Buffers incoming user audio and forwards it to Gemini.
2.  **Gemini Receiver**: Processes multimodal responses, including tool calls and audio/text chunks.
3.  **Heartbeat/Monitoring**: Maintains connection health and handles cleanup on disconnect.

## 3. Distributed Integration Layer (The Toolkit)

The agent uses **Function Calling** to interact with external business logic.
- **State Management**: The `pharmacy_functions.py` module acts as the source of truth for clinic availability.
- **Integration Registry**: A `FUNCTION_MAP` maps JSON tool calls to Python execution logic for Google Calendar and Sheets.
- **Security**: Authentication is managed via a dedicated Google Service Account with scoped IAM permissions.

## 4. Post-Call Analytical Pipeline

Once the WebSocket closes, a secondary asynchronous block triggers:
- **Transcription Reconstruction**: Merges `inputTranscription` and `outputTranscription` into a unified dialogue log.
- **AI Summary**: Uses a standard Gemini Flash 1.5 instance to extract clinical intent and outcomes.
- **Notification**: Dispatches HTML reports via SMTP (Gmail) to the clinic owner.

---

## 5. Vobiz Native Audio Pipeline (16kHz)

The system now supports **Vobiz.ai** for localized Indian deployments.
- **Superior Fidelity**: Unlike Twilio's 8kHz Mu-law, Vobiz supports **16kHz Linear PCM** natively.
- **Latency Reduction**: By matching Gemini's native 16kHz input requirements, we eliminate the Mu-law-to-PCM translation and resampling steps, reducing total round-trip time (RTT).

## 6. Observability Framework (Call Telemetry)

The agent now includes a professional observability layer to track production KPIs:
- **TTFT (Time to First Token)**: Measured from the moment the user stops speaking to the first byte of AI audio.
- **Session Duration**: Precise tracking of billable conversation time.
- **Multi-Modal Costing**: Real-time estimation of Gemini API costs based on model turn density.

## 7. Multi-Cloud Ready Pattern

The architecture follows a **Provider Interface Pattern**. By separating the core logic from the telephony provider (`twilio_handler` vs `vobiz_handler`), the system is now vendor-agnostic and ready for future integrations.
