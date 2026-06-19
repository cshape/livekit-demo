# Voice cloning demo — agent worker

The backend half of the [voice cloning demo](../README.md): a Python
[LiveKit Agents](https://docs.livekit.io/agents/) worker that chats with the
user and, on request, clones their voice from ~10 seconds of the conversation
using [Fish Audio](https://fish.audio).

This directory is self-contained — you can run it on its own and point any
[compatible frontend](https://docs.livekit.io/frontends/) (or the
[`web/`](../web/) app, or telephony) at the same LiveKit project.

## Stack

- **STT** — Cartesia `ink-whisper` (`livekit-plugins-cartesia`)
- **LLM** — OpenAI `gpt-5.4-nano` (`livekit-plugins-openai`); override the model with `OPENAI_MODEL`
- **TTS** — Fish Audio `s2.1-pro` (`livekit-plugins-fishaudio`)
- **VAD / turn detection** — Silero VAD only (no separate turn-detector model, to keep the worker footprint small)

The voice-cloning flow (silent audio capture → VAD trim → reference
transcription → Fish `/model` upload → TTS swap → delete on session end) is
documented in [`CLAUDE.md`](./CLAUDE.md); the code is in
[`src/agent.py`](./src/agent.py) and [`src/voice_clone.py`](./src/voice_clone.py).

## Run it standalone

```bash
cp .env.example .env.local                  # then fill in your keys
uv sync
uv run python src/agent.py download-files   # Silero VAD weights

# Talk to it in your terminal (no LiveKit server needed):
uv run python src/agent.py console

# Or register as a worker against your LiveKit project (for use with a frontend):
uv run python src/agent.py dev
```

In production use `start` instead of `dev` (this is what the Dockerfile and the
Render deploy run).

### Docker

```bash
docker build -t voice-clone-agent .
docker run --rm --env-file .env.local voice-clone-agent
```

The worker has no inbound port — it connects out to LiveKit and waits for room
dispatch.

## Environment variables

```env
LIVEKIT_URL=wss://<your-project>.livekit.cloud
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=

CARTESIA_API_KEY=
OPENAI_API_KEY=
FISH_API_KEY=
```

Fish reads `FISH_API_KEY` (not `FISH_AUDIO_API_KEY`).

## Lint

```bash
uv run ruff check src/
uv run ruff format --check src/
```
