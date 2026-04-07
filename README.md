# Omni-Voice: Native Speech-to-Speech Architecture for Specialized Healthcare

## 1. Project Introduction
Omni-Voice is a high-performance, low-latency artificial intelligence receptionist designed specifically for small-to-medium medical practitioners. By leveraging native multimodal processing, the system addresses the critical bottleneck of patient intake and appointment management, ensuring 24/7 availability and operational efficiency.

## 2. Product Value Proposition (The "Why")
In the healthcare sector, administrative friction often leads to revenue leakage and diminished patient trust. Traditional IVR (Interactive Voice Response) systems suffer from high cognitive load and excessive menu-depth. Omni-Voice replaces this with a conversational interface that understands context, local dialects (Hinglish), and intent, directly integrating with the clinic's administrative stack to provide:
- **Instant Response**: Eliminating wait times for booking and inquiries.
- **Data Integrity**: Reducing manual transcription errors in patient records.
- **Operational Scalability**: Allowing staff to focus on high-acuity clinical tasks rather than routine scheduling.

## 3. Technology Stack Deep-Dive (The "What")

### 3.1 Google Gemini 3.1 Multimodal Live
The core reasoning engine uses the `gemini-3.1-flash-live-preview` model. Unlike standard LLMs that require separate Speech-to-Text (STT) and Text-to-Speech (TTS) modules, Gemini 3.1 Live processes audio natively via a Bidirectional (Bidi) stream. 
- **Effectiveness**: This architecture reduces Time to First Byte (TTFB) significantly by eliminating the latency inherent in sequential transcription and synthesis.
- **Multimodality**: The model maintains a stateful understanding of audio nuances, allowing for a more human-like "patience" and turn-taking logic.

### 3.2 Twilio Media Streams
Connectivity to the Public Switched Telephone Network (PSTN) is managed via Twilio. The system utilizes Twilio Media Streams to fork and stream raw audio data in real-time over WebSockets.
- **Protocol**: Twilio provides G.711 Mu-law audio at an 8,000Hz sampling rate.
- **Real-time Control**: Twilio allows the system to receive and inject audio dynamically, enabling the AI to interrupt or be interrupted naturally.

### 3.3 Python AsyncIO and WebSockets
The middleware is a custom-built asynchronous Python bridge. Using `asyncio` and the `websockets` library, the server manages two concurrent, full-duplex streams:
- **Twilio-to-Gemini**: Uplink for user audio frames.
- **Gemini-to-Twilio**: Downlink for agent audio responses.

## 4. Architectural Implementation (The "How")

### 4.1 The Audio Translation Bridge
Telephony audio (8kHz Mu-law) is fundamentally incompatible with the required input for multimodal AI (24kHz PCM). The system performs high-frequency signal processing:
1. **Mu-law to Linear PCM**: Converting telephony compression to raw 16-bit integers.
2. **Resampling**: Upsampling/Downsampling between 8kHz and 24kHz using `audioop` to maintain fidelity across mismatched audio standards.

### 4.2 The Turn-Taking and Message Loop (Bidi Protocol)
The system implements the Google Bidi-Wire protocol. Each message is a JSON object containing either `serverContent` (audio/text) or `toolCall`.
- **inputTranscription**: The system is configured to receive top-level transcription events, providing a textual record for post-call analytical processing even while maintaining the performance of native audio.
- **Sentiment and Persona**: A dynamic system instruction is injected at the start of every call, defining the agent's identity and conversational boundaries (e.g., patient pacing and confirmation requirements).

### 4.3 The Tool Execution Layer (Function Calling)
The AI has direct agency through Function Calling. When the model identifies an intent (e.g., "Book an appointment"), it pauses the audio loop and issues a JSON `toolCall`.
- **Google Calendar API**: Real-time slot assessment and event injection.
- **Google Sheets API**: ETL (Extract, Transform, Load) logging of كل call data for business intelligence.
- **SMTP/Gmail API**: Post-session NLP summarization and clinical briefing dispatch.

### 4.4 Flow Architecture Diagram
```mermaid
graph TD
    A[PSTN/User Phone] <--> B[Twilio Voice Engine]
    B <--> C[Twilio Media Stream / 8kHz Mu-law]
    C <--> D[Python Bridge / Mu-law-to-PCM Translation]
    D <--> E[Gemini 3.1 Live API / 24kHz PCM]
    E -- JSON Tool Call --> F[Tool Execution Engine]
    F --> G[Google Calendar API]
    F --> H[Google Sheets API]
    F --> I[SMTP Analytics Dispatch]
