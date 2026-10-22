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
