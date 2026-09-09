# Avatar frontend (experimental)

Two ways to get the Wawa-Lipsync-driven avatar, both built from this dir:

## 1. Avatar overlay inside the stock prebuilt UI (active)

Keeps `ui/` (the prebuilt Pipecat UI) intact and injects a canvas over its
"Bot Video" panel:

- `src/overlay/main.ts` — patched `RTCPeerConnection` captures the bot's
  audio track, three.js renders the avatar (Draco GLB + Idle clip + viseme
  morph targets + blinking).
- `npm run build:overlay` — builds IIFE, copies `avatar-overlay.js` and
  `public/models/*` into `../ui/`.
- `ui/index.html` gains one `<script src="./avatar-overlay.js"></script>`
  line (before the app bundle). Remove that line to fully revert.

Anchors: panel found via `[data-slot="panel-title"]` = "Bot Video"
(voice-ui-kit markup, pipecat-ai-prebuilt 1.0.6). If you upgrade the pip
package and the markup changes, update `PANEL_TITLE`/selectors in
`src/overlay/main.ts`.

Known limits:
- **Remote-audio capture needs a muted element**: Chrome routes WebRTC audio
  straight to hardware, so `createMediaStreamSource` taps silence unless the
  stream is also attached to a **muted** `<audio>` element
  (crbug 40094084). Handled in `lipsync.ts:connectStream` — don't "simplify"
  the muted element away.
- **Lipsync runs on a 30ms `setInterval`, not rAF**: rAF stops firing in
  background/occluded tabs and would starve the viseme feed.
- DRACO decoder is fetched from Google's CDN at runtime.
- Viseme sync is decent but untuned; framing is head-and-torso.
- Debug helpers: `window.__avatarDebug` (per-frame viseme/volume/state),
  `window.__avatarLipsync`, `window.__botStream`.

## 2. Standalone custom UI (optional, not served by default)

`npm run build` builds a small custom React client to `frontend/dist`. To
use it, point the client mount in `bot.py` at `frontend/dist` instead of
`ui/`:

```python
app.mount("/client", StaticFiles(directory="frontend/dist", html=True), name="client")
```

Dev mode: `npm run dev` (proxies `/api` to localhost:7861).

## Connection note

The bot audio → analyser path requires `client.connect({ webrtcRequestParams:
{ endpoint: "/api/offer" } })` in the standalone UI — passing `{ endpoint }`
directly routes through `startBot()` which POSTs an empty body and 422s.
The stock UI uses the `/start` + `/sessions/:id/api/offer` flow and needs
no such workaround.
