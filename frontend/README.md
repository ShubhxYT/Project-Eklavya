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

## Isolated learner app

`learner/` is the React learner; `src/overlay/` remains the independent developer overlay. Use Node 22.14+ in the Node 22 line.

```bash
npm ci
npm run dev:learner
npm run test:learner
npm run typecheck:learner
npm run typecheck
npm run build:learner
```

The learner Vite root is `learner/`, base `/learn/`, public directory `public/`, and absolute output `../end-user-client/`. Never point its output at `../client/`. Models/favicon are copied by Vite; the build’s copy-assets script copies DRACO decoder files from the exact installed Three package. No CDN or overlay globals are required at runtime.

The official Pipecat client is owned once for the page lifetime. `session.ts` is the only SDK callback adapter. `BotAudioController` owns the audible player and single Lipsync analysis context; Avatar and spectrum share it. Do not add `PipecatClientAudio`, a microphone analyser, random bars, a webcam control or per-frame React state.

Vitest/jsdom tests use fakes and prove no real browser media behavior. Real Chrome/Safari media, autoplay, device output, GLB idle/blink/morph, ICE/TURN and accessibility checks must be recorded separately. Existing `build:overlay` and `typecheck` commands remain unchanged.
