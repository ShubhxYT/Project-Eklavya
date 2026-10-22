import { afterEach, expect, it, vi } from "vitest";
import { BotAudioController } from "./BotAudioController";
import { bandLevel } from "./BotAudioSpectrum";

class Track extends EventTarget {
  kind = "audio";
  readyState = "live";
  muted = false;
  stop = vi.fn();
}

afterEach(() => { document.body.replaceChildren(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("owns one context/player and a permanently silent analysis tap", async () => {
  let contexts = 0;
  let closes = 0;
  const analyser = { fftSize: 2048, frequencyBinCount: 1024,
    disconnect: vi.fn(), getByteFrequencyData: (data: Uint8Array) => data.fill(0) };
  class Context {
    constructor() { contexts++; }
    state = "running";
    sampleRate = 48000;
    createAnalyser = () => analyser;
    createMediaStreamSource = () => ({ connect: vi.fn(), disconnect: vi.fn() });
    resume = async () => {};
    close = async () => { closes++; this.state = "closed"; };
  }
  vi.stubGlobal("AudioContext", Context);
  vi.stubGlobal("MediaStream", class { constructor(public tracks: Track[]) {} });
  vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  const controller = new BotAudioController();
  await controller.resume();
  const old = new Track(); const current = new Track();
  await controller.attach(old as unknown as MediaStreamTrack);
  await controller.attach(current as unknown as MediaStreamTrack);
  old.dispatchEvent(new Event("ended"));
  expect(controller.track).toBe(current);
  expect(contexts).toBe(1);
  const elements = [...document.querySelectorAll("audio")];
  expect(elements.filter((element) => !element.muted)).toHaveLength(1);
  expect(elements.find((element) => element !== controller.element)?.muted).toBe(true);
  controller.sample(); expect(controller.lipsync?.viseme).toBe("viseme_sil");
  await controller.dispose(); await controller.dispose();
  expect(closes).toBe(1); expect(current.stop).not.toHaveBeenCalled();
  expect(document.querySelectorAll("audio")).toHaveLength(0);
});

it("uses deterministic frequency samples, with zero quiet energy", () => {
  expect(bandLevel(new Uint8Array([0, 0, 0, 0]), 0, 2)).toBe(0);
  expect(bandLevel(new Uint8Array([255, 255, 0, 0]), 0, 2)).toBe(1);
  expect(bandLevel(new Uint8Array([255, 255, 0, 0]), 1, 2)).toBe(0);
});

it("recovers rejected playback and routes the actual audible element", async () => {
  const analyser = { frequencyBinCount: 1024, disconnect: vi.fn() };
  vi.stubGlobal("AudioContext", class {
    state = "running"; sampleRate = 48000;
    createAnalyser = () => analyser;
    createMediaStreamSource = () => ({ connect: vi.fn(), disconnect: vi.fn() });
    resume = async () => {};
    close = async () => {};
  });
  vi.stubGlobal("MediaStream", class { constructor(public tracks: Track[]) {} });
  const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockRejectedValue(new Error("blocked"));
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  const controller = new BotAudioController();
  const sink = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(controller.element, "setSinkId", { value: sink, configurable: true });
  await controller.attach(new Track() as unknown as MediaStreamTrack);
  expect(controller.blocked).toBe(true);
  play.mockResolvedValue();
  await controller.resume(); expect(controller.blocked).toBe(false);
  await controller.selectSpeaker("headphones");
  expect(sink).toHaveBeenCalledExactlyOnceWith("headphones");
  controller.setMuted(true); controller.setVolume(.4);
  expect(controller.element.muted).toBe(true);
  expect(controller.element.volume).toBe(.4);
  await controller.dispose();
});
