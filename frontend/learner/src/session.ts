import { LogLevel, PipecatClient, type Participant } from "@pipecat-ai/client-js";
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport";
import type { LearnerEvent } from "./types";
import type { BotAudioController } from "./BotAudioController";

type Bootstrap = {
  sessionId: string;
  csrf: string;
  expiresAt: number;
  iceConfig?: { iceServers: RTCIceServer[] };
  webrtcRequestParams: { endpoint: string };
};

export interface LearnerSession {
  readonly client: PipecatClient;
  start(): Promise<void>;
  sendText(text: string): Promise<void>;
  setMicEnabled(enabled: boolean): Promise<void>;
  selectMicrophone(id: string): Promise<void>;
  selectSpeaker(id: string): Promise<void>;
  end(): Promise<void>;
  dispose(): Promise<void>;
}

export function createLearnerSession({ mode, audio, onEvent }: {
  mode: "local" | "public";
  audio: BotAudioController;
  onEvent: (event: LearnerEvent) => void;
}): LearnerSession {
  let ready = false;
  let active = false;
  let disposed = false;
  let generation = 0;
  let starting: Promise<void> | undefined;
  let stopping: Promise<void> | undefined;
  let lease: Bootstrap | undefined;
  let abort: AbortController | undefined;
  let micWait: { id: string; resolve: () => void; reject: () => void } | undefined;
  let sequence = 0;
  const emit = (event: LearnerEvent) => { if (!disposed) onEvent(event); };
  const phase = (value: Parameters<typeof onEvent>[0] & { type: "phase" }) => emit(value);
  const isRemote = (track: MediaStreamTrack, participant?: Participant) =>
    track.kind === "audio" && !participant?.local && track !== client.tracks().local.audio;

  const client = new PipecatClient({
    transport: new SmallWebRTCTransport(),
    enableMic: true,
    enableCam: false,
    enableScreenShare: false,
    callbacks: {
      onBotReady: () => {
        if (active) { ready = true; phase({ type: "phase", phase: "ready" }); }
        else void client.disconnect();
      },
      onConnected: () => { if (!active) void client.disconnect(); },
      onDisconnected: () => { ready = false; if (active) phase({ type: "phase", phase: "disconnected" }); },
      onTrackStarted: (track, participant) => {
        if (!active || disposed) { if (participant?.local) track.stop(); return; }
        if (isRemote(track, participant)) void audio.attach(track);
      },
      onTrackStopped: (track) => { if (audio.track === track) audio.detach(); },
      onUserStartedSpeaking: () => { if (active && ready) {
        emit({ type: "user-start" }); phase({ type: "phase", phase: "listening" });
      } },
      onUserStoppedSpeaking: () => { if (active && ready) phase({ type: "phase", phase: "thinking" }); },
      onUserTranscript: (data) => { if (active) emit({ type: "user-text", text: data.text, final: data.final, user: data.user_id }); },
      onUserLlmText: (data) => { if (active) emit({ type: "user-echo", text: data.text }); },
      onBotLlmStarted: () => { if (active) { emit({ type: "bot-start" }); phase({ type: "phase", phase: "thinking" }); } },
      onBotLlmText: (data) => { if (active) emit({ type: "bot-text", text: data.text }); },
      onBotOutput: (data) => { if (active) emit({ type: "bot-output", text: data.text,
        segment: data.segment_id, spoken: data.spoken, progress: data.spoken_progress?.accumulated_text }); },
      onBotStartedSpeaking: () => { if (active) { emit({ type: "bot-speaking" }); phase({ type: "phase", phase: "speaking" }); } },
      onBotStoppedSpeaking: () => { if (active && ready) { emit({ type: "bot-stopped" }); phase({ type: "phase", phase: "ready" }); } },
      onUserMuteStarted: () => emit({ type: "server-mute", muted: true }),
      onUserMuteStopped: () => emit({ type: "server-mute", muted: false }),
      onServerMessage: (data) => {
        if (active && data && typeof data === "object" && "type" in data && data.type === "learner-interrupted")
          emit({ type: "interrupted" });
      },
      onError: () => { if (active) emit({ type: "error", message: "Connection failed. End and try again." }); },
      onMessageError: () => { if (active) emit({ type: "error", message: "The request could not be completed." }); },
      onDeviceError: () => { micWait?.reject(); if (active) emit({ type: "error", message: "Check microphone permissions and device settings." }); },
      onMicUpdated: (device) => { if (micWait && micWait.id === device.deviceId) micWait.resolve(); },
      onAvailableMicsUpdated: () => { if (active) void refreshDevices().catch(() => undefined); },
      onAvailableSpeakersUpdated: () => { if (active) void refreshDevices().catch(() => undefined); },
    },
  });
  client.setLogLevel(LogLevel.NONE);

  async function refreshDevices(): Promise<void> {
    const [microphones, speakers] = await Promise.all([client.getAllMics(), client.getAllSpeakers()]);
    if (active) emit({ type: "devices", microphones, speakers });
  }

  async function releaseLease(current: Bootstrap | undefined): Promise<void> {
    if (!current) return;
    await fetch(`/session/${current.sessionId}/end`, {
      method: "POST", credentials: "same-origin", keepalive: true,
      headers: { "Content-Type": "application/json", "X-Eklavya-CSRF": current.csrf },
      body: "{}",
      signal: AbortSignal.timeout(5000),
    }).catch(() => undefined);
  }

  const session: LearnerSession = {
    client,
    start() {
      if (disposed) return Promise.reject(new Error("Session disposed"));
      if (starting) return starting;
      if (active) return Promise.resolve();
      const token = ++generation;
      active = true; ready = false; abort = new AbortController();
      const signal = abort.signal;
      emit({ type: "reset", lease: "pending" });
      starting = (async () => {
        await stopping;
        await audio.resume();
        let connection: Parameters<PipecatClient["connect"]>[0] = {
          webrtcRequestParams: { endpoint: "/api/offer" },
        };
        if (mode === "public") {
          const response = await fetch("/session/start", {
            method: "POST", credentials: "same-origin", signal,
            headers: { "Content-Type": "application/json" }, body: "{}",
          });
          if (!response.ok) throw new Error("Tutor busy or unavailable");
          const value: Bootstrap = await response.json();
          if (!/^[a-f0-9]{32}$/.test(value.sessionId) || typeof value.csrf !== "string" ||
              value.webrtcRequestParams?.endpoint !== `/session/${value.sessionId}/offer`)
            throw new Error("Invalid session response");
          lease = value;
          if (token !== generation) { await releaseLease(value); return; }
          connection = { iceConfig: value.iceConfig, webrtcRequestParams: {
            endpoint: value.webrtcRequestParams.endpoint,
            headers: new Headers({ "X-Eklavya-CSRF": value.csrf }),
          } };
        }
        if (token !== generation) return;
        let timer: ReturnType<typeof setTimeout> | undefined;
        let cancel = () => {};
        try {
          await Promise.race([
            client.connect(connection),
            new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error("Setup timed out")), 60_000); }),
            new Promise<never>((_, reject) => {
              cancel = () => reject(new Error("Start canceled"));
              if (signal.aborted) cancel();
              else signal.addEventListener("abort", cancel, { once: true });
            }),
          ]);
          if (token === generation) await refreshDevices();
        } finally { clearTimeout(timer); signal.removeEventListener("abort", cancel); }
      })().catch(async () => {
        if (token === generation) {
            await stopCurrent();
          emit({ type: "error", message: "Could not start. Check permissions or try again shortly." });
        }
      }).finally(() => { starting = undefined; });
      return starting;
    },
    async sendText(text) {
      const value = text.trim();
      if (!ready || !active || !value || value.length > 4000) throw new Error("Input unavailable");
      const id = `typed-${++sequence}`;
      emit({ type: "interrupted" }); emit({ type: "typed", id, text: value });
      try { await client.sendText(value, { run_immediately: true, audio_response: true }); }
      catch { emit({ type: "typed-failed", id }); throw new Error("Message was not sent"); }
    },
    async setMicEnabled(enabled) { client.enableMic(enabled); },
    async selectMicrophone(id) {
      if (micWait) throw new Error("Device change already pending");
      await new Promise<void>((resolve, reject) => {
        const finish = (error?: Error) => { clearTimeout(timer); micWait = undefined; error ? reject(error) : resolve(); };
        const timer = setTimeout(() => finish(new Error("Microphone change timed out")), 8000);
        micWait = { id, resolve: () => finish(), reject: () => finish(new Error("Microphone unavailable")) };
        client.updateMic(id);
      });
    },
    async selectSpeaker(id) { await audio.selectSpeaker(id); client.updateSpeaker(id); },
    async end() {
      const pending = starting;
      await stopCurrent();
      await pending;
    },
    async dispose() { await session.end(); disposed = true; await audio.dispose(); },
  };
  function stopCurrent(): Promise<void> {
    if (stopping) return stopping;
    ++generation; active = false; ready = false; abort?.abort(); micWait?.reject();
    const current = lease; lease = undefined;
    const local = client.tracks().local;
    local.audio?.stop(); local.video?.stop();
    audio.detach(); emit({ type: "clear" });
    stopping = (async () => {
      await releaseLease(current);
      await Promise.allSettled([client.disconnect()]);
    })().then(() => undefined).finally(() => { stopping = undefined; });
    return stopping;
  }
  return session;
}
