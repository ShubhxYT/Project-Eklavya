import { createRoot } from "react-dom/client";
import { PipecatClientProvider } from "@pipecat-ai/client-react";
import { App } from "./App";
import { BotAudioController } from "./BotAudioController";
import { createLearnerSession } from "./session";
import { initialState, reduceSession } from "./types";
import "./styles.css";

const root = createRoot(document.getElementById("root")!);
const audio = new BotAudioController();
let state = initialState();
const mode = document.querySelector('meta[name="eklavya-mode"]')?.getAttribute("content") === "public"
  ? "public" : "local";
const session = createLearnerSession({ mode, audio, onEvent: (event) => {
  state = reduceSession(state, event); render();
} });

function render() {
  root.render(<PipecatClientProvider client={session.client} autoInitDevices={false}>
    <App session={session} state={state} audio={audio} />
  </PipecatClientProvider>);
}
render();
window.addEventListener("pagehide", () => { void session.end(); });
if (import.meta.hot) import.meta.hot.dispose(() => { root.unmount(); void session.dispose(); });
