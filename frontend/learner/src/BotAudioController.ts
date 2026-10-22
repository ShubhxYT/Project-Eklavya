import { Lipsync } from "../../src/lipsync";

export class BotAudioController {
  readonly element = document.createElement("audio");
  track: MediaStreamTrack | null = null;
  lipsync: Lipsync | null = null;
  blocked = false;
  private ended?: () => void;
  private destroyed = false;
  private pendingDispose?: Promise<void>;

  constructor() {
    this.element.autoplay = true;
    this.element.setAttribute("playsinline", "");
    this.element.hidden = true;
    document.body.append(this.element);
  }

  async resume(): Promise<void> {
    if (this.destroyed) return;
    try {
      this.lipsync ??= new Lipsync();
      await this.lipsync.audioContext.resume();
      if (this.track) await this.element.play();
      this.blocked = false;
    } catch { this.blocked = true; }
  }

  async attach(track: MediaStreamTrack): Promise<void> {
    if (this.destroyed) return;
    if (track.kind !== "audio") throw new Error("Only remote audio may be attached");
    if (this.track === track) return;
    this.detach();
    this.track = track;
    const stream = new MediaStream([track]);
    this.element.srcObject = stream;
    this.ended = () => { if (this.track === track) this.detach(); };
    track.addEventListener("ended", this.ended);
    await this.resume();
    if (this.track === track && !this.destroyed) this.lipsync?.connectStream(stream);
  }

  detach(): void {
    if (this.track && this.ended) this.track.removeEventListener("ended", this.ended);
    this.track = null;
    this.ended = undefined;
    this.element.pause();
    this.element.srcObject = null;
    this.lipsync?.disconnectStream();
  }

  sample(): void {
    const sync = this.lipsync;
    if (!sync) return;
    if (!this.track || this.track.readyState === "ended" || this.track.muted) {
      sync.neutralize(); return;
    }
    sync.processAudio();
    if ((sync.features?.volume ?? 0) < 0.005) sync.neutralize();
  }

  setMuted(muted: boolean): void { this.element.muted = muted; }
  setVolume(volume: number): void { this.element.volume = Math.max(0, Math.min(1, volume)); }
  get canSelectSpeaker(): boolean { return typeof this.element.setSinkId === "function"; }
  async selectSpeaker(id: string): Promise<void> {
    if (!this.canSelectSpeaker) throw new Error("Use system sound settings");
    await this.element.setSinkId(id);
  }
  dispose(): Promise<void> {
    if (this.pendingDispose) return this.pendingDispose;
    this.destroyed = true;
    this.detach();
    this.element.remove();
    const sync = this.lipsync; this.lipsync = null;
    this.pendingDispose = sync?.dispose() ?? Promise.resolve();
    return this.pendingDispose;
  }
}
