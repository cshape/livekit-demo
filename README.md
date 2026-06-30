# Expressive voice agent demo

A small voice agent that shows off [Fish Audio](https://fish.audio)'s
**expressive** text-to-speech. Pick one of four preset voices (or clone your own
by reading a short script), then flip it between casual and professional mid-call
with an on-screen toggle and watch its mood shift in real time. Powered
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

## Deploy

The two halves deploy to two places: the **frontend** to Render, the **agent
worker** to LiveKit Cloud Agents (co-located with the media server). Both target
the same LiveKit Cloud project.

### Frontend → Render

`render.yaml` is a [Render Blueprint](https://render.com/docs/infrastructure-as-code)
for the web service only (the landing page + the `/api/token` route).

1. Push the repo to GitHub.
2. In the Render dashboard: **New → Blueprint**, pick this repo. Render reads
   `render.yaml` and creates `livekit-demo-web`.
3. Fill in the `livekit-demo-shared` env-var group with your LiveKit Cloud
   project's `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` — the same
   project the agent is deployed to, or named dispatch finds no worker and calls
   hang. No provider keys here; those are the agent's secrets (below).

### Agent worker → LiveKit Cloud Agents

The worker deploys with the [`lk` CLI](https://docs.livekit.io/agents/ops/deployment/)
from `fish/` (its `Dockerfile` is the build; `fish/livekit.toml` pins the agent
id + project). Provider keys are stored as agent secrets, not env vars — and
`LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` are injected
automatically by LiveKit, so you never set them.

```bash
cd fish
lk cloud auth                 # or: lk project add … (link the project once)
# first deploy (creates the agent + livekit.toml):
lk agent create --region us-east --secrets-file <your-secrets.env> .
# subsequent deploys (after code changes):
lk agent deploy
lk agent status               # rollout / replicas
lk agent logs                 # runtime logs
```

The agent's dispatch name comes from `@server.rtc_session(agent_name="fish-demo")`
in `src/agent.py` and must match `agentName` in `web/app-config.ts`.

## How it works

- **Pick a voice up front.** The landing page offers four preset Fish Audio
  voices (with audio previews) or "clone your voice." That choice rides agent
  metadata to the worker via named dispatch, so the agent starts in the chosen
  voice.
- **Expressive by default.** The agent opens in a casual register. You flip it
  between casual and professional with an on-screen toggle, which sends a
  `set_mode` RPC that swaps the agent's expressive preset at runtime and has it
  react in the new voice. A separate, lightweight LLM reads each line the agent
  speaks and drives the on-screen mood ring (cosmetic — it never changes how the
  agent talks). Delivery is shaped with the SDK's expressive markup, converted to
  Fish Audio's native form for audio and stripped from the transcript.
- **Clone-first (optional).** If you choose "clone your voice," the agent shows a
  short script and captures ~12 seconds as you read it (highlighting words live
  from streaming STT), clones your voice via Fish Audio's `/model` endpoint
  (`train_mode=fast`), switches the TTS into it, and greets you in your own voice.
  The clone and the recording are deleted from Fish when the call ends.

See `fish/CLAUDE.md` for the full agent-side flow and `fish/src/agent.py` for
the code.

## License

[MIT](LICENSE).
