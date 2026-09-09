# Quick start

```bash
# 1. Install the extras the dev runner + WebRTC + VAD need
uv add "pipecat-ai[runner]" "pipecat-ai[webrtc]" "pipecat-ai[silero]" python-dotenv

# 2. Create your env file and add at least OPENAI_API_KEY
cp .env.example .env

# 3. Run the bot
uv run bot.py
```

Open http://localhost:7860 in your browser and click **Connect** to talk to the
bot. First run can take ~20s while models/SDKs warm up.

## File-grounded tutor (Drona)

The bot answers questions **only from an ingested course document** rather than
from a general LLM. Grounding uses the Drona OKF pipeline under `tutor/`:

1. Ingest a PDF/DOCX into the corpus (one-time, CLI):
   ```bash
   cd tutor
   uv run cli.py ingest /path/to/course.pdf      # or a directory of files
   ```
   This parses with Docling and writes an OKF bundle under `tutor/data/okf/<course-id>/`.
2. Run the bot. It loads the ingested course via `FileCatalog` (BM25 retrieval),
   grounds each answer in the matched sections, validates the `[S#]` citations,
   and falls back to a general chit-chat answer (noting the material doesn't
   cover it) when nothing matches.

The bot auto-picks the course if only one is ingested; set `COURSE_ID` to
disambiguate. Relevant env vars (see `.env.example`):

```dotenv
DATA_DIR=tutor/data          # must match where `tutor ingest` writes
# COURSE_ID=<course id>
GROQ_BASE_URL=https://api.groq.com/openai/v1
GROQ_MODEL=openai/gpt-oss-120b
```

Citations appear in the text transcript but are stripped from the spoken audio.

## Local behavior-aware voice test

The H5 engagement model runs in a separate Python 3.13 process while the voice
bot remains on Python 3.14. Camera frames come from the browser, so no native
OpenCV window is opened. This phase is local-host only; the Docker image does
not start a camera process.

Create the model environment once:

```bash
uv venv --python 3.13 CV/.venv-h5
uv pip install --python CV/.venv-h5/bin/python -r CV/requirements-h5.txt
```

Start the bot normally with `uv run bot.py`, open the local client, and click
Connect. In the Bot Video header, turn on the Camera toggle to grant permission
and begin browser-frame sensing. The mirrored self-view appears in the panel's
bottom-right corner; turning the toggle off stops the camera and behavior
sensing immediately.
Camera permission is available on `localhost` or HTTPS origins in Chrome.

The first-test policy uses absolute thresholds: Engagement ≤40%, Boredom ≥60%,
Confusion ≥65%, or Frustration ≥65%, after a smoothed breach lasting five
seconds. A 60-second cooldown and five-point recovery hysteresis prevent
repeated interruptions. Missing cameras, denied permission, disconnected
streams, and no-face periods fail silently and leave voice chat running.

Override local paths if needed:

```dotenv
CV_PYTHON=/absolute/path/to/CV/.venv-h5/bin/python
CV_MODEL_PATH=/absolute/path/to/CV/daisee_engagement_model_final.h5
CV_CAMERA_INDEX=0
```


## What's in here

- `bot.py` — a simple voice agent: mic audio → STT → LLM → TTS → speaker.
  Defaults to OpenAI for all three services (`OPENAI_API_KEY` only). Comments
  in the file show how to swap in Deepgram / Cartesia / Anthropic, etc.
- `.env.example` — every API key Pipecat accepts, grouped by category
  (STT, LLM, TTS, realtime, transports, ...). Each key lists the `uv add`
  extra that installs its provider SDK.
- `src/my_pipecat_app/` — default `uv init` package (unused by `bot.py`).

## Picking different services

1. Copy the key you need from `.env.example` into `.env`.
2. Install the matching extra, e.g. `uv add "pipecat-ai[deepgram]"`.
3. Swap the service constructor in `bot.py` (commented examples included).

## Transports

`bot.py` uses the Pipecat dev runner, which supports multiple transports:

| Transport | Command | Needs |
| --- | --- | --- |
| WebRTC (browser) | `python bot.py -t webrtc` | `pipecat-ai[webrtc]` (default) |
| Daily | `python bot.py -t daily` | `pipecat-ai[daily]`, `DAILY_API_KEY` |
| Twilio | `python bot.py -t twilio -x your.ngrok.io` | `pipecat-ai[websocket]`, Twilio keys |
| WebSocket | `python bot.py -t websocket` | `pipecat-ai[websocket]` |

The prebuilt client UI is served at the root URL for WebRTC/Daily.

## Coolify deployment

The included `Dockerfile` runs the browser-only WebRTC service on port `7861`.
Configure these runtime environment variables in Coolify (do not commit the
local `.env` file):

```dotenv
GROQ_API_KEY=...
VOICEBOX_URL=...
VOICEBOX_PROFILE=HF Female
VOICEBOX_ENGINE=kokoro
PIPECAT_ALLOWED_ORIGINS=https://conv.shubhsomani.tech
```

Set the Coolify domain to `https://conv.shubhsomani.tech` and the container
port to `7861`. The image supplies a public STUN server for WebRTC candidate
discovery; use a TURN service as well if clients must work from restrictive
networks.

## Twilio outbound calls

Keep Twilio credentials in `.env` (which is ignored by Git), then set the
public HTTPS origin that forwards to the bot:

```dotenv
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_PHONE_NUMBER=+1...
PIPECAT_PUBLIC_URL=https://your-public-host.example
```

For production REST authentication, set `TWILIO_API_KEY_SID` and
`TWILIO_API_KEY_SECRET`, then omit `TWILIO_AUTH_TOKEN` from the deployed
environment. Local trial accounts can keep the Auth Token for compatibility.

Start the bot in multi-transport mode so both the browser UI and outbound
Twilio calls work from the same process:

```bash
uv run bot.py --port 7861 -x your-public-host.example
```

Do not pass `-t twilio` for this setup: that option intentionally restricts
the server to Twilio and makes the WebRTC browser UI reject connections.
`call.py` sends the Twilio Media Stream instructions inline, so it does not
need a Twilio-only `POST /` webhook.

Place one call, or queue several calls at once:

```bash
uv run call.py +15551234567
uv run call.py +15551234567 +15557654321
```

## Docs

- Quickstart: https://docs.pipecat.ai/pipecat/get-started/quickstart
- Examples repo: https://github.com/pipecat-ai/pipecat/tree/main/examples/getting-started
