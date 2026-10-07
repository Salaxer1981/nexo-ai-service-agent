# Nexo evaluation client (UI-02). Two stages:
#   build   — locked dependencies (npm ci) + typecheck + production bundle. Has no credential (none exists at build time).
#   runtime — the static bundle + server/server.mjs (Node standard library only). Runs as the unprivileged `node` user.
# Demo credentials are supplied ONLY at run time through the container environment (compose.yaml), never as build args.
FROM node:22.16.0-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY index.html tsconfig.json vite.config.js ./
COPY src ./src
RUN npm run build

FROM node:22.16.0-alpine
ENV NODE_ENV=production HOST=0.0.0.0 PORT=8080 WEB_ROOT=/srv/web/dist
WORKDIR /srv/web
COPY --from=build /app/dist ./dist
COPY server/server.mjs ./server/server.mjs
USER node
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:8080/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
CMD ["node", "server/server.mjs"]
