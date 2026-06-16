# Voice cloning demo

A small voice agent that lets you clone your own voice in ~10 seconds of
conversation, powered by [Fish Audio](https://fish.audio),
[Cartesia](https://cartesia.ai), [Groq](https://groq.com), and
[LiveKit Agents](https://docs.livekit.io/agents/).

```
fish/   Python agent worker (livekit-agents, uv)
web/    Next.js 15 frontend (pnpm, Tailwind)
```

The two halves never talk to each other directly — they meet in a LiveKit room.

## Prereqs

- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)
- [`pnpm`](https://pnpm.io/installation) (Node 20+)
- A [LiveKit Cloud](https://cloud.livekit.io) project (free tier is plenty)
- API keys for [Fish Audio](https://fish.audio), [Cartesia](https://cartesia.ai), and [Groq](https://console.groq.com)

## Run it locally

```bash
make env       # bootstrap empty .env.local files
# fill in fish/.env.local and web/.env.local with your keys
make install   # uv sync + download VAD/turn-detector weights + pnpm install
make dev       # runs the agent worker and Next.js side-by-side
```

Then open <http://localhost:3000> and hit **Start call**.

`make dev` uses `uvx honcho start` to run both processes with interleaved logs
under a single `Ctrl-C`. Skip the Makefile and run them yourself if you'd
rather — see `Procfile`.

## Deploy to Render

This repo ships a [Render Blueprint](https://render.com/docs/infrastructure-as-code) (`render.yaml`)
that provisions both services from a single click. No Docker.

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
with either (uv-based, no Docker required).

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
