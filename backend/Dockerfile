FROM python:3.11-slim

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

COPY . .

EXPOSE 8000

# Railway sets $PORT dynamically; fall back to 8000 for local docker run
CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
