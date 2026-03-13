FROM python:3.11-slim

WORKDIR /app

# Install Node.js + Chromium dependencies (for Notion MCP server + agent-browser)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    # Chromium dependencies for agent-browser headless fetching
    chromium \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libnss3 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    xdg-utils && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Pre-install MCP servers globally so npx doesn't re-download each time
# Add new servers here as they are enabled in backend/config/mcp_servers.yaml
RUN npm install -g @notionhq/notion-mcp-server agent-browser

# Build context is the project root so backend.* imports resolve correctly
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure SQLite data directory exists (will be mounted as volume on Railway)
RUN mkdir -p backend/data

EXPOSE 8000

# Railway sets $PORT dynamically; fall back to 8000 for local docker run
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
