// Overlay entry: injects the lip-synced avatar into the stock prebuilt
// Pipecat UI's "Bot Video" panel without touching the UI bundle.
// ponytail: panel located by data-slot attributes from @pipecat-ai/voice-ui-kit
// (v1.0.6-era markup). If the pip package changes markup, update these selectors.
import { DRACOLoader } from "three/examples/jsm/loaders/DRACOLoader.js";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import * as THREE from "three";
import { Lipsync } from "../lipsync";
import VISEMES from "../visemes";

const PANEL_TITLE = "bot video";
const AVATAR_URL = "models/avatar.glb";
const ANIM_URL = "models/animations.glb";

class AvatarOverlay {
  lipsync: Lipsync | null = null;
  blink = false;
  canvas: HTMLCanvasElement | null = null;
  private renderer: THREE.WebGLRenderer | null = null;
  private scene = new THREE.Scene();
  private camera: THREE.PerspectiveCamera;
  private mixer: THREE.AnimationMixer | null = null;
  private clock = new THREE.Clock();
  private skinnedMeshes: THREE.SkinnedMesh[] = [];
  running = false;
  private loopTimer: number | null = null;
  visemeMorphCount = 0;

  constructor() {
    this.camera = new THREE.PerspectiveCamera(30, 1, 0.1, 50);
    this.camera.position.set(0.1, 1.7, 1.0);
    this.camera.lookAt(0, 1.5, 0);
  }

  async load() {
    this.scene.add(new THREE.AmbientLight(0xffffff, 2.2));
    const key = new THREE.DirectionalLight(0xffffff, 2.5);
    key.position.set(1, 2.5, 2);
    this.scene.add(key);
    const rim = new THREE.DirectionalLight(0x8899ff, 1.0);
    rim.position.set(-2, 1.5, -1);
    this.scene.add(rim);

    const loader = new GLTFLoader();
    // avatar.glb is Draco-compressed (Ready Player Me export)
    const draco = new DRACOLoader();
    draco.setDecoderPath("https://www.gstatic.com/draco/versioned/decoders/1.5.7/");
    loader.setDRACOLoader(draco);
    const avatar = await loader.loadAsync(AVATAR_URL);
    this.scene.add(avatar.scene);
    avatar.scene.traverse((child: any) => {
      if (child.isSkinnedMesh) this.skinnedMeshes.push(child);
    });
    this.visemeMorphCount = this.skinnedMeshes.filter(
      (m) => m.morphTargetDictionary?.[VISEMES.aa] !== undefined
    ).length;
    const anim = await loader.loadAsync(ANIM_URL);
    this.mixer = new THREE.AnimationMixer(avatar.scene);
    const clip =
      THREE.AnimationClip.findByName(anim.animations, "Idle") ??
      anim.animations[0];
    if (clip) this.mixer.clipAction(clip).play();
  }

  show(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    // hide the panel's "No video" placeholder while the avatar is active
    for (const el of canvas.parentElement?.children ?? []) {
      if (el !== canvas && el instanceof HTMLElement) {
        el.dataset.prevDisplay = el.style.display;
        el.style.display = "none";
      }
    }
    if (!this.renderer) {
      this.renderer = new THREE.WebGLRenderer({
        canvas,
        alpha: true,
        antialias: true,
      });
      this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    }
    this.resize();
    if (!this.running) {
      this.running = true;
      this.clock.start();
      // ponytail: rAF stops firing in background/occluded tabs and the
      // viseme feed would starve; a 30fps interval keeps lips moving even
      // while the tab is partly hidden.
      this.loopTimer = window.setInterval(() => this.frame(), 33);
    }
    canvas.style.display = "block";
  }

  hide() {
    if (this.canvas) {
      this.canvas.style.display = "none";
      for (const el of this.canvas.parentElement?.children ?? []) {
        if (el !== this.canvas && el instanceof HTMLElement) {
          el.style.display = el.dataset.prevDisplay ?? "";
          delete el.dataset.prevDisplay;
        }
      }
    }
  }

  resize() {
    const canvas = this.canvas;
    if (!canvas || !this.renderer) return;
    const w = canvas.clientWidth || canvas.parentElement?.clientWidth || 1;
    const h = canvas.clientHeight || canvas.parentElement?.clientHeight || 1;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  frame() {
    const dt = this.clock.getDelta();
    this.mixer?.update(dt);
    this.lipsync?.processAudio();

    const viseme = this.lipsync?.viseme ?? VISEMES.sil;
    const isVowel = this.lipsync?.state === "vowel";
    // diagnostics: inspect via window.__avatarDebug in the browser console
    (window as any).__avatarDebug = {
      viseme,
      volume: this.lipsync?.features?.volume ?? null,
      state: this.lipsync?.state ?? null,
      audioCtx: this.lipsync?.audioContext.state ?? null,
      visemeMorphs: this.visemeMorphCount,
      skinnedMeshes: this.skinnedMeshes.length,
    };
    lerpMorph(this.skinnedMeshes, "eyeBlinkLeft", this.blink ? 1 : 0, 0.5);
    lerpMorph(this.skinnedMeshes, "eyeBlinkRight", this.blink ? 1 : 0, 0.5);
    lerpMorph(this.skinnedMeshes, viseme, 1, isVowel ? 0.2 : 0.4);
    for (const v of Object.values(VISEMES)) {
      if (v !== viseme) lerpMorph(this.skinnedMeshes, v, 0, isVowel ? 0.1 : 0.2);
    }

    if (this.renderer && this.canvas && this.canvas.style.display !== "none") {
      this.renderer.render(this.scene, this.camera);
    }
  }
}

function lerpMorph(
  meshes: THREE.SkinnedMesh[],
  target: string,
  value: number,
  speed: number
) {
  for (const mesh of meshes) {
    const index = mesh.morphTargetDictionary?.[target];
    if (index === undefined) continue;
    const influences = mesh.morphTargetInfluences;
    if (!influences || influences[index] === undefined) continue;
    influences[index] = THREE.MathUtils.lerp(influences[index], value, speed);
  }
}

// Blink loop (2-6s random interval, 200ms blink)
const overlay = new AvatarOverlay();
(function blinkLoop() {
  window.setTimeout(() => {
    overlay.blink = true;
    window.setTimeout(() => {
      overlay.blink = false;
      blinkLoop();
    }, 200);
  }, THREE.MathUtils.randInt(2000, 6000));
})();

// ---- Wire into the stock UI ----------------------------------------------

function findVideoPanel(): HTMLElement | null {
  for (const title of document.querySelectorAll('[data-slot="panel-title"]')) {
    if (title.textContent?.trim().toLowerCase() === PANEL_TITLE) {
      return title.closest('[data-slot="panel"]') as HTMLElement | null;
    }
  }
  return null;
}

function inject(panel: HTMLElement, lipsync: Lipsync) {
  const content = panel.querySelector(
    '[data-slot="panel-content"]'
  ) as HTMLElement | null;
  if (!content || content.querySelector("canvas[data-avatar-overlay]")) return;

  const canvas = document.createElement("canvas");
  canvas.setAttribute("data-avatar-overlay", "1");
  canvas.style.cssText =
    "position:absolute;inset:0;width:100%;height:100%;display:none;";
  content.style.position = "relative";
  content.appendChild(canvas);
  new ResizeObserver(() => overlay.resize()).observe(content);
  // Load GLBs lazily, once. Renderer + visibility start on bot audio (show()).
  if (!overlayLoaded) {
    overlayLoaded = true;
    overlay.load().catch((e) => console.error("[avatar-overlay] load failed:", e));
  }

  // Called by the patched RTCPeerConnection whenever the bot's audio arrives.
  // lipsync.connectStream handles the muted-element audio capture itself.
  overlay.lipsync = lipsync;
  onBotAudio = (stream: MediaStream) => {
    (window as any).__botStream = stream; // diagnostics
    lipsync.connectStream(stream);
    overlay.show(canvas);
  };
}

let onBotAudio: ((stream: MediaStream) => void) | null = null;
let overlayLoaded = false;
const lipsync = new Lipsync();
// exposed for diagnostics (window.__avatarLipsync)
(window as any).__avatarLipsync = lipsync;

// Patch RTCPeerConnection BEFORE the app bundle loads (plain script in <head>).
const OrigPC = window.RTCPeerConnection;
class PatchedPC extends OrigPC {
  constructor(...args: ConstructorParameters<typeof OrigPC>) {
    super(...args);
    this.addEventListener("track", (e: RTCTrackEvent) => {
      if (e.track.kind !== "audio") return;
      onBotAudio?.(new MediaStream([e.track]));
    });
    this.addEventListener("connectionstatechange", () => {
      if (
        ["disconnected", "failed", "closed"].includes(this.connectionState)
      ) {
        overlay.hide();
      }
    });
  }
}
window.RTCPeerConnection = PatchedPC as unknown as typeof RTCPeerConnection;

// The panel is React-rendered after load — watch for it, then inject.
const observer = new MutationObserver(() => {
  const panel = findVideoPanel();
  if (panel) {
    inject(panel, lipsync);
    if (panel.querySelector("canvas[data-avatar-overlay]")) observer.disconnect();
  }
});
function start() {
  if (findVideoPanel()) inject(findVideoPanel()!, lipsync);
  else observer.observe(document.body, { childList: true, subtree: true });
}
if (document.body) start();
else document.addEventListener("DOMContentLoaded", start);
