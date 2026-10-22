# Learner frontend

Builds the React learner at `/learn/` and owns the shared lipsync engine.

- `learner/` — React UI: session adapter, avatar, audio spectrum, conversation,
  device controls, tests.
- `src/lipsync.ts`, `src/visemes.ts`, `src/mathUtil.ts` — shared lipsync engine.
- `public/models/` — `avatar.glb`, `animations.glb`.
- Output: `../end-user-client/` (checked in; the Dockerfile requires it).

## Build and check

Use Node 22.14+ in the Node 22 line.

```bash
npm ci
npm run dev:learner
npm run test:learner
npm run typecheck:learner
npm run typecheck
npm run build:learner
```

The Vite root is `learner/`, base `/learn/`, public directory `public/`, and
absolute output `../end-user-client/`. The learner build copies the models and
favicon, then `learner/scripts/copy-assets.mjs` copies the DRACO decoder from
the installed Three package into `../end-user-client/draco/`. There is no CDN
or overlay-global dependency at runtime.

## Runtime ownership

The official Pipecat client is created once for the page lifetime. `session.ts`
is the only SDK callback adapter. `BotAudioController` owns the audible player
and the single `Lipsync` analysis context; `Avatar` and `BotAudioSpectrum`
share it. Do not add `PipecatClientAudio`, a microphone analyser, random bars,
a webcam control, or per-frame React state.

Vitest/jsdom tests use fakes and do not prove real browser media behavior. Real
Chrome/Safari media, autoplay, device output, GLB idle/blink/morph, ICE/TURN and
accessibility checks must be recorded separately.

## Known limits

- **Remote-audio capture needs a muted element**: Chrome routes WebRTC audio
  straight to hardware, so `createMediaStreamSource` taps silence unless the
  stream is also attached to a **muted** `<audio>` element (crbug 40094084).
  Handled in `lipsync.ts:connectStream` — don't "simplify" the muted element
  away.
- Viseme sync is decent but untuned; framing is head-and-torso.
- The learner never requests a camera and never feeds microphone audio into the
  avatar analyser.
