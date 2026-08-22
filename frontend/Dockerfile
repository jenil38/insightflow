# Frontend image: build the static bundle, then serve it with nginx.
#
# Vite inlines VITE_* variables at BUILD time, not at run time, so the API base
# URL has to be supplied as a build argument. Changing it means rebuilding this
# image - there is no way to swap it via an environment variable on the running
# container.
FROM node:20-alpine AS build

WORKDIR /app

# `npm ci` needs the lockfile and installs exactly what it pins.
COPY package*.json ./
RUN npm ci

COPY . .

ARG VITE_API_BASE=http://localhost:8000
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

# --- serve -------------------------------------------------------------------
FROM nginx:1.27-alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

RUN apk add --no-cache curl

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -fsS http://localhost/ || exit 1
