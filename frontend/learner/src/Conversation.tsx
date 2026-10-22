import { useEffect, useRef, useState } from "react";
import type { LearnerSession } from "./session";
import type { LearnerState } from "./types";

export function Conversation({ session, state }: { session: LearnerSession; state: LearnerState }) {
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const scroller = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);
  const canSend = ["ready", "listening", "thinking", "speaking"].includes(state.phase) && !state.serverMuted;
  useEffect(() => {
    if (pinned.current && scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight;
  }, [state.messages]);
  useEffect(() => { if (state.phase === "disconnected") { setText(""); setError(""); } }, [state.phase]);
  return <section className="conversation" aria-labelledby="conversation-title">
    <header><h2 id="conversation-title">Conversation</h2><span>Unsaved · this tab only</span></header>
    <div className="messages" ref={scroller} tabIndex={0} aria-label="Conversation transcript"
      onScroll={(event) => { const node = event.currentTarget;
        pinned.current = node.scrollHeight - node.scrollTop - node.clientHeight < 64; }}>
      {!state.messages.length && <p className="empty">Bring a question.<br />We’ll work through it together.</p>}
      {state.messages.filter((message) => message.text).map((message) => <article key={message.id} className={message.role}>
        <strong>{message.role === "user" ? "You" : "Tutor"}</strong>
        <p>{message.text}</p>
        {!message.final && message.role === "user" && <small>Hearing you…</small>}
        {message.failed && <small>Not sent</small>}
        {message.interrupted && <small>Interrupted — some generated text may not have been spoken.</small>}
      </article>)}
    </div>
    <form onSubmit={(event) => { event.preventDefault();
      const value = text.trim(); if (!value || !canSend) return;
      setText(""); setError("");
      void session.sendText(value).catch(() => { setText(value); setError("Not sent. Try again when connected."); });
    }}>
      <label className="sr-only" htmlFor="question">Ask a question</label>
      <textarea id="question" rows={2} maxLength={4000} value={text} disabled={!canSend}
        placeholder={canSend ? "Or type your question…" : "Start a conversation to ask a question"}
        onChange={(event) => setText(event.target.value)} />
      <button type="submit" disabled={!canSend || !text.trim()}>Send</button>
    </form>
    {error && <p role="alert">{error}</p>}
  </section>;
}
