# Voice cloning demo

A small voice agent that lets you clone your own voice in ~10 seconds of
conversation, powered by [Fish Audio](https://fish.audio),
[Cartesia](https://cartesia.ai), [Groq](https://groq.com), and
[LiveKit Agents](https://docs.livekit.io/agents/).

```
fish/   Python agent worker (livekit-agents, uv)  → fish/README.md
web/    Next.js 15 frontend (pnpm, Tailwind)       → web/README.md
```

The two halves never talk to each other directly — they meet in a LiveKit room.
Each directory is self-contained (its own deps, `.env.example`, README, and
Dockerfile), so you can run the whole thing together or grab just one half.

## Prereqs

- A [LiveKit Cloud](https://cloud.livekit.io) project (free tier is plenty)
- API keys for [Fish Audio](https://fish.audio), [Cartesia](https://cartesia.ai), and [Groq](https://console.groq.com)
- Then either [Docker](https://docs.docker.com/get-started/get-docker/) (Compose path) **or**
  [`uv`](https://docs.astral.sh/uv/getting-started/installation/) + [`pnpm`](https://pnpm.io/installation) (Node 20+) for the local path

## Run the whole thing

### Option A — Docker Compose

Brings up both services with one command; you only need Docker.

```bash
cp .env.example .env   # then fill in your LiveKit + provider keys
docker compose up --build
```

Open <http://localhost:3000> and hit **Start call**. Both containers and your
browser connect to the same LiveKit Cloud project from `.env`.

### Option B — local processes (uv + pnpm)

```bash
make env       # bootstrap empty fish/.env.local and web/.env.local
# fill in fish/.env.local and web/.env.local with your keys
make install   # uv sync + download VAD weights + pnpm install
make dev       # runs the agent worker and Next.js side-by-side
```

`make dev` uses `uvx honcho start` to run both processes with interleaved logs
under a single `Ctrl-C` (see `Procfile`).

## Run just one half

The frontend and backend are independent — each has its own README with
standalone (and Docker) instructions:

- **Backend only** (point your own frontend/telephony at it): [`fish/README.md`](fish/README.md)
- **Frontend only** (point at an already-running agent): [`web/README.md`](web/README.md)

With Compose you can also target one service: `docker compose up --build agent`
or `docker compose up --build web`.

## Deploy to Render

This repo ships a [Render Blueprint](https://render.com/docs/infrastructure-as-code) (`render.yaml`)
that provisions both services from a single click — no Docker needed — and is
the current production deploy.

1. Push the repo to GitHub.
2. In the Render dashboard: **New → Blueprint**, pick this repo. Render reads
   `render.yaml` and offers to create:
   - `livekit-demo-web` — Next.js (free tier).
   - `livekit-demo-agent` — Python worker (Starter, ~$7/mo; Render has no free worker tier).
3. Fill in the `livekit-demo-shared` env-var group with your real LiveKit /
   Fish / Cartesia / Groq keys.
4. Hit deploy. Both services come up against the same LiveKit Cloud project.

If the worker pricing is a blocker, [Fly.io](https://fly.io) and [Railway](https://railway.app)
both have cheaper long-running processes — the same `fish/` directory works
with either (uv-based, or via `fish/Dockerfile`).

## How it works

- Agent silently buffers user mic audio while you chat. Once ~10s of cumulative
  user speech has been captured (per VAD), the agent organically pivots to
  offering a voice clone.
- On confirmation, the buffered audio is VAD-trimmed, transcribed via Cartesia,
  and uploaded to Fish Audio's `/model` endpoint (`train_mode=fast`).
- The cloned voice gets swapped into the active TTS for the rest of the
  session and is deleted from Fish on session end.

See `fish/CLAUDE.md` for the full agent-side flow and `fish/src/agent.py` for
the code.
