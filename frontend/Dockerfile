# Web Studio (Next.js) cho bản chạy bằng Docker: build production một lần, chạy `next start`.
#
#   docker compose -f docker-compose.studio.yml up --build      (từ root repo)
#
# Trình duyệt chỉ gọi origin của web; Next chuyển tiếp `/api/v1/*` sang API (REAL2SIM_API_URL). Rewrites được chốt lúc
# build nên địa chỉ API phải có cả ở build (ARG) lẫn lúc chạy (ENV, cho route upload và fetch phía server).
# Node 24 (npm 11): cùng bản với CI và với lockfile; npm 10 từ chối `npm ci` trên lockfile này.
FROM node:24-bookworm-slim AS build
WORKDIR /app
ARG REAL2SIM_API_URL=http://api:8000
ENV REAL2SIM_API_URL=$REAL2SIM_API_URL NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# Trình chỉnh Gaussian nhúng (SuperSplat, mã nguồn vendored) → public/editor, rồi build app.
RUN npm run build:editor && npm run build

FROM node:24-bookworm-slim
WORKDIR /app
ARG REAL2SIM_API_URL=http://api:8000
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 REAL2SIM_API_URL=$REAL2SIM_API_URL PORT=3000
COPY --from=build /app/package.json /app/package-lock.json /app/next.config.ts ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/.next ./.next
COPY --from=build /app/public ./public
USER node
EXPOSE 3000
CMD ["npx", "next", "start", "--hostname", "0.0.0.0", "--port", "3000"]
