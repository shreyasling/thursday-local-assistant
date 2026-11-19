FROM node:22-alpine AS web-build
WORKDIR /src/assistant/web
COPY assistant/web/package.json assistant/web/package-lock.json ./
RUN npm ci
COPY assistant/web/ ./
RUN npm run build

FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    THURSDAY_HOST=0.0.0.0 \
    THURSDAY_PORT=5005 \
    THURSDAY_ALLOW_REMOTE=1 \
    THURSDAY_HYPRUSE=0 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /app
COPY pyproject.toml README.md ./
COPY assistant/ ./assistant/
RUN pip install --no-cache-dir . \
    && python -m playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright \
    && rm -rf /var/lib/apt/lists/*
COPY --from=web-build /src/assistant/web/dist ./assistant/web/dist
RUN useradd --system --uid 10001 --create-home --home-dir /home/thursday thursday \
    && mkdir -p /data /workspace \
    && chown -R 10001:10001 /app /data /workspace
USER 10001:10001
EXPOSE 5005
CMD ["sh", "-c", "if [ -z \"$THURSDAY_API_TOKEN\" ]; then echo 'ERROR: Set THURSDAY_API_TOKEN in Dokploy before starting.' >&2; exit 1; fi; exec python -m assistant.main --web --no-browser --config /app/assistant/config/server.json"]