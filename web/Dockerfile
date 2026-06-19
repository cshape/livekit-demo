# syntax=docker/dockerfile:1

# Next.js 15 frontend. Multi-stage build that produces a slim runtime image from
# Next's standalone output (see `output: 'standalone'` in next.config.ts).
FROM node:20-bookworm-slim AS base
ENV PNPM_HOME=/pnpm
ENV PATH="$PNPM_HOME:$PATH"
RUN corepack enable

# --- Dependencies ---
FROM base AS deps
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm install --frozen-lockfile

# --- Build ---
FROM base AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN pnpm build

# --- Runtime ---
FROM base AS runtime
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
# Next.js standalone server reads HOSTNAME; 0.0.0.0 so it's reachable in Docker.
ENV HOSTNAME=0.0.0.0

# Run as the non-root user shipped with the node image.
USER node

# Standalone output bundles the server + only the node_modules it traced.
COPY --chown=node:node --from=build /app/.next/standalone ./
COPY --chown=node:node --from=build /app/.next/static ./.next/static
COPY --chown=node:node --from=build /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
