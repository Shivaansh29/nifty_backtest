# The dashboard image (M8): the production build of the React app, served by unprivileged
# nginx, which also forwards /api and the API documentation to the API container. The
# browser therefore talks to one origin, exactly as it does through Vite's proxy in
# development, and the API needs no CORS headers.
#
# Base images are pinned by version AND sha256 digest; change both together to upgrade.

# --- Build stage: Node 24.14.1 (frontend/.nvmrc), exact packages from package-lock.json -----
FROM node:24.14.1-alpine3.23@sha256:8510330d3eb72c804231a834b1a8ebb55cb3796c3e4431297a24d246b8add4d5 AS build
WORKDIR /frontend
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# Type-checks, then builds into dist/ (the same `npm run build` CI runs).
RUN npm run build

# --- Runtime stage: nginx 1.30 (the stable line), running as an unprivileged user ---------
# 1.30.6 is pinned although it was released less than two weeks before M8, because it fixes
# five CVEs (nginx.org CHANGES-1.30, 14 Oct 2026), one of them in the variable evaluation used
# for document roots and request logging.
FROM nginxinc/nginx-unprivileged:1.30.6-alpine-slim@sha256:5d8bb9437d74a600ec5dbf90c035451c724dc33eac8d3a71078f6f8612c345f6
COPY nginx.conf /etc/nginx/conf.d/default.conf
# A folder of its own, so none of the base image's sample pages (e.g. 50x.html) is served.
COPY --from=build /frontend/dist /usr/share/nginx/dashboard
# The base image already runs as the unprivileged `nginx` user and listens on 8080.
EXPOSE 8080
