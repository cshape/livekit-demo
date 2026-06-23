# Expressive voice agent demo

A small voice agent that shows off [Fish Audio](https://fish.audio)'s
**expressive** text-to-speech. Pick one of four preset voices (or clone your own
by reading a short script), then ask the agent to switch register
(professional ↔ casual) or take on a mood, and hear the emotional range. Powered
by [Fish Audio](https://fish.audio), [AssemblyAI](https://www.assemblyai.com),
[OpenAI](https://openai.com), and
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
- API keys for [Fish Audio](https://fish.audio), [AssemblyAI](https://www.assemblyai.com), and [OpenAI](https://platform.openai.com)
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
that provisions both services from a single click — no Docker needed.

1. Push the repo to GitHub.
2. In the Render dashboard: **New → Blueprint**, pick this repo. Render reads
   `render.yaml` and creates both services — `livekit-demo-web` (Next.js
   frontend) and `livekit-demo-agent` (Python worker).
3. Fill in the `livekit-demo-shared` env-var group with your real LiveKit /
   Fish / AssemblyAI / OpenAI keys.
4. Hit deploy. Both services come up against the same LiveKit Cloud project.

## How it works

- **Pick a voice up front.** The landing page offers four preset Fish Audio
  voices (with audio previews) or "clone your voice." That choice rides agent
  metadata to the worker via named dispatch, so the agent starts in the chosen
  voice.
- **Expressive by default.** The agent opens in a professional register; ask it
  to get casual or take on a mood and it calls a `set_style` tool that rewrites
  its own prompt at runtime and updates an on-screen mood-ring indicator.
  Delivery is shaped with Fish Audio's bracket markers (`[excited]`, `[calm]`,
  `[chuckles]`, …), which are stripped from the transcript.
- **Clone-first (optional).** If you choose "clone your voice," the agent shows a
  short script and captures ~12 seconds as you read it (highlighting words live
  from streaming STT), clones your voice via Fish Audio's `/model` endpoint
  (`train_mode=fast`), switches the TTS into it, and greets you in your own voice.
  The clone and the recording are deleted from Fish when the call ends.

See `fish/CLAUDE.md` for the full agent-side flow and `fish/src/agent.py` for
the code.

## License

[MIT](LICENSE).
