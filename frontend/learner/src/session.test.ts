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
