import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { initialState, reduceSession, type LearnerEvent } from "./types";
import { Conversation } from "./Conversation";
import type { LearnerSession } from "./session";

afterEach(cleanup);

it("upserts interim text, consumes typed echoes and preserves repeated questions", () => {
  const events: LearnerEvent[] = [
    { type: "user-start" }, { type: "user-text", text: "hel", final: false, user: "u" },
    { type: "user-text", text: "hello", final: true, user: "u" },
    { type: "typed", id: "a", text: "again" }, { type: "user-echo", text: "again" },
    { type: "typed", id: "b", text: "again" }, { type: "user-echo", text: "again" },
  ];
  const state = events.reduce(reduceSession, initialState());
  expect(state.messages.map((message) => message.text)).toEqual(["hello", "again", "again"]);
  expect(state.messages.filter((message) => message.echoed)).toHaveLength(2);
});

it("keeps cited and clean speech as one answer without claiming heard words", () => {
  const state = ([
    { type: "bot-start" }, { type: "bot-text", text: "An answer [S1]." },
    { type: "bot-text", text: "An answer." },
    { type: "bot-output", text: "An answer.", segment: 1, spoken: true },
    { type: "interrupted" },
  ] satisfies LearnerEvent[]).reduce(reduceSession, initialState());
  expect(state.messages).toHaveLength(1);
  expect(state.messages[0].text).toContain("[S1]");
  expect(state.messages[0].interrupted).toBe(true);
  render(<Conversation state={state} session={{} as LearnerSession} />);
  expect(screen.getByText(/some generated text may not have been spoken/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
});

it("clears the unsaved transcript for End and a new lease", () => {
  const state = reduceSession(initialState(), { type: "typed", id: "a", text: "private" });
  expect(reduceSession(state, { type: "clear" }).messages).toEqual([]);
  expect(reduceSession(state, { type: "reset", lease: "new" }).messages).toEqual([]);
});
