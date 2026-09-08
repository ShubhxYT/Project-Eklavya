FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 7860

CMD ["uv", "run", "bot.py", "--host", "0.0.0.0", "--port", "7860"]
