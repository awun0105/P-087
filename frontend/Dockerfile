# syntax=docker/dockerfile:1

FROM node:24.15.0-bookworm-slim AS dependencies

WORKDIR /app
COPY package.json package-lock.json ./
COPY scripts/patch-viewer-collision.mjs scripts/patch-viewer-collision.mjs
RUN npm ci --no-audit --no-fund

# SuperSplat is checked into the repository as a separately licensed vendor
# checkout.  Its lockfile is installed in the build stage so the editor is
# generated from the pinned source, while its node_modules never enter the
# final image.
COPY vendor/supersplat/package.json vendor/supersplat/package-lock.json ./vendor/supersplat/
RUN cd vendor/supersplat && npm ci --no-audit --no-fund

FROM dependencies AS builder

ARG REAL2SIM_API_URL=http://api:8000
ENV REAL2SIM_API_URL=${REAL2SIM_API_URL} \
    NEXT_TELEMETRY_DISABLED=1

COPY . .
RUN npm run build:editor \
    && npm run build

FROM node:24.15.0-bookworm-slim AS runner

WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3000

RUN groupadd --system nodejs \
    && useradd --system --gid nodejs nextjs

COPY --from=builder --chown=nextjs:nodejs /app/.next ./.next
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/node_modules ./node_modules
COPY --from=builder --chown=nextjs:nodejs /app/package.json ./package.json
# next start loads runtime configuration, including the API proxy rewrites.
COPY --from=builder --chown=nextjs:nodejs /app/next.config.ts ./next.config.ts

USER nextjs
EXPOSE 3000

CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
