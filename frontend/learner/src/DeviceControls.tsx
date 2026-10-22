import { useState } from "react";
import type { BotAudioController } from "./BotAudioController";
import type { LearnerSession } from "./session";
import type { LearnerState } from "./types";

export function DeviceControls({ session, state, audio }: {
  session: LearnerSession; state: LearnerState; audio: BotAudioController;
}) {
  const [error, setError] = useState("");
  const attempt = (operation: Promise<void>) => { setError(""); void operation.catch(() => setError("Device unavailable. Check system settings.")); };
  return <details className="devices">
    <summary>Audio settings & recovery</summary>
    <div className="device-fields">
      <label>Microphone<select defaultValue="" disabled={!state.microphones.length}
        onChange={(event) => attempt(session.selectMicrophone(event.target.value))}>
        <option value="" disabled>Select microphone</option>
        {state.microphones.map((device, index) => <option key={device.deviceId} value={device.deviceId}>
          {device.label || `Microphone ${index + 1}`}</option>)}
      </select></label>
      {audio.canSelectSpeaker ? <label>Speaker<select defaultValue=""
        onChange={(event) => attempt(session.selectSpeaker(event.target.value))}>
        <option value="" disabled>Select speaker</option>
        {state.speakers.map((device, index) => <option key={device.deviceId} value={device.deviceId}>
          {device.label || `Speaker ${index + 1}`}</option>)}
      </select></label> : <p>Choose your speaker in your device’s sound settings.</p>}
      <label>Output volume<input type="range" min="0" max="1" step="0.05" defaultValue="1"
        onChange={(event) => audio.setVolume(Number(event.target.value))} /></label>
      <button type="button" onClick={() => attempt(audio.resume())}>Resume audio</button>
      <p>No camera is used. If the microphone is blocked, allow it in your browser’s site settings.</p>
      {error && <p role="alert">{error}</p>}
    </div>
  </details>;
}
