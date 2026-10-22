import { useEffect, useState } from "react";
import { Avatar } from "./Avatar";
import { BotAudioSpectrum } from "./BotAudioSpectrum";
import { Conversation } from "./Conversation";
import { DeviceControls } from "./DeviceControls";
import type { BotAudioController } from "./BotAudioController";
import type { LearnerSession } from "./session";
import type { LearnerState } from "./types";

export function App({ session, state, audio }: {
  session: LearnerSession; state: LearnerState; audio: BotAudioController;
}) {
  const [mic, setMic] = useState(true);
  const [output, setOutput] = useState(true);
  const [controlError, setControlError] = useState("");
  const live = !["disconnected", "error"].includes(state.phase);
  useEffect(() => { if (state.phase === "disconnected") setMic(true); }, [state.phase]);
  const labels = {
    disconnected: "A little curiosity goes a long way.", connecting: "Connecting to your tutor…",
    ready: "Ask your first question", listening: "Listening to you…", thinking: "Working through your question…",
    speaking: "Your tutor is speaking", reconnecting: "Recovering the connection…", error: "Let’s try again",
  };
  return <main>
    <header className="masthead"><a href="/learn/" aria-label="Eklavya home">eklavya<span> / learning space</span></a>
      <span className="privacy">Voice & text · no camera</span></header>
    <div className="workspace">
      <section className="tutor" aria-labelledby="tutor-title">
        <div className="tutor-heading"><span className="eyebrow">MAKE ROOM FOR UNDERSTANDING</span>
          <h1 id="tutor-title">One question.<br />A clearer perspective.</h1></div>
        <Avatar audio={audio} />
        <div className="tutor-status"><BotAudioSpectrum audio={audio} />
          <p role="status" aria-live="polite">{state.serverMuted ? "Input processing is paused" :
            !mic && state.phase === "listening" ? "Microphone muted" : labels[state.phase]}</p>
          {state.serverMuted && <p>Input processing is paused by the tutor.</p>}</div>
      </section>
      <Conversation session={session} state={state} />
    </div>
    <nav className="session-controls" aria-label="Conversation controls">
      {!live ? <button className="primary" onClick={() => {
        void (state.phase === "error" ? session.end().then(() => session.start()) : session.start());
      }}>Start conversation</button> : <>
        <button disabled={state.phase === "connecting"} aria-pressed={!mic} onClick={() => {
          void session.setMicEnabled(!mic).then(() => setMic(!mic)).catch(() => setControlError("Microphone unavailable"));
        }}>{mic ? "Mute microphone" : "Unmute microphone"}</button>
        <button aria-pressed={!output} onClick={() => { audio.setMuted(output); setOutput(!output); }}>
          {output ? "Mute tutor" : "Unmute tutor"}</button>
        <button className="end" onClick={() => void session.end()}>End conversation</button>
      </>}
    </nav>
    {state.notice && <p className="notice">{state.notice}</p>}
    {controlError && <p role="alert">{controlError}</p>}
    <DeviceControls session={session} state={state} audio={audio} />
    <footer>Learn out loud. Or take your time and type.<span>Ending clears this conversation from the page.</span></footer>
  </main>;
}
