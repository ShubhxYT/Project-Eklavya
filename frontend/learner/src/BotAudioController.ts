export class BotAudioController {
  readonly element = document.createElement("audio");
  track: MediaStreamTrack | null = null;
  blocked = false;
  private ended?: () => void;

  constructor() {
    this.element.autoplay = true;
    this.element.setAttribute("playsinline", "");
    this.element.hidden = true;
    document.body.append(this.element);
  }

  async attach(track: MediaStreamTrack): Promise<void> {
    if (track.kind !== "audio") throw new Error("Audio track required");
    this.detach();
    this.track = track;
    this.ended = () => { if (this.track === track) this.detach(); };
    track.addEventListener("ended", this.ended);
    this.element.srcObject = new MediaStream([track]);
    await this.resume();
  }

  detach(): void {
    if (this.track && this.ended) this.track.removeEventListener("ended", this.ended);
    this.track = null;
    this.element.pause();
    this.element.srcObject = null;
  }

  async resume(): Promise<void> {
    try { if (this.track) await this.element.play(); this.blocked = false; }
    catch { this.blocked = true; }
  }

  setMuted(muted: boolean): void { this.element.muted = muted; }
  setVolume(volume: number): void { this.element.volume = Math.max(0, Math.min(1, volume)); }
  get canSelectSpeaker(): boolean { return typeof this.element.setSinkId === "function"; }
  async selectSpeaker(id: string): Promise<void> {
    if (!this.canSelectSpeaker) throw new Error("Use system audio settings");
    await this.element.setSinkId(id);
  }
  async dispose(): Promise<void> { this.detach(); this.element.remove(); }
}
