# Avatar overlay frontend

Builds the IIFE overlay that is injected into the prebuilt Pipecat client in
`../client/`.

- `src/overlay/main.ts` — patches `RTCPeerConnection` to capture the bot audio
  track; three.js renders the avatar (Draco GLB + Idle clip + viseme morph
  targets + blinking).
- `src/lipsync.ts`, `src/visemes.ts`, `src/mathUtil.ts` — shared lipsync engine.
- `public/models/` — `avatar.glb`, `animations.glb`.

## Build

```bash
npm ci
npm run build:overlay
```

This writes `avatar-overlay.js` and the models into `../client/`, which is what
`bot.py` serves at `/client`. `client/index.html` already loads the overlay
before the app bundle; remove that `<script>` line to revert.

Anchors: the panel is found via `[data-slot="panel-title"]` = "Bot Video"
(voice-ui-kit markup, pipecat-ai-prebuilt 1.0.6). If you upgrade the pip package
and the markup changes, update `PANEL_TITLE`/selectors in `src/overlay/main.ts`.

## Known limits

- **Remote-audio capture needs a muted element**: Chrome routes WebRTC audio
  straight to hardware, so `createMediaStreamSource` taps silence unless the
  stream is also attached to a **muted** `<audio>` element (crbug 40094084).
  Handled in `lipsync.ts:connectStream` — don't "simplify" the muted element
  away.
- **Lipsync runs on a 30ms `setInterval`, not rAF**: rAF stops firing in
  background/occluded tabs and would starve the viseme feed.
- DRACO decoder is fetched from Google's CDN at runtime.
- Viseme sync is decent but untuned; framing is head-and-torso.
- Debug helpers: `window.__avatarDebug` (per-frame viseme/volume/state),
  `window.__avatarLipsync`, `window.__botStream`.
