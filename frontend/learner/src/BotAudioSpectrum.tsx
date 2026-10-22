import { useEffect, useRef } from "react";
import type { BotAudioController } from "./BotAudioController";

export function bandLevel(data: Uint8Array, index: number, count: number): number {
  const start = Math.floor(index * data.length / count);
  const end = Math.max(start + 1, Math.floor((index + 1) * data.length / count));
  let sum = 0;
  for (let i = start; i < Math.min(end, data.length); i++) sum += data[i];
  return sum / ((end - start) * 255);
}

export function BotAudioSpectrum({ audio }: { audio: BotAudioController }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const element = canvas.current!;
    const context = element.getContext("2d");
    if (!context) return;
    let frame = 0;
    let last = 0;
    let data = new Uint8Array(new ArrayBuffer(0));
    const reduced = matchMedia("(prefers-reduced-motion: reduce)");
    const draw = (now: number) => {
      frame = requestAnimationFrame(draw);
      if (document.hidden || now - last < (reduced.matches ? 100 : 1000 / 30)) return;
      last = now;
      const dpr = Math.min(devicePixelRatio || 1, 2);
      const width = element.clientWidth || 320;
      const height = element.clientHeight || 64;
      if (element.width !== width * dpr || element.height !== height * dpr) {
        element.width = width * dpr; element.height = height * dpr;
      }
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      context.clearRect(0, 0, width, height);
      const analyser = audio.lipsync?.getAnalyser();
      if (analyser && data.length !== analyser.frequencyBinCount)
        data = new Uint8Array(new ArrayBuffer(analyser.frequencyBinCount));
      data.fill(0);
      if (analyser && audio.track && !audio.track.muted && audio.track.readyState !== "ended")
        analyser.getByteFrequencyData(data);
      context.fillStyle = "#b49ae9";
      const bars = 40;
      for (let i = 0; i < bars; i++) {
        const level = bandLevel(data, i, bars);
        const barHeight = 2 + level * (height - 4);
        context.fillRect(i * width / bars + 1, (height - barHeight) / 2,
          Math.max(1, width / bars - 3), barHeight);
      }
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [audio]);
  return <canvas className="spectrum" ref={canvas} role="img" aria-label="Live tutor audio spectrum" />;
}
