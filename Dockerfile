FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# The bot runs on Python 3.12, while TensorFlow's supported runtime for the H5
# worker is Python 3.13. Keep the CV worker isolated in its own interpreter.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV CV_PYTHON=/opt/cv-venv/bin/python \
    CV_MODEL_PATH=/app/vision/daisee_engagement_model_final.h5

# Install deps first (cached layer) — project files copied after.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Install the browser-frame H5 worker dependencies without the GUI-enabled
# OpenCV stack. This layer is cached independently from application changes.
COPY vision/requirements-h5.txt /tmp/requirements-h5.txt
RUN uv python install 3.13 \
    && uv venv --python 3.13 /opt/cv-venv \
    && uv pip install --python /opt/cv-venv/bin/python -r /tmp/requirements-h5.txt

COPY . .
# Fail the image build if the separate learner delivery was not built first.
# Keep CV layers and the legacy bot; public ASGI denies their routes.
RUN test -f /app/end_user_app.py \
    && test -f /app/frontend/end-user-client/index.html \
    && test -f /app/frontend/end-user-client/models/avatar.glb \
    && test -f /app/frontend/end-user-client/models/animations.glb \
    && test -f /app/frontend/end-user-client/draco/draco_decoder.wasm \
    && test -f /app/frontend/end-user-client/draco/draco_wasm_wrapper.js \
    && test -f /app/frontend/end-user-client/draco/draco_decoder.js
RUN uv sync --frozen --no-dev

EXPOSE 7861

CMD ["uv", "run", "bot.py", "--host", "0.0.0.0", "--port", "7861"]
