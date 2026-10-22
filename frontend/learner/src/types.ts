export type Phase = "disconnected" | "connecting" | "ready" | "listening" |
  "thinking" | "speaking" | "reconnecting" | "error";
export type LearnerEvent =
  | { type: "phase"; phase: Phase }
  | { type: "reset"; lease: string }
  | { type: "clear" }
  | { type: "user-start" }
  | { type: "user-text"; text: string; final: boolean; user: string }
  | { type: "typed"; id: string; text: string }
  | { type: "typed-failed"; id: string }
  | { type: "user-echo"; text: string }
  | { type: "bot-start" }
  | { type: "bot-speaking" }
  | { type: "bot-stopped" }
  | { type: "bot-text"; text: string }
  | { type: "bot-output"; text: string; segment?: number; spoken?: boolean; progress?: string }
  | { type: "interrupted" }
  | { type: "server-mute"; muted: boolean }
  | { type: "devices"; microphones: MediaDeviceInfo[]; speakers: MediaDeviceInfo[] }
  | { type: "error"; message: string };

export interface Message {
  id: string;
  role: "user" | "assistant";
  text: string;
  final: boolean;
  canonical?: string;
  source?: "typed" | "speech";
  failed?: boolean;
  echoed?: boolean;
  interrupted?: boolean;
  segments?: Record<string, { text: string; spoken?: boolean; progress?: string }>;
}

export interface LearnerState {
  phase: Phase;
  messages: Message[];
  next: number;
  activeUser?: string;
  activeBot?: string;
  botInFlight: boolean;
  serverMuted: boolean;
  notice?: string;
  microphones: MediaDeviceInfo[];
  speakers: MediaDeviceInfo[];
}

export const initialState = (): LearnerState => ({
  phase: "disconnected", messages: [], next: 0, serverMuted: false, botInFlight: false,
  microphones: [], speakers: [],
});

export function reduceSession(state: LearnerState, event: LearnerEvent): LearnerState {
  if (event.type === "clear") return initialState();
  if (event.type === "reset") return { ...initialState(), phase: "connecting", notice: "New conversation" };
  if (event.type === "phase") return { ...state, phase: event.phase };
  if (event.type === "error") return { ...state, phase: "error", notice: event.message };
  if (event.type === "server-mute") return { ...state, serverMuted: event.muted };
  if (event.type === "devices") return { ...state, microphones: event.microphones, speakers: event.speakers };
  if (event.type === "bot-speaking") return { ...state, botInFlight: true };
  if (event.type === "bot-stopped") return { ...state, botInFlight: false,
    messages: state.messages.map((m) => m.id === state.activeBot ? { ...m, final: true } : m) };
  if (event.type === "user-start") {
    const id = `speech-${state.next}`;
    return { ...state, next: state.next + 1, activeUser: id,
      messages: state.messages.map((m) => m.id === state.activeBot && state.botInFlight ? { ...m, interrupted: true } : m) };
  }
  if (event.type === "typed") return { ...state,
    messages: [...state.messages, { id: event.id, role: "user", text: event.text, final: true, source: "typed" }] };
  if (event.type === "typed-failed") return { ...state,
    messages: state.messages.map((m) => m.id === event.id ? { ...m, failed: true } : m) };
  if (event.type === "user-echo") {
    const candidate = state.messages.find((m) => m.role === "user" && !m.echoed && m.text === event.text);
    return candidate ? { ...state, messages: state.messages.map((m) =>
      m.id === candidate.id ? { ...m, echoed: true } : m) } : state;
  }
  if (event.type === "user-text") {
    const id = state.activeUser ?? `speech-${state.next}`;
    const message: Message = { id, role: "user", text: event.text, final: event.final, source: "speech" };
    const found = state.messages.some((m) => m.id === id);
    return { ...state, next: state.activeUser ? state.next : state.next + 1,
      activeUser: event.final ? undefined : id,
      messages: found ? state.messages.map((m) => m.id === id ? message : m) : [...state.messages, message] };
  }
  if (event.type === "bot-start") {
    const id = `bot-${state.next}`;
    return { ...state, next: state.next + 1, activeBot: id, botInFlight: true,
      messages: [...state.messages, { id, role: "assistant", text: "", final: false, segments: {} }] };
  }
  if (event.type === "interrupted") return { ...state,
    messages: state.messages.map((m) => m.id === state.activeBot && state.botInFlight ? { ...m, interrupted: true } : m) };
  if (event.type === "bot-text" || event.type === "bot-output") {
    if (!state.activeBot) state = reduceSession(state, { type: "bot-start" });
    const canonical = (text: string) => text.replace(/\[S[0-9]+\]/g, "")
      .replace(/\s+([.,;:!?])/g, "$1").replace(/\s+/g, " ").trim();
    return { ...state, messages: state.messages.map((m) => {
      if (m.id !== state.activeBot) return m;
      if (event.type === "bot-output") return { ...m,
        text: m.text || event.text,
        segments: { ...m.segments, [String(event.segment ?? 0)]: {
          text: event.text, spoken: event.spoken, progress: event.progress,
        } } };
      if (!m.canonical) return { ...m, text: event.text, canonical: event.text };
      if (canonical(m.canonical) === canonical(event.text)) {
        const text = /\[S[0-9]+\]/.test(event.text) ? event.text : m.canonical;
        return { ...m, text, canonical: text };
      }
      return { ...m, text: m.canonical + event.text, canonical: m.canonical + event.text };
    }) };
  }
  return state;
}
