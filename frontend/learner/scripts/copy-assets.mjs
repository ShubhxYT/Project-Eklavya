import { copyFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const source = new URL("../../node_modules/three/examples/jsm/libs/draco/gltf/", import.meta.url);
const output = new URL("../../end-user-client/draco/", import.meta.url);
await mkdir(output, { recursive: true });
for (const name of ["draco_decoder.js", "draco_decoder.wasm", "draco_wasm_wrapper.js"]) {
  await copyFile(fileURLToPath(new URL(name, source)), fileURLToPath(new URL(name, output)));
}
