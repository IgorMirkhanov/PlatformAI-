# syntax=docker/dockerfile:1.7
# MP.AI WhatsApp Baileys microservice (production)

############################
# Stage 1 — dependencies
############################
FROM node:20-alpine AS deps

WORKDIR /app

RUN apk add --no-cache libc6-compat

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

############################
# Stage 2 — runtime
############################
FROM node:20-alpine AS runtime

WORKDIR /app

ENV NODE_ENV=production \
    PORT=3001 \
    HOST=0.0.0.0 \
    SESSIONS_DIR=/app/whatsapp-sessions

RUN apk add --no-cache libc6-compat wget \
    && addgroup --system --gid 1001 whatsapp \
    && adduser --system --uid 1001 -G whatsapp whatsapp \
    && mkdir -p /app/whatsapp-sessions \
    && chown -R whatsapp:whatsapp /app

COPY --from=deps --chown=whatsapp:whatsapp /app/node_modules ./node_modules
COPY --chown=whatsapp:whatsapp package.json ./
COPY --chown=whatsapp:whatsapp server.js ./

USER whatsapp

EXPOSE 3001

HEALTHCHECK --interval=20s --timeout=5s --start-period=25s --retries=5 \
  CMD wget -qO- http://127.0.0.1:3001/health >/dev/null || exit 1

CMD ["node", "server.js"]
