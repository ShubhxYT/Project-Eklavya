import { useRef, useState } from "react";
import { PipecatClient, RTVIEvent } from "@pipecat-ai/client-js";
import { SmallWebRTCTransport } from "@pipecat-ai/small-webrtc-transport";
import { AvatarScene } from "./Avatar";
import { Lipsync } from "./lipsync";

type Msg = { key: string; role: "user" | "bot"; text: string };

export default function App() {
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const clientRef = useRef<PipecatClient | null>(null);
  const lipsyncRef = useRef<Lipsync | null>(null);

  const connect = async () => {
    setConnecting(true);
    setError(null);
    try {
      if (!clientRef.current) {
        lipsyncRef.current = new Lipsync();
        const client = new PipecatClient({
          transport: new SmallWebRTCTransport(),
          callbacks: {
            onTrackStarted: (track, participant) => {
              if (participant?.local || track.kind !== "audio") return;
              const el = audioRef.current;
              const l = lipsyncRef.current;
              if (!el || !l) return;
              const stream = new MediaStream([track]);
              el.srcObject = stream;
              el.play().catch(() => {});
              l.connectStream(stream);
            },
            onUserTranscript: (data) =>
              setMsgs((m) =>
                m.some((x) => x.key === data.timestamp)
                  ? m
                  : [
                      ...m,
                      { key: data.timestamp, role: "user", text: data.text },
                    ]
              ),
            onBotOutput: (data) =>
              setMsgs((m) =>
                m.some((x) => x.key === String(data.segment_id))
                  ? m.map((x) =>
                      x.key === String(data.segment_id)
                        ? { ...x, text: data.text }
                        : x
                    )
                  : [
                      ...m,
                      {
                        key: String(data.segment_id),
                        role: "bot",
                        text: data.text,
                      },
                    ]
              ),
            onError: (message) => {
              const detail = (message as { data?: { message?: string } })?.data
                ?.message;
              setError(detail || "Connection error. Is the bot running?");
              setConnected(false);
            },
            onDisconnected: () => setConnected(false),
          },
        });
        clientRef.current = client;
      }
      await clientRef.current.initDevices();
      // webrtcRequestParams (NOT `endpoint`): passing `{endpoint}` routes
      // through startBot() which POSTs an empty body and 422s /api/offer.
      // webrtcRequestParams makes the transport POST the SDP offer itself.
      await clientRef.current.connect({
        webrtcRequestParams: { endpoint: "/api/offer" },
      });
      setConnected(true);
    } catch (e) {
      console.error(e);
      const name = (e as DOMException)?.name;
      if (name === "NotAllowedError") {
        setError("Microphone permission denied. Allow mic access and retry.");
      } else if (name === "NotFoundError") {
        setError("No microphone found.");
      } else {
        setError(
          "Could not connect. Is the bot running? (uv run bot.py -t webrtc --port 7861)"
        );
      }
      setConnected(false);
    } finally {
      setConnecting(false);
    }
  };

  const disconnect = async () => {
    await clientRef.current?.disconnect();
    setConnected(false);
  };

  return (
    <div className="app">
      <h1>Project Eklavya</h1>
      <div className="avatar">
        <AvatarScene lipsync={lipsyncRef} />
      </div>
      <div className="controls">
        {connected ? (
          <button className="danger" onClick={disconnect}>
            Disconnect
          </button>
        ) : (
          <button onClick={connect} disabled={connecting}>
            {connecting ? "Connecting..." : "Connect"}
          </button>
        )}
        {connected && <span className="status">Live</span>}
      </div>
      {error && <div className="error">{error}</div>}
      <div className="transcript">
        {msgs.length === 0 && (
          <p className="hint">
            Press Connect and start talking. Your conversation appears here.
          </p>
        )}
        {msgs.map((m) => (
          <p key={m.key} className={m.role}>
            <b>{m.role === "user" ? "You" : "Eklavya"}:</b> {m.text}
          </p>
        ))}
      </div>
      <audio ref={audioRef} autoPlay />
    </div>
  );
}
