FROM node:22.11.0-bookworm-slim@sha256:f035ba7ffee18f67200e2eb8018e0f13c954ec16338f264940f701997e3c12da AS builder

WORKDIR /app
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:alpine
ARG CRYPTO_VERSION=1.0.0
ARG CRYPTO_BUNDLE_SHA256=03636dd86c983cf4af2070f8d71fa1683fdbde81b7845fbb639aebc8adef557b
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
RUN apk add --no-cache curl ca-certificates || \
    (apt-get update && apt-get install -y curl ca-certificates && rm -rf /var/lib/apt/lists/*)
RUN mkdir -p /tmp/crypto && \
    curl -fsSL "https://github.com/SellerDock/profitos-crypto/releases/download/v1.0.0/profitos-crypto.iife.js" \
      -o /tmp/crypto/profitos-crypto.iife.js && \
    echo "${CRYPTO_BUNDLE_SHA256}  /tmp/crypto/profitos-crypto.iife.js" \
      | sha256sum -c - && \
    mkdir -p /usr/share/nginx/html/static/crypto && \
    cp /tmp/crypto/profitos-crypto.iife.js \
      /usr/share/nginx/html/static/crypto/profitos-crypto-v${CRYPTO_VERSION}.js
EXPOSE 80
