# CLAUDE.md

LiveKit Agents (Python) voice-cloning demo. Single agent at `src/agent.py`, voice-clone helpers at `src/voice_clone.py`. React frontend in sibling dir at `../web/` (Next.js 15 + Tailwind v4 + shadcn + `@livekit/components-react`, bootstrapped from the `agent-starter-react` template).

See `@AGENTS.md` for the upstream LiveKit Agents conventions (uv, src/ layout, lk docs CLI).

## Stack

- **STT**: Cartesia `ink-whisper` (`livekit-plugins-cartesia`)
- **LLM**: Groq `openai/gpt-oss-120b` (`livekit-plugins-groq`)
- **TTS**: Fish Audio `s2-pro` (`livekit-plugins-fishaudio`)
- **VAD / turn**: silero VAD + LiveKit multilingual turn detector
- Runs against self-hosted `livekit-server --dev` (defaults: `ws://localhost:7880`, key `devkey`, secret `secret`) — also works against LiveKit Cloud.

## `.env.local` (gitignored)

```
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret
CARTESIA_API_KEY=...
GROQ_API_KEY=...
FISH_API_KEY=...
```

Fish reads `FISH_API_KEY`, not `FISH_AUDIO_API_KEY`.

## Common commands

All from `/Users/cale/code/fish/livekit-demo/fish/` (the dir with `pyproject.toml`).

```bash
# First time / after pulling deps
uv sync
uv run python src/agent.py download-files  # silero VAD + turn detector weights

# Smoke test: console mode (no LiveKit server, uses your terminal mic)
uv run python src/agent.py console

# Pick a specific mic (Cale uses the Rode)
uv run python src/agent.py console --input-device "RODE"
uv run python src/agent.py console --list-devices

# Worker against the local livekit-server --dev (separate terminal)
uv run python src/agent.py dev

# Lint / format (must stay green)
uv run ruff check src/
uv run ruff format src/
```

`uv run python -c "import src.agent"` is the fastest "did I break the imports" check.

## Full local stack (three terminals)

```bash
# Terminal 1: LiveKit dev server (devkey/secret on ws://localhost:7880)
livekit-server --dev

# Terminal 2: Python agent worker — registers and waits for room dispatch
cd fish
uv run python src/agent.py dev

# Terminal 3: Next.js frontend at http://localhost:3000
cd ../web
pnpm install   # first run only
pnpm dev
```

Open http://localhost:3000, hit "Start call". The worker auto-dispatches into the new room (no `agent_name` set on the rtc_session). `web/.env.local` is preconfigured to point at the local dev server.

## Frontend: `clone.state` state machine

The Python agent calls `self._set_clone_state(session, "<state>")` at each transition, which writes `clone.state` onto its participant attributes via `session.room.local_participant.set_attributes({"clone.state": state})`. Values:
- `recording` — set on entry to `clone_my_voice`, cleared if recording fails (back to `idle`).
- `cloning` — set right after `clear_user_turn()` once the upload pipeline starts.
- `ready` — set when Fish returns the model_id.
- `playing` — set in `play_cloned_voice` after the TTS swap.

React reads it via `useParticipantAttribute('clone.state', { participant: agent })` (the agent participant comes from `useVoiceAssistant().agent`). `web/components/app/clone-status-banner.tsx` is the indicator — a fixed top-center pill that swaps between pulse-dot (recording), spinner (cloning), and static success badges (ready / playing). Mounted in `web/components/app/app.tsx` inside `<AgentSessionProvider>` so the hooks bind to the same session.

Don't reuse the built-in `lk.agent.state` attribute (`listening`/`thinking`/`speaking`) for cloning UI — it flickers during `session.say` and tool execution and isn't a clean source of truth.

## Voice-cloning flow

`clone_my_voice` is **synchronous end-to-end** — it doesn't return until the clone is uploaded and ready. Background tasks were tried earlier; they raced with the LLM's tool-response queue and the announcement got silently dropped.

1. Session starts, agent greets via `session.generate_reply(instructions=...)` and pitches cloning.
2. On confirmation, LLM calls `Assistant.clone_my_voice` with **zero preamble** (system prompt forbids speaking — the tool plays its own cues).
3. **No in-tool start cue.** The system prompt tells the LLM to say one short "go!" sentence *and* call `clone_my_voice` in the same turn — LiveKit speaks the text first, then runs the tool. So the start cue rides the normal LLM response; tool starts recording immediately on entry.
4. Tool records 15s via `_CaptureAndMuteAudioInput` — pulls real frames from `session.input.audio` and yields silent frames so STT/turn detection don't transcribe the monologue.
5. `session.clear_user_turn()` drops any in-flight transcript that leaked through.
6. Tool fires a short verbatim `session.say("Got it! Give me just a sec to clone your voice.", add_to_chat_ctx=False, allow_interruptions=False)` — and *concurrently* runs silero VAD-trim → fresh `cartesia.STT` one-shot transcription → POST `/v1/model` to Fish (multipart, `train_mode=fast`, `visibility=private`, with `texts=<transcript>`). Verbatim instead of `generate_reply` because `generate_reply` from inside a tool auto-sets `tool_choice="none"`, and Groq's `gpt-oss-120b` strictly errors when the model emits a tool call anyway. Fallback to `session.say` is reliable and the user only hears a single short line during the upload.
7. Tool awaits the ack's `SpeechHandle.wait_for_playout()` and returns with a directive telling the LLM to ask "wanna hear it?" in one sentence. That return is LLM-generated, so it varies each run.
8. User says yes → LLM calls `Assistant.play_cloned_voice` → `fishaudio.TTS.update_options(voice_id=...)`. Next utterance is in the cloned voice.
9. On session end, `ctx.add_shutdown_callback` `DELETE`s the Fish model.

## Things that will bite you

- **Console mode mocks `ctx.room`.** Anything that touches `rtc.AudioStream.from_participant` or `participant._ffi_handle` will crash with `AttributeError: Mock object has no attribute '_ffi_handle'`. For audio capture, go through `session.input.audio` — uniform across console + rtc.
- **Cartesia STT only supports `stream()`**, not `recognize()`. If you call `recognize()` it raises an unrecoverable `stt_error` event and the session shuts down. The reference-transcript path uses a one-shot `transcribe_frames(stt, frames)` over `stream()`.
- **Always use a fresh `cartesia.STT(...)` for the reference transcription**, not `session.stt`. An error on the session's STT instance is treated as fatal.
- **Silero `END_OF_SPEECH` requires trailing silence** (~`min_silence_duration`). `vad_trim_frames` pads with ~1s of silence so the event fires even when the user talks right up to the 15s cutoff.
- **`fishaudio.TTS.update_options(voice_id=...)` applies to the *next* synthesis**, not mid-utterance. `ChunkedStream`/`SynthesizeStream` copy `_opts` on construction.
- **`livekit.rtc.LocalParticipant.set_attributes` clobbers all attributes you don't pass.** The implementation (rtc/participant.py:552-571) builds the outgoing set from a fresh empty `FfiRequest` instead of reading the current attributes, so calling it with a single key wipes everything else — including `lk.agent.state`, which the React `useAgent` hook reads to determine connection state. With it missing, `agent.state` flips to `"failed"` and the template's `useAgentErrors` ends the session. Always read `participant.attributes`, merge your keys, then send. `Assistant._set_clone_state` does this.

## Editing conventions

- One `Agent` subclass (`Assistant`), tools as `@function_tool`-decorated methods. No agent handoffs / `AgentTask` unless the flow grows.
- Cloning is synchronous inside the tool — no background tasks (they raced with the LLM tool-response queue).
- For any "the agent should speak something not from the LLM" use `session.say(text, add_to_chat_ctx=...)`. Set `add_to_chat_ctx=False` for system-only cues so the LLM's chat context stays clean.
- Don't call `session.generate_reply(...)` from inside a `@function_tool` — it auto-sets `tool_choice="none"`, and Groq's `gpt-oss-120b` strictly errors if the model emits a tool call anyway. Use `session.say` instead.

## Project layout

```
src/
├── agent.py         # Assistant, tools, server entrypoint
└── voice_clone.py   # capture-mute tee, VAD trim, STT transcribe, Fish HTTP
tests/               # placeholder; no tests yet
```
