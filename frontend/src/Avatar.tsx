// Avatar adapted from wass08/wawa-lipsync examples/lipsync-demo (MIT).
// Model: Ready Player Me avatar with Oculus viseme morph targets + an
// animations.glb providing the Idle clip. Swap either file in
// frontend/public/models/ for your own character.
import { useAnimations, useGLTF } from "@react-three/drei";
import { useFrame } from "@react-three/fiber";
import { Canvas } from "@react-three/fiber";
import { MutableRefObject, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { Lipsync } from "./lipsync";
import VISEMES from "./visemes";

function Avatar({ lipsync }: { lipsync: MutableRefObject<Lipsync | null> }) {
  // typed as any: GLTF node types are Object3D; the skinned-mesh list below
  // matches this specific avatar.glb.
  const { nodes, materials, scene } = useGLTF("models/avatar.glb") as any;
  const { animations } = useGLTF("models/animations.glb");
  const group = useRef<THREE.Group>(null);
  const { actions } = useAnimations(animations, group);

  useEffect(() => {
    const name = animations.find((a) => a.name === "Idle")
      ? "Idle"
      : animations[0]?.name;
    if (!name || !actions[name]) return;
    actions[name]!.reset().fadeIn(0.5).play();
    return () => {
      actions[name]!.fadeOut(0.5);
    };
  }, [actions, animations]);

  const lerpMorph = (target: string, value: number, speed = 0.3) => {
    scene.traverse((child: any) => {
      if (child.isSkinnedMesh && child.morphTargetDictionary) {
        const index = child.morphTargetDictionary[target];
        if (index === undefined || child.morphTargetInfluences[index] === undefined) {
          return;
        }
        child.morphTargetInfluences[index] = THREE.MathUtils.lerp(
          child.morphTargetInfluences[index],
          value,
          speed
        );
      }
    });
  };

  const [blink, setBlink] = useState(false);
  useEffect(() => {
    let t: number;
    const nextBlink = () => {
      t = window.setTimeout(() => {
        setBlink(true);
        window.setTimeout(() => {
          setBlink(false);
          nextBlink();
        }, 200);
      }, THREE.MathUtils.randInt(2000, 6000));
    };
    nextBlink();
    return () => clearTimeout(t);
  }, []);

  useFrame(() => {
    const l = lipsync.current;
    l?.processAudio();
    lerpMorph("eyeBlinkLeft", blink ? 1 : 0, 0.5);
    lerpMorph("eyeBlinkRight", blink ? 1 : 0, 0.5);

    const viseme = l?.viseme ?? VISEMES.sil;
    const isVowel = l?.state === "vowel";
    lerpMorph(viseme, 1, isVowel ? 0.2 : 0.4);
    Object.values(VISEMES).forEach((v) => {
      if (v !== viseme) {
        lerpMorph(v, 0, isVowel ? 0.1 : 0.2);
      }
    });
  });

  return (
    <group ref={group} dispose={null}>
      <primitive object={nodes.Hips} />
      <skinnedMesh
        name="Wolf3D_Body"
        geometry={nodes.Wolf3D_Body.geometry}
        material={materials.Wolf3D_Body}
        skeleton={nodes.Wolf3D_Body.skeleton}
      />
      <skinnedMesh
        name="Wolf3D_Outfit_Bottom"
        geometry={nodes.Wolf3D_Outfit_Bottom.geometry}
        material={materials.Wolf3D_Outfit_Bottom}
        skeleton={nodes.Wolf3D_Outfit_Bottom.skeleton}
      />
      <skinnedMesh
        name="Wolf3D_Outfit_Footwear"
        geometry={nodes.Wolf3D_Outfit_Footwear.geometry}
        material={materials.Wolf3D_Outfit_Footwear}
        skeleton={nodes.Wolf3D_Outfit_Footwear.skeleton}
      />
      <skinnedMesh
        name="Wolf3D_Outfit_Top"
        geometry={nodes.Wolf3D_Outfit_Top.geometry}
        material={materials.Wolf3D_Outfit_Top}
        skeleton={nodes.Wolf3D_Outfit_Top.skeleton}
      />
      <skinnedMesh
        name="Wolf3D_Hair"
        geometry={nodes.Wolf3D_Hair.geometry}
        material={materials.Wolf3D_Hair}
        skeleton={nodes.Wolf3D_Hair.skeleton}
      />
      <skinnedMesh
        name="EyeLeft"
        geometry={nodes.EyeLeft.geometry}
        material={materials.Wolf3D_Eye}
        skeleton={nodes.EyeLeft.skeleton}
        morphTargetDictionary={nodes.EyeLeft.morphTargetDictionary}
        morphTargetInfluences={nodes.EyeLeft.morphTargetInfluences}
      />
      <skinnedMesh
        name="EyeRight"
        geometry={nodes.EyeRight.geometry}
        material={materials.Wolf3D_Eye}
        skeleton={nodes.EyeRight.skeleton}
        morphTargetDictionary={nodes.EyeRight.morphTargetDictionary}
        morphTargetInfluences={nodes.EyeRight.morphTargetInfluences}
      />
      <skinnedMesh
        name="Wolf3D_Head"
        geometry={nodes.Wolf3D_Head.geometry}
        material={materials.Wolf3D_Skin}
        skeleton={nodes.Wolf3D_Head.skeleton}
        morphTargetDictionary={nodes.Wolf3D_Head.morphTargetDictionary}
        morphTargetInfluences={nodes.Wolf3D_Head.morphTargetInfluences}
      />
      <skinnedMesh
        name="Wolf3D_Teeth"
        geometry={nodes.Wolf3D_Teeth.geometry}
        material={materials.Wolf3D_Teeth}
        skeleton={nodes.Wolf3D_Teeth.skeleton}
        morphTargetDictionary={nodes.Wolf3D_Teeth.morphTargetDictionary}
        morphTargetInfluences={nodes.Wolf3D_Teeth.morphTargetInfluences}
      />
    </group>
  );
}

useGLTF.preload("models/avatar.glb");
useGLTF.preload("models/animations.glb");

export function AvatarScene({
  lipsync,
}: {
  lipsync: MutableRefObject<Lipsync | null>;
}) {
  return (
    <Canvas
      camera={{ position: [0, 1.55, 1.4], fov: 30 }}
      onCreated={({ camera }) => camera.lookAt(0, 1.4, 0)}
    >
      <ambientLight intensity={0.7} />
      <directionalLight position={[1, 2.5, 2]} intensity={1.8} />
      <directionalLight position={[-2, 1.5, -1]} intensity={0.6} color="#8899ff" />
      <Avatar lipsync={lipsync} />
    </Canvas>
  );
}
