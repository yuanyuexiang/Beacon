# Beacon Web：Next.js 生产构建。构建上下文为仓库根目录（pnpm workspace）。
FROM node:24-alpine AS build
RUN corepack enable && corepack prepare pnpm@11.2.2 --activate
WORKDIR /srv
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/
RUN pnpm install --frozen-lockfile
COPY apps/web/ apps/web/
# rewrite 目标在构建时固化：容器内后端地址
ARG BEACON_API_URL=http://api:8000
ENV BEACON_API_URL=$BEACON_API_URL
RUN pnpm --filter beacon-web build

FROM node:24-alpine AS run
RUN corepack enable && corepack prepare pnpm@11.2.2 --activate
WORKDIR /srv
COPY --from=build /srv/package.json /srv/pnpm-lock.yaml /srv/pnpm-workspace.yaml ./
COPY --from=build /srv/node_modules ./node_modules
COPY --from=build /srv/apps/web ./apps/web
ENV NODE_ENV=production
EXPOSE 3000
# BEACON_API_URL 在启动时由 next.config 读取，用于把 /api 代理到后端
CMD ["pnpm", "--filter", "beacon-web", "start"]
