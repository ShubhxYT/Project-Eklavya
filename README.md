# Project Eklavya

A behavior-aware, file-grounded voice tutor. A Pipecat voice bot answers only
from an ingested course corpus, speaks through a self-hosted voicebox TTS
server, and can interrupt with concise recovery prompts when the browser
camera's engagement model detects a struggling learner.

## Layout

```
bot.py                    Pipecat dev-runner entrypoint (uv run bot.py)
src/eklavya/
  app.py                  bot pipeline, transports, behavior websocket
  grounded_tutor.py       OKF-grounded Pipecat LLM processor
  behavior_monitor.py     owns the vision worker subprocess + policy
  voicebox_tts.py         Voicebox TTS service
  telephony.py            outbound Twilio calls (eklavya-call)
  drona/                  retrieval, citations, Groq tutor client
  ingest/                 Docling ingestion CLI + optional Streamlit uploader
client/                   built Pipecat UI served at /client (checked in)
frontend/                 avatar-overlay source, builds into client/
vision/                   H5 engagement model + worker (own Python 3.13 venv)
data/                     ingested course corpus (gitignored)
docs/plans/               design and implementation notes
tests/                    behavior + ingestion tests
```

## Quick start

```bash
uv sync
cp .env.example .env   # add GROQ_API_KEY
uv run bot.py
```

Open http://localhost:7860 and click **Connect**. First run takes ~20s while
models/SDKs warm up.

## Ingest a course

Ingestion pulls in Docling, so it lives behind an optional extra and is never
installed into the production image:

```bash
uv sync --extra ingest
uv run --extra ingest eklavya-ingest ingest /path/to/course.pdf   # file or dir
uv run --extra ingest eklavya-ingest chat                          # terminal chat
```

Bundles are written to `data/okf/<course-id>/`. The bot auto-picks the course
when only one exists; set `COURSE_ID` to disambiguate.

Optional upload UI:

```bash
uv run --extra ingest streamlit run src/eklavya/ingest/streamlit_app.py
```

## Behavior sensing

The H5 engagement model runs in a separate Python 3.13 process while the voice
bot runs on 3.12. Create its venv once:

```bash
uv venv --python 3.13 vision/.venv-h5
uv pip install --python vision/.venv-h5/bin/python -r vision/requirements-h5.txt
```

Start the bot normally, open the client, and turn on the **Camera** toggle in
the Bot Video header. Camera permission requires `localhost` or HTTPS.

Absolute thresholds: Engagement ≤40%, Boredom ≥60%, Confusion ≥65%, or
Frustration ≥65% after a smoothed breach lasting five seconds. A 60-second
cooldown and five-point recovery hysteresis prevent repeated interruptions.
Missing cameras, denied permission, disconnected streams, and no-face periods
fail silently and leave voice chat running.

Override paths if needed:

```dotenv
CV_PYTHON=/absolute/path/to/vision/.venv-h5/bin/python
CV_MODEL_PATH=/absolute/path/to/vision/daisee_engagement_model_final.h5
CV_CAMERA_INDEX=0
```

## Client UI

`client/` is a checked-in build of the prebuilt Pipecat UI, customized with the
avatar overlay. To rebuild the overlay after changing `frontend/`:

```bash
cd frontend
npm ci
npm run build:overlay   # writes avatar-overlay.js + models into ../client
```

## Transports

| Transport | Command | Needs |
| --- | --- | --- |
| WebRTC (browser) | `uv run bot.py -t webrtc` | `pipecat-ai[webrtc]` (default) |
| Daily | `uv run bot.py -t daily` | `pipecat-ai[daily]`, `DAILY_API_KEY` |
| Twilio | `uv run bot.py -t twilio -x your.ngrok.io` | Twilio keys |
| WebSocket | `uv run bot.py -t websocket` | `pipecat-ai[websocket]` |

The prebuilt client UI is served at `/client` (root URL redirects/connects for
WebRTC).

## Twilio outbound calls

Keep Twilio credentials in `.env`, then set the public HTTPS origin that
forwards to the bot:

```dotenv
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=+1...
PIPECAT_PUBLIC_URL=https://your-public-host.example
```

For production REST authentication, set `TWILIO_API_KEY_SID` and
`TWILIO_API_KEY_SECRET` and omit `TWILIO_AUTH_TOKEN`.

Run the bot in multi-transport mode so browser and outbound calls share one
process:

```bash
uv run bot.py --port 7861 -x your-public-host.example
uv run eklavya-call +15551234567
uv run eklavya-call +15551234567 +15557654321
```

Do not pass `-t twilio` for this setup: it restricts the server to Twilio and
makes the WebRTC browser client reject connections.

## Tests

```bash
uv sync --extra ingest
uv run pytest
```

## Coolify deployment

The `Dockerfile` runs the browser-only WebRTC service on port `7861`. Runtime
environment variables:

```dotenv
GROQ_API_KEY=...
VOICEBOX_URL=...
VOICEBOX_PROFILE=HF Female
VOICEBOX_ENGINE=kokoro
PIPECAT_ALLOWED_ORIGINS=https://conv.shubhsomani.tech
```

`data/` is excluded from the image; mount the OKF corpus (or set `DATA_DIR`) if
the deployment needs course grounding. Set the Coolify domain to your public
host and the container port to `7861`. The image supplies a public STUN server;
use TURN as well if clients must work from restrictive networks.

## Docs

- Pipecat quickstart: https://docs.pipecat.ai/pipecat/get-started/quickstart
- Pipecat examples: https://github.com/pipecat-ai/pipecat/tree/main/examples/getting-started

## Learner website (separate from the developer console)

The learner is a React/TypeScript/Vite static build at `/learn/`, backed by the existing Python/Pipecat tutor. It supports microphone conversation, typed questions, captions, the animated avatar and a spectrum of actual tutor audio. It uses no webcam or attention worker. Typed questions still use the configured voice-response pipeline; a microphone-free connection is not promised.

### Build and run locally

Use Python 3.12, uv, and Node 22.14+ (Node 22 line). After dependencies have been locked, install with:

```bash
npm --prefix frontend ci
npm --prefix frontend run typecheck:learner
npm --prefix frontend run build:learner
uv run end_user_app.py -t webrtc --host 127.0.0.1 --port 7861
```

Open `http://localhost:7861/learn/`. Start grants microphone access only; Resume Audio recovers browser autoplay blocking. End clears the unsaved tab transcript and releases the microphone. A new lease is a new conversation, not restored server memory.

For local UI iteration, run `npm --prefix frontend run dev:learner` in a second terminal and use its printed `/learn/` URL. Its signaling proxy defaults to `http://127.0.0.1:7861`; `LEARNER_BACKEND_URL` changes that build-process setting. Never use the Vite development server as the public deployment.

The unchanged developer command remains `uv run bot.py` (default local port 7860). Do not run both entrypoints on the same port. The developer console and vision code are retained, not exposed as learner features.

### Existing backend prerequisites

Provider keys stay in the backend environment, never JS, `VITE_*`, URLs or public errors. The backend still requires the existing ingested `DATA_DIR/okf` corpus, a valid `COURSE_ID` when configured, Silero/local turn dependencies, and reachability to the configured Groq STT/LLM and Voicebox TTS services. The default Voicebox address is private-network-local and is not proof of deployment reachability. The image excludes `data/`; mount the approved corpus read-only. Do not log course text, transcripts or keys while diagnosing failures.

### Public deployment (release gated)

Do not publish the local runner command. Public delivery requires the approved lease-owned signaling adapter and passing attachment/security/browser acceptance in `docs/end-user-smoke-checks.md`.

Build `end-user-client/` before `docker build`; the Dockerfile intentionally checks for its index, models and DRACO decoder. The default image command stays the developer command. Supply this learner command override through the deployment platform:

```text
uv run end_user_app.py -t webrtc --host 0.0.0.0 --port 7861 --public --public-origin https://YOUR_ACTUAL_HOST
```

`YOUR_ACTUAL_HOST` is the exact release origin configured by the operator, not a literal example hostname to deploy. There is no Node production server. Serve static files and signaling through the same HTTPS origin; do not serve the repository root.

Reverse proxy requirements:
- Terminate valid HTTPS, preserve the exact Host and browser Origin, and route `/`, `/learn/`, `/healthz`, and owned `/session/*` requests to the learner backend.
- Limit request bodies to 256KiB and configure finite timeouts. Preserve POST/PATCH bodies and CSRF headers. No generic fallback to the developer console.
- Make the backend unreachable directly from the Internet. Set `FORWARDED_ALLOW_IPS` to only the actual trusted proxy IPs; never `*`. Do not trust arbitrary forwarded address headers.
- Configure matched ICE on both peers using server-side `PIPECAT_ICE_SERVERS` JSON. The bootstrap returns the same intended browser ICE configuration. Use short-lived TURN credentials for restrictive/NATed networks; TURN configuration is deliberately browser-visible and is not a provider API key.
- Verify real external-network media and TURN relay. HTTPS and an HTTP health check alone do not establish WebRTC reachability. TURN must be reachable from the browser and backend, with required UDP/TCP/TLS ports allowed.
- Run exactly one process/replica. `WEB_CONCURRENCY=1`; no replicas sharing an origin while relying on these in-memory ownership maps.

Anonymous launch defaults are conservative recommendations, not measured capacity: one reserved/active conversation, 30s reservation, 60s setup, 15min maximum lease age, 120s meaningful-user idle, 30 turns, 300 outbound provider attempts per lease and 6,000 attempts globally per rolling day. Start/RTVI/signaling limits also apply. `EKLAVYA_PUBLIC_ENABLED=0` disables admissions; stopping active leases requires graceful shutdown. Counters reset on restart, do not coordinate replicas and do not cap currency spend. Anyone—including automation—can consume allowed anonymous capacity; ownership cookies are not accounts or anti-abuse guarantees.

Only enumerated learner assets and owned session endpoints are public. Raw signaling, developer console, behavior/WebSocket, files, docs, metrics and diagnostics are denied. Provider/dependency logs are suppressed in public mode; only add fixed, reviewed event names if operational logging is needed. No raw errors, transcripts, SDP, capabilities or provider payloads belong in logs.

The visible transcript is unsaved in this tab. This does not establish provider retention, network privacy beyond HTTPS, or an application-wide data-retention guarantee. Generated cited text may differ from clean spoken text; interrupted replies are not represented as fully heard. No full-history reasoning, persistent memory or word-perfect caption timing is promised.
