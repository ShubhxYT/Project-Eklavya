import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/examples/jsm/loaders/DRACOLoader.js";
import VISEMES from "../../src/visemes";
import type { BotAudioController } from "./BotAudioController";

export function disposeObject(root: THREE.Object3D): void {
  const textures = new Set<THREE.Texture>();
  const materials = new Set<THREE.Material>();
  const geometries = new Set<THREE.BufferGeometry>();
  root.traverse((node) => {
    if (!(node instanceof THREE.Mesh)) return;
    geometries.add(node.geometry);
    for (const material of Array.isArray(node.material) ? node.material : [node.material]) {
      materials.add(material);
      for (const value of Object.values(material)) if (value instanceof THREE.Texture) textures.add(value);
    }
  });
  textures.forEach((texture) => texture.dispose());
  materials.forEach((material) => material.dispose());
  geometries.forEach((geometry) => geometry.dispose());
}

export function updateMorphs(meshes: THREE.SkinnedMesh[], viseme: string, blink: boolean): void {
  for (const mesh of meshes) {
    const values = mesh.morphTargetInfluences;
    const names = mesh.morphTargetDictionary;
    if (!values || !names) continue;
    for (const name of ["eyeBlinkLeft", "eyeBlinkRight", ...Object.values(VISEMES)]) {
      const index = names[name];
      if (index === undefined) continue;
      const target = name.startsWith("eyeBlink") ? Number(blink) : Number(name === viseme);
      values[index] = THREE.MathUtils.lerp(values[index], target, 0.35);
    }
  }
}

export function Avatar({ audio }: { audio: BotAudioController }) {
  const host = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const container = host.current!;
    let stopped = false;
    let frame = 0;
    let last = 0;
    let nextBlink = performance.now() + 3000;
    let blinkUntil = 0;
    let model: THREE.Object3D | undefined;
    let animationRoot: THREE.Object3D | undefined;
    let mixer: THREE.AnimationMixer | undefined;
    const meshes: THREE.SkinnedMesh[] = [];
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 50);
    camera.position.set(0.1, 1.7, 1);
    camera.lookAt(0, 1.5, 0);
    let renderer: THREE.WebGLRenderer;
    try { renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true }); }
    catch { setFailed(true); return; }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    container.append(renderer.domElement);
    scene.add(new THREE.AmbientLight(0xffffff, 2.2));
    const key = new THREE.DirectionalLight(0xffffff, 2.5);
    key.position.set(1, 2.5, 2); scene.add(key);
    const rim = new THREE.DirectionalLight(0x8899ff, 1);
    rim.position.set(-2, 1.5, -1); scene.add(rim);
    const draco = new DRACOLoader();
    draco.setDecoderPath(`${import.meta.env.BASE_URL}draco/`);
    const loader = new GLTFLoader().setDRACOLoader(draco);
    const reduced = matchMedia("(prefers-reduced-motion: reduce)");
    const resize = () => {
      const width = Math.max(container.clientWidth, 1);
      const height = Math.max(container.clientHeight, 1);
      renderer.setSize(width, height);
      camera.aspect = width / height; camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(container); resize();
    const visibility = () => { last = 0; };
    document.addEventListener("visibilitychange", visibility);
    const contextLost = (event: Event) => { event.preventDefault(); setFailed(true); };
    renderer.domElement.addEventListener("webglcontextlost", contextLost);

    void (async () => {
      const avatar = await loader.loadAsync(`${import.meta.env.BASE_URL}models/avatar.glb`);
      if (stopped) { disposeObject(avatar.scene); return; }
      model = avatar.scene; scene.add(model);
      model.traverse((node) => { if (node instanceof THREE.SkinnedMesh) meshes.push(node); });
      const animation = await loader.loadAsync(`${import.meta.env.BASE_URL}models/animations.glb`);
      if (stopped) { disposeObject(animation.scene); return; }
      animationRoot = animation.scene;
      mixer = new THREE.AnimationMixer(model);
      const clip = THREE.AnimationClip.findByName(animation.animations, "Idle") ?? animation.animations[0];
      if (clip) mixer.clipAction(clip).play();
    })().catch(() => { if (!stopped) setFailed(true); });

    const draw = (now: number) => {
      if (stopped) return;
      frame = requestAnimationFrame(draw);
      if (document.hidden || now - last < 1000 / 30) return;
      const delta = last ? Math.min((now - last) / 1000, 0.1) : 0;
      last = now;
      audio.sample();
      if (!reduced.matches) {
        mixer?.update(delta);
        if (now >= nextBlink) { blinkUntil = now + 200; nextBlink = now + 2000 + Math.random() * 4000; }
      }
      const viseme = audio.lipsync?.viseme ?? VISEMES.sil;
      updateMorphs(meshes, viseme, !reduced.matches && now < blinkUntil);
      renderer.render(scene, camera);
    };
    frame = requestAnimationFrame(draw);
    return () => {
      stopped = true; cancelAnimationFrame(frame); observer.disconnect();
      document.removeEventListener("visibilitychange", visibility);
      renderer.domElement.removeEventListener("webglcontextlost", contextLost);
      mixer?.stopAllAction(); if (model) mixer?.uncacheRoot(model);
      if (model) disposeObject(model);
      if (animationRoot) disposeObject(animationRoot);
      draco.dispose(); renderer.dispose(); renderer.domElement.remove();
    };
  }, [audio]);
  return <div className="avatar" ref={host} aria-label="Animated tutor">
    {failed && <p className="avatar-fallback">Your tutor is here.<br />Voice and text remain available.</p>}
  </div>;
}
