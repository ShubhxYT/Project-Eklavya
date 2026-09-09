import cv2
import numpy as np
import tensorflow as tf
from tensorflow.keras import layers
import argparse
import json
import os
import struct
import sys
import time
from pathlib import Path

MODEL_PATH = Path(__file__).resolve().parent / "daisee_engagement_model_final.h5"
LABELS = ["Engagement", "Boredom", "Confusion", "Frustration"]


def build_model(model_path: Path):
    base = tf.keras.applications.MobileNetV2(
        weights=None, include_top=False, input_shape=(224, 224, 3)
    )
    model = tf.keras.Sequential(
        [
            layers.Input(shape=(224, 224, 3)),
            base,
            layers.GlobalAveragePooling2D(),
            layers.Dropout(0.3),
            layers.Dense(512, activation="relu"),
            layers.BatchNormalization(),
            layers.Dropout(0.5),
            layers.Dense(256, activation="relu"),
            layers.BatchNormalization(),
            layers.Dropout(0.5),
            layers.Dense(4, activation="sigmoid", name="emotions"),
        ]
    )
    model.load_weights(model_path)
    return model


def emit(payload: dict) -> None:
    print(json.dumps(payload, separators=(",", ":")), flush=True)


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="H5 face engagement camera monitor")
    parser.add_argument("--model-path", type=Path, default=Path(os.getenv("CV_MODEL_PATH", MODEL_PATH)))
    parser.add_argument("--camera-index", type=int, default=int(os.getenv("CV_CAMERA_INDEX", "0")))
    parser.add_argument(
        "--input-stdin",
        action="store_true",
        help="Read length-prefixed JPEG frames from stdin instead of opening a camera window",
    )
    args = parser.parse_args(argv)

    model = build_model(args.model_path)
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    if args.input_stdin:
        run_stdin(model, cascade)
        return

    cap = cv2.VideoCapture(args.camera_index)
    if not cap.isOpened():
        print("Could not open camera", file=sys.stderr)
        return

    monitoring_enabled = False
    last_emit = 0.0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))

            scores = None
            if len(faces) > 0:
                x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)

                face = frame[y : y + h, x : x + w]
                face = cv2.resize(face, (224, 224), interpolation=cv2.INTER_AREA)
                rgb = cv2.cvtColor(face, cv2.COLOR_BGR2RGB)
                inp = np.expand_dims(rgb.astype(np.float32) / 255.0, axis=0)
                scores = model.predict(inp, verbose=0)[0]

            now = time.time()
            if now - last_emit >= 0.5:
                output_scores = scores if scores is not None else [0.0] * 4
                values = {label.casefold(): float(score) for label, score in zip(LABELS, output_scores)}
                emit({
                    "type": "prediction",
                    "timestamp": now,
                    "face_present": scores is not None,
                    "monitoring_enabled": monitoring_enabled,
                    "engagement": values["engagement"],
                    "boredom": values["boredom"],
                    "confusion": values["confusion"],
                    "frustration": values["frustration"],
                })
                last_emit = now

            overlay(frame, scores, monitoring_enabled)
            cv2.imshow("Emotion (h5)", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord("i"):
                monitoring_enabled = not monitoring_enabled
                emit({"type": "monitoring_changed", "enabled": monitoring_enabled, "timestamp": time.time()})
    finally:
        cap.release()
        cv2.destroyAllWindows()


def run_stdin(model, cascade) -> None:
    """Process 4-byte big-endian length-prefixed JPEG frames from stdin."""
    last_emit = 0.0
    while True:
        header = sys.stdin.buffer.read(4)
        if len(header) < 4:
            return
        (size,) = struct.unpack("!I", header)
        if size <= 0 or size > 750_000:
            print(f"Invalid frame size: {size}", file=sys.stderr)
            return
        payload = sys.stdin.buffer.read(size)
        if len(payload) != size:
            return
        frame = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            continue
        scores = infer_frame(model, cascade, frame)
        now = time.time()
        if now - last_emit >= 0.5:
            output_scores = scores if scores is not None else [0.0] * 4
            values = {label.casefold(): float(score) for label, score in zip(LABELS, output_scores)}
            emit({
                "type": "prediction",
                "timestamp": now,
                "face_present": scores is not None,
                "monitoring_enabled": True,
                "engagement": values["engagement"],
                "boredom": values["boredom"],
                "confusion": values["confusion"],
                "frustration": values["frustration"],
            })
            last_emit = now


def infer_frame(model, cascade, frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80)
    )
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
    face = frame[y : y + h, x : x + w]
    face = cv2.resize(face, (224, 224), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(face, cv2.COLOR_BGR2RGB)
    inp = np.expand_dims(rgb.astype(np.float32) / 255.0, axis=0)
    return model.predict(inp, verbose=0)[0]


def overlay(frame, scores, monitoring_enabled=False):
    x0, y0 = 10, 10
    state = "AUTO ON (I toggles)" if monitoring_enabled else "CALIBRATION (I enables)"
    cv2.putText(frame, state, (x0, y0), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 255), 2)
    if scores is None:
        cv2.putText(frame, "No face", (x0, y0 + 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        return
    for i, (label, score) in enumerate(zip(LABELS, scores)):
        pct = max(0.0, min(100.0, float(score) * 100.0))
        text = f"{label}: {pct:5.1f}%"
        y = y0 + 28 + i * 28
        cv2.putText(frame, text, (x0, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)


if __name__ == "__main__":
    main()
