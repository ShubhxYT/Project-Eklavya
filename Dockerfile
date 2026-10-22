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
RUN uv sync --frozen --no-dev

EXPOSE 7861

CMD ["uv", "run", "bot.py", "--host", "0.0.0.0", "--port", "7861"]
