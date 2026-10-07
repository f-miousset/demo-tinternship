# The demo, built once and served as static files. There is no backend: every
# visitor's data lives in their own browser (documentation/architecture.md), so
# the image holds nothing but the build and one nginx config. The real app's
# backend in app/ is NOT in this image — it is here to be read and self-hosted
# (selfhost/), never to run on the demo's server.
#
# Pinned exactly: a floating tag is invisible to Renovate. Node matches the
# real app's own web image (app/deploy/Dockerfile.web).
FROM node:24-alpine AS build
WORKDIR /src

COPY package.json package-lock.json .npmrc ./
RUN npm ci

# Only what the build reads. app/frontend is the real app's UI, unmodified;
# demo/ is the mock and the static files the seed builder wrote.
COPY index.html vite.config.ts tsconfig.json ./
COPY demo/ demo/
COPY app/frontend/src/ app/frontend/src/
COPY app/frontend/public/ app/frontend/public/
RUN npx vite build

FROM nginx:1.31-alpine
COPY --from=build /src/dist /usr/share/nginx/html
COPY --from=build /src/dist-nginx/export-names.conf /etc/nginx/conf.d/00-export-names.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80

# 127.0.0.1, not localhost: busybox wget resolves localhost to ::1 first, and an
# address-family mismatch reads exactly like a dead server. Declared HERE, not in
# compose, so every `docker run` of this image executes it — including the smoke.
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -qO /dev/null http://127.0.0.1/index.html || exit 1
