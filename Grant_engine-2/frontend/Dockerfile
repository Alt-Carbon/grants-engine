FROM node:18-alpine AS base

# --- Dependencies ---
FROM base AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

# --- Build ---
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Build-time env vars (Railway injects these)
ARG MONGODB_URI
ARG FASTAPI_URL
ARG INTERNAL_SECRET
ARG CRON_SECRET

ENV MONGODB_URI=$MONGODB_URI
ENV FASTAPI_URL=$FASTAPI_URL
ENV INTERNAL_SECRET=$INTERNAL_SECRET
ENV CRON_SECRET=$CRON_SECRET

RUN npm run build

# --- Production ---
FROM base AS runner
WORKDIR /app
ENV NODE_ENV=production

RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs

# Copy standalone output + static/public assets
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public 2>/dev/null || true

USER nextjs
EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
