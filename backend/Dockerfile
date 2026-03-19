FROM python:3.11-slim-bookworm

WORKDIR /app

# Install Node.js (for Notion MCP server)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Pre-install MCP servers globally so npx doesn't re-download each time
# Add new servers here as they are enabled in backend/config/mcp_servers.yaml
RUN npm install -g @notionhq/notion-mcp-server

# Build context is the project root so backend.* imports resolve correctly
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium + OS deps for headless browser fetching
RUN playwright install --with-deps chromium

COPY . .

EXPOSE 8000

# Create non-root user for security
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup appuser && \
    chown -R appuser:appgroup /app

USER appuser

# Railway sets $PORT dynamically; fall back to 8000 for local docker run
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:${PORT:-8000}/health || exit 1

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
