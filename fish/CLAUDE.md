# CLAUDE.md

LiveKit Agents (Python) voice-cloning demo. Single agent at `src/agent.py`, voice-clone helpers at `src/voice_clone.py`. React frontend in sibling dir at `../web/` (Next.js 15 + Tailwind v4 + shadcn + `@livekit/components-react`, bootstrapped from the `agent-starter-react` template).

This is a LiveKit Agents (Python) project: use `uv` for everything, app code lives under `src/` with `agent.py` as the entrypoint, and `uv run ruff check src/` / `uv run ruff format src/` must stay green. For up-to-date LiveKit docs, use the `lk docs` CLI or the LiveKit docs MCP server.

## Stack

- **STT**: AssemblyAI `universal-streaming-english` (`livekit-plugins-assemblyai`)
- **LLM**: OpenAI `gpt-5.4-nano` (`livekit-plugins-openai`); model overridable via `OPENAI_MODEL`.
- **TTS**: Fish Audio `s2.1-pro` (`livekit-plugins-fishaudio`)
- **VAD / turn**: silero VAD only (no separate turn-detector model — keeps the worker footprint inside Render's 512MB Starter tier)
- Runs against self-hosted `livekit-server --dev` (defaults: `ws://localhost:7880`, key `devkey`, secret `secret`) — also works against LiveKit Cloud.

## `.env.local` (gitignored)

```
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret
ASSEMBLYAI_API_KEY=...
OPENAI_API_KEY=...
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

The Python agent calls `self._set_clone_state("<state>")` at each transition, which writes `clone.state` onto its participant attributes (read-modify-write — see the `set_attributes` gotcha below). Values:
- `cloning` — set on entry to `clone_my_voice`, once the upload pipeline starts.
- `ready` — set when Fish returns the model_id.
- `playing` — set at the end of `clone_my_voice`, right after it swaps the TTS to the clone.

No `recording` state — the demo no longer prompts the user for a monologue, so there's no countdown phase to show. React reads the attribute via `useParticipantAttribute('clone.state', { participant: agent })`. The status pill that used to surface these states was removed; `clone.state` now drives only `web/components/app/capture-progress.tsx` (hides the capture bar once state leaves `idle`) and the `/debug` overlay's clone-state log. The agent still sets it, so re-add UI off it if needed.

Don't reuse the built-in `lk.agent.state` attribute (`listening`/`thinking`/`speaking`) for cloning UI — it flickers during `session.say` and tool execution and isn't a clean source of truth.

## Voice-cloning flow

The agent silently buffers user audio in the background during normal conversation and only pivots to the clone pitch once it has enough speech to work with. `clone_my_voice` is **synchronous end-to-end** — it doesn't return until the clone is uploaded and ready. Background tasks were tried earlier; they raced with the LLM's tool-response queue and the announcement got silently dropped.

1. Session starts, agent greets warmly with no mention of cloning. `Assistant.install_capture(session)` (called from `my_agent` after `session.start`) tees `session.input.audio` through a `PassthroughCaptureAudioInput` that forwards every frame unchanged *and* appends it to an in-memory buffer when `tee.recording` is True. The tee is hard-capped at `CAPTURE_MAX_SECS` (60s) of buffered audio — long recordings get truncated rather than ballooning memory.
2. `install_capture` also subscribes to `session.on("user_state_changed", ...)` and flips `tee.recording` based on whether the user is currently speaking. It tracks cumulative speech wall-clock between `speaking` → `listening`/`away` transitions; once it crosses `CLONE_PITCH_THRESHOLD_SECS` (10s — Fish Audio's voice cloning works on ~10s of reference audio), `_capture_ready` flips to True.
3. `Assistant.on_user_turn_completed(turn_ctx, new_message)` checks `_capture_ready and not _pitch_done` on every completed user turn. The first time it's True, it appends a hidden system message to `turn_ctx` telling the LLM to organically pivot to the clone pitch in its next response, and sets `_pitch_done = True`. The pitch rides the normal next-response cycle so it can't interrupt the user mid-turn.
4. On confirmation, LLM calls `Assistant.clone_my_voice` with **zero preamble** — the tool plays its own cues. The tool snapshots `self._capture.frames`, sets `clone.state = "cloning"`, and fires a verbatim `session.say(random.choice(CLONE_ACK_LINES), add_to_chat_ctx=True, allow_interruptions=False)` (one of 5 two-sentence acks that promise the next line will be in the cloned voice; added to chat ctx so the reveal flows from it, uninterruptible so it plays in full) — and *concurrently* runs silero VAD-trim → fresh `assemblyai.STT` one-shot transcription → POST `/v1/model` to Fish (multipart, `train_mode=fast`, `visibility=private`, with `texts=<transcript>`). Verbatim `session.say` instead of `generate_reply` because `generate_reply` from inside a tool auto-sets `tool_choice="none"`; `session.say` sidesteps that.
5. Tool awaits the ack's `SpeechHandle.wait_for_playout()`, then **itself** swaps the TTS to the clone (`fishaudio.TTS.update_options(voice_id=...)`), sets `clone.state = "playing"`, and returns a directive telling the LLM to announce the clone is ready and ask what they think. There is no "wanna hear it?" confirmation step — the reveal is automatic, so the next LLM reply is already in the cloned voice. (`update_options` applies to the *next* synthesis, so the ack queued before the swap still plays in the original voice.)
6. On session end, `ctx.add_shutdown_callback` `DELETE`s the Fish model.

## Things that will bite you

- **Console mode mocks `ctx.room`.** Anything that touches `rtc.AudioStream.from_participant` or `participant._ffi_handle` will crash with `AttributeError: Mock object has no attribute '_ffi_handle'`. For audio capture, go through `session.input.audio` — uniform across console + rtc.
- **The STT plugin is streaming-only** (`assemblyai.STT` is a realtime websocket model; no batch `recognize()`). The reference-transcript path therefore feeds the buffered frames through a one-shot `transcribe_frames(stt, frames)` over `stream()`, collecting `FINAL_TRANSCRIPT` events. `transcribe_frames` is provider-agnostic, so swapping STT vendors only touches the two `assemblyai.STT()` call sites in `agent.py`.
- **Always use a fresh `assemblyai.STT()` for the reference transcription**, not `session.stt`. An error on the session's STT instance is treated as fatal, so the throwaway instance isolates the clone path.
- **Silero `END_OF_SPEECH` requires trailing silence** (~`min_silence_duration`). `vad_trim_frames` pads with ~1s of silence so the event fires even when the user is still mid-word at the buffered-frames cutoff.
- **`fishaudio.TTS.update_options(voice_id=...)` applies to the *next* synthesis**, not mid-utterance. `ChunkedStream`/`SynthesizeStream` copy `_opts` on construction.
- **`preemptive_generation=True` races with `on_user_turn_completed`.** It starts generating the reply while the user is still speaking, before `on_user_turn_completed` runs — so the capture-status note and the one-shot "pivot to cloning now" system message injected there don't land in that turn's response (LiveKit logs `preemptive generation enabled but chat context or tools have changed after on_user_turn_completed`). The agent misses the moment the buffer crosses threshold and the clone pitch stalls until the user prods it. Keep it **off** as long as the pivot relies on `on_user_turn_completed` injection.
- **`livekit.rtc.LocalParticipant.set_attributes` clobbers all attributes you don't pass.** The implementation (rtc/participant.py:552-571) builds the outgoing set from a fresh empty `FfiRequest` instead of reading the current attributes, so calling it with a single key wipes everything else — including `lk.agent.state`, which the React `useAgent` hook reads to determine connection state. With it missing, `agent.state` flips to `"failed"` and the template's `useAgentErrors` ends the session. Always read `participant.attributes`, merge your keys, then send. `Assistant._set_clone_state` does this.

## Editing conventions

- One `Agent` subclass (`Assistant`), tools as `@function_tool`-decorated methods. No agent handoffs / `AgentTask` unless the flow grows.
- Cloning is synchronous inside the tool — no background tasks (they raced with the LLM tool-response queue).
- For any "the agent should speak something not from the LLM" use `session.say(text, add_to_chat_ctx=...)`. Set `add_to_chat_ctx=False` for system-only cues so the LLM's chat context stays clean.
- Don't call `session.generate_reply(...)` from inside a `@function_tool` — it auto-sets `tool_choice="none"`, suppressing further tool calls. Use `session.say` instead.
- To shape the LLM's next response from outside a tool (e.g. pivoting the conversation), override `Agent.on_user_turn_completed(turn_ctx, new_message)` and `turn_ctx.add_message(role="system", content=...)`. It rides the natural next-response cycle and won't interrupt the user mid-turn.

## Project layout

```
src/
├── agent.py         # Assistant, tools, server entrypoint
└── voice_clone.py   # capture-mute tee, VAD trim, STT transcribe, Fish HTTP
tests/               # test_agent.py — 3 LLM-judge eval tests (friendliness, grounding, refusal)
```
