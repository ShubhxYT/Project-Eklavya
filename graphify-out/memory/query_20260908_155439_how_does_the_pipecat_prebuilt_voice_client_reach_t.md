---
type: "query"
date: "2026-09-08T15:54:39.450964+00:00"
question: "How does the Pipecat prebuilt voice client reach the transport pipeline and interrupt bot audio playback?"
contributor: "graphify"
source_nodes: ["Pipecat Prebuilt Voice Client", "Runtime Transport Selector", "Interruptible Bot Audio Playback", "Voice Conversation Pipeline"]
---

# Q: How does the Pipecat prebuilt voice client reach the transport pipeline and interrupt bot audio playback?

## Answer

The graph shows the prebuilt client owning a runtime transport selector for SmallWebRTC, Daily, WebSocket, Twilio, and MoQ. Interruptible playback is explicitly implemented in Daily and MoQ client paths, while bot.py's pipeline explicitly chains Groq STT, Groq LLM, Voicebox TTS, and shared conversation context. The WebRTC UI-to-bot join is protocol-mediated and is not represented as a direct source edge in this corpus.

## Source Nodes

- Pipecat Prebuilt Voice Client
- Runtime Transport Selector
- Interruptible Bot Audio Playback
- Voice Conversation Pipeline