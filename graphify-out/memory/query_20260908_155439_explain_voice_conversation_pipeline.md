---
type: "explain"
date: "2026-09-08T15:54:39.631425+00:00"
question: "Explain Voice Conversation Pipeline"
contributor: "graphify"
source_nodes: ["Voice Conversation Pipeline"]
---

# Q: Explain Voice Conversation Pipeline

## Answer

The Voice Conversation Pipeline is orchestrated by run_bot and explicitly calls Groq Whisper STT, Groq LLM, and Voicebox TTS while sharing the multi-turn LLM context. Transport input and output wrap these stages in bot.py. Its interruption behavior is supplied by Pipecat turn/VAD and transport machinery rather than by VoiceboxTTSService itself.

## Source Nodes

- Voice Conversation Pipeline