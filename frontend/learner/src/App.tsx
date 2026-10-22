import type { LearnerSession } from "./session";
import type { LearnerState } from "./types";
import type { BotAudioController } from "./BotAudioController";

export function App({ session, state, audio }: {
  session: LearnerSession; state: LearnerState; audio: BotAudioController;
}) {
  return <main>
    <h1>Your learning space</h1>
    <p role="status">{state.phase === "ready" ? "Ask your first question" : state.phase}</p>
    <button onClick={() => void session.start()}>Start conversation</button>
    <button onClick={() => void audio.resume()}>Resume audio</button>
    <button onClick={() => void session.end()}>End</button>
    {state.notice && <p>{state.notice}</p>}
  </main>;
}
