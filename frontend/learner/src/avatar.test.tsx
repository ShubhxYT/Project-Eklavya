import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, render, screen } from "@testing-library/react";
import * as THREE from "three";
import { disposeObject, updateMorphs, Avatar } from "./Avatar";
import type { BotAudioController } from "./BotAudioController";

const visual = vi.hoisted(() => ({
  fail: false, load: vi.fn(), play: vi.fn(), update: vi.fn(),
  rendererDispose: vi.fn(), dracoDispose: vi.fn(), disconnect: vi.fn(),
}));
vi.mock("three", async () => {
  const real = await vi.importActual<typeof import("three")>("three");
  return { ...real,
    WebGLRenderer: class {
      domElement = document.createElement("canvas");
      constructor() { if (visual.fail) throw new Error("no WebGL"); }
      setPixelRatio() {} setSize() {} render() {}
      dispose = visual.rendererDispose;
    },
    AnimationMixer: class {
      clipAction() { return { play: visual.play }; }
      update = visual.update;
      stopAllAction() {} uncacheRoot() {}
    },
  };
});
vi.mock("three/examples/jsm/loaders/GLTFLoader.js", () => ({ GLTFLoader: class {
  setDRACOLoader() { return this; }
  loadAsync = visual.load;
} }));
vi.mock("three/examples/jsm/loaders/DRACOLoader.js", () => ({ DRACOLoader: class {
  setDecoderPath() {}
  dispose = visual.dracoDispose;
} }));

afterEach(() => {
  cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks();
  visual.fail = false; visual.load.mockReset();
  visual.play.mockClear(); visual.update.mockClear();
  visual.rendererDispose.mockClear(); visual.dracoDispose.mockClear(); visual.disconnect.mockClear();
});

it("updates actual blink and viseme morphs and neutralizes old visemes", () => {
  const mesh = new THREE.SkinnedMesh();
  mesh.morphTargetDictionary = { eyeBlinkLeft: 0, eyeBlinkRight: 1, viseme_aa: 2, viseme_sil: 3 };
  mesh.morphTargetInfluences = [0, 0, 0, 0];
  updateMorphs([mesh], "viseme_aa", true);
  expect(mesh.morphTargetInfluences[0]).toBeGreaterThan(0);
  expect(mesh.morphTargetInfluences[2]).toBeGreaterThan(0);
  for (let i = 0; i < 40; i++) updateMorphs([mesh], "viseme_sil", false);
  expect(mesh.morphTargetInfluences[2]).toBeLessThan(.001);
  expect(mesh.morphTargetInfluences[3]).toBeGreaterThan(.99);
});

it("disposes owned GPU geometry/materials", () => {
  const geometry = new THREE.BoxGeometry();
  const material = new THREE.MeshBasicMaterial();
  const disposeGeometry = vi.spyOn(geometry, "dispose");
  const disposeMaterial = vi.spyOn(material, "dispose");
  disposeObject(new THREE.Mesh(geometry, material));
  expect(disposeGeometry).toHaveBeenCalledOnce();
  expect(disposeMaterial).toHaveBeenCalledOnce();
});

function browserFakes() {
  let draw: FrameRequestCallback = () => {};
  const reduced = { matches: false };
  vi.stubGlobal("matchMedia", () => reduced);
  vi.stubGlobal("ResizeObserver", class { observe() {} disconnect = visual.disconnect; });
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { draw = callback; return 1; });
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  vi.spyOn(performance, "now").mockReturnValue(0);
  return { tick: (time: number) => act(() => draw(time)), reduced };
}

it("loads the actual idle clip, blinks/morphs, pauses hidden drawing and disposes", async () => {
  const browser = browserFakes();
  const group = new THREE.Group();
  const mesh = new THREE.SkinnedMesh();
  mesh.morphTargetDictionary = { eyeBlinkLeft: 0, viseme_aa: 1, viseme_sil: 2 };
  mesh.morphTargetInfluences = [0, 0, 0]; group.add(mesh);
  visual.load.mockResolvedValueOnce({ scene: group })
    .mockResolvedValueOnce({ scene: new THREE.Group(), animations: [new THREE.AnimationClip("Idle", 1, [])] });
  const audio = { sample: vi.fn(), lipsync: { viseme: "viseme_aa" }, dispose: vi.fn() } as unknown as BotAudioController;
  const mounted = render(<Avatar audio={audio} />);
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
  expect(visual.play).toHaveBeenCalledOnce();
  browser.tick(3100);
  expect(mesh.morphTargetInfluences[0]).toBeGreaterThan(0);
  expect(mesh.morphTargetInfluences[1]).toBeGreaterThan(0);
  expect(visual.update).toHaveBeenCalled();
  visual.update.mockClear(); browser.reduced.matches = true;
  browser.tick(3200); expect(visual.update).not.toHaveBeenCalled();
  const samples = vi.mocked(audio.sample).mock.calls.length;
  vi.spyOn(document, "hidden", "get").mockReturnValue(true);
  browser.tick(3300); expect(audio.sample).toHaveBeenCalledTimes(samples);
  mounted.unmount();
  expect(visual.disconnect).toHaveBeenCalledOnce();
  expect(visual.rendererDispose).toHaveBeenCalledOnce();
  expect(visual.dracoDispose).toHaveBeenCalledOnce();
  expect(audio.dispose).not.toHaveBeenCalled();
});

it("disposes an avatar that resolves after unmount", async () => {
  browserFakes();
  const geometry = new THREE.BoxGeometry();
  const dispose = vi.spyOn(geometry, "dispose");
  let resolve!: (value: unknown) => void;
  visual.load.mockImplementation(() => new Promise((done) => { resolve = done; }));
  const mounted = render(<Avatar audio={{ sample: vi.fn() } as unknown as BotAudioController} />);
  mounted.unmount();
  await act(async () => { resolve({ scene: new THREE.Mesh(geometry, new THREE.MeshBasicMaterial()) }); });
  expect(dispose).toHaveBeenCalledOnce();
});

it("keeps voice ownership independent of WebGL failure", () => {
  browserFakes(); visual.fail = true;
  const audio = { dispose: vi.fn() } as unknown as BotAudioController;
  render(<Avatar audio={audio} />);
  expect(screen.getByText(/Voice and text remain available/)).toBeTruthy();
  expect(audio.dispose).not.toHaveBeenCalled();
});
