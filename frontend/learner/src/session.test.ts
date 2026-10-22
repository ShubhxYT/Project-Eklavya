import { afterEach, describe, expect, it, vi } from "vitest";
import { BotAudioController } from "./BotAudioController";
import { createLearnerSession } from "./session";

const sdk = vi.hoisted(() => ({ options: null as any, connect: vi.fn(), disconnect: vi.fn(), sendText: vi.fn() }));
vi.mock("@pipecat-ai/client-js", () => ({
  LogLevel: { NONE: "none" },
  PipecatClient: class {
    constructor(options: any) { sdk.options = options; }
    setLogLevel() {}
    connect = sdk.connect;
    disconnect = sdk.disconnect;
    sendText = sdk.sendText;
    tracks = () => ({ local: {} });
    getAllMics = async () => [];
    getAllSpeakers = async () => [];
    enableMic() {}
    updateMic() {}
    updateSpeaker() {}
  },
}));
vi.mock("@pipecat-ai/small-webrtc-transport", () => ({ SmallWebRTCTransport: class {} }));

afterEach(() => { vi.useRealTimers(); vi.resetAllMocks(); });

describe("session adapter", () => {
  it("deduplicates start, never enables video, and waits for bot-ready", async () => {
    const events: any[] = [];
    const audio = { resume: vi.fn(), detach: vi.fn(), dispose: vi.fn() } as unknown as BotAudioController;
    let finish!: () => void;
    sdk.connect.mockImplementation(() => new Promise<void>((resolve) => { finish = resolve; }));
    const session = createLearnerSession({ mode: "local", audio, onEvent: (event) => events.push(event) });
    const first = session.start();
    expect(session.start()).toBe(first);
    await Promise.resolve(); await Promise.resolve();
    expect(sdk.connect).toHaveBeenCalledTimes(1);
    expect(sdk.options.enableCam).toBe(false);
    expect(sdk.options.enableScreenShare).toBe(false);
    await expect(session.sendText("premature")).rejects.toThrow();
    sdk.options.callbacks.onBotReady({ version: "2.1.0" }); finish(); await first;
    await session.sendText("question");
    expect(sdk.sendText).toHaveBeenCalledWith("question", { run_immediately: true, audio_response: true });
    await session.end(); expect(audio.detach).toHaveBeenCalled();
    expect(events.at(-1)).toEqual({ type: "clear" });
  });

  it("accepts remote audio without participant metadata, not local/video", async () => {
    sdk.connect.mockResolvedValue({});
    const audio = { resume: vi.fn(), attach: vi.fn(), detach: vi.fn(), dispose: vi.fn() } as unknown as BotAudioController;
    const session = createLearnerSession({ mode: "local", audio, onEvent: () => {} });
    await session.start();
    const remote = { kind: "audio" } as MediaStreamTrack;
    sdk.options.callbacks.onTrackStarted(remote);
    sdk.options.callbacks.onTrackStarted({ kind: "audio" }, { local: true });
    sdk.options.callbacks.onTrackStarted({ kind: "video" });
    expect(audio.attach).toHaveBeenCalledExactlyOnceWith(remote);
    await session.dispose();
  });
});

it("settles pending Start on End and stops late local capture", async () => {
  const audio = { resume: vi.fn(), detach: vi.fn(), dispose: vi.fn() } as unknown as BotAudioController;
  sdk.connect.mockImplementation(() => new Promise(() => {}));
  const events: any[] = [];
  const session = createLearnerSession({ mode: "local", audio, onEvent: (event) => events.push(event) });
  const pending = session.start();
  await Promise.resolve(); await Promise.resolve();
  await session.end(); await pending;
  const track = { kind: "audio", stop: vi.fn() };
  sdk.options.callbacks.onTrackStarted(track, { local: true });
  sdk.options.callbacks.onBotReady({ version: "2.1.0" });
  expect(track.stop).toHaveBeenCalledOnce();
  expect(events.filter((event) => event.type === "phase" && event.phase === "ready")).toHaveLength(0);
  await session.dispose();
});

it("reuses a live public lease but resets when explicitly starting a new one", async () => {
  let leases = 0;
  const fetcher = vi.fn(async (url: string) => {
    if (url === "/session/start") {
      const sessionId = (++leases).toString(16).padStart(32, "0");
      return new Response(JSON.stringify({ sessionId, csrf: "safe-fake-nonce", expiresAt: 900000,
        webrtcRequestParams: { endpoint: `/session/${sessionId}/offer` } }), { status: 200 });
    }
    return new Response("{}", { status: 200 });
  });
  vi.stubGlobal("fetch", fetcher);
  sdk.connect.mockImplementation(async () => { sdk.options.callbacks.onBotReady({ version: "2.1.0" }); });
  const events: any[] = [];
  const audio = { resume: vi.fn(), detach: vi.fn(), dispose: vi.fn() } as unknown as BotAudioController;
  const session = createLearnerSession({ mode: "public", audio, onEvent: (event) => events.push(event) });
  try {
    await session.start(); await session.start();
    sdk.options.callbacks.onDisconnected();
    sdk.options.callbacks.onBotReady({ version: "2.1.0" });
    expect(leases).toBe(1);
    expect(events.filter((event) => event.type === "reset")).toHaveLength(1);
    await session.end(); await session.start();
    expect(leases).toBe(2);
    expect(events.filter((event) => event.type === "reset")).toHaveLength(2);
    await session.dispose();
  } finally { vi.unstubAllGlobals(); }
});

it("releases the public lease before disconnecting the peer", async () => {
  let releaseEnd!: () => void;
  const order: string[] = [];
  const sessionId = "a".repeat(32);
  const fetcher = vi.fn(async (url: string) => {
    if (url === "/session/start") {
      return new Response(JSON.stringify({ sessionId, csrf: "safe-fake-nonce", expiresAt: 900000,
        webrtcRequestParams: { endpoint: `/session/${sessionId}/offer` } }), { status: 200 });
    }
    if (url.endsWith("/end")) {
      order.push("end");
      await new Promise<void>((resolve) => { releaseEnd = resolve; });
      return new Response("{}", { status: 200 });
    }
    return new Response("{}", { status: 200 });
  });
  vi.stubGlobal("fetch", fetcher);
  sdk.connect.mockImplementation(async () => { sdk.options.callbacks.onBotReady({ version: "2.1.0" }); });
  sdk.disconnect.mockImplementation(async () => { order.push("disconnect"); });
  const audio = { resume: vi.fn(), detach: vi.fn(), dispose: vi.fn() } as unknown as BotAudioController;
  const session = createLearnerSession({ mode: "public", audio, onEvent: () => {} });
  try {
    await session.start();
    const ending = session.end();
    await Promise.resolve();
    expect(order).toEqual(["end"]);
    releaseEnd();
    await ending;
    expect(order).toEqual(["end", "disconnect"]);
    await session.dispose();
  } finally { vi.unstubAllGlobals(); }
});
