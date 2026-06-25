# CLAUDE.md

LiveKit Agents (Python) **expressive-voice** demo (Fish Audio TTS). Single agent at `src/agent.py`, voice-clone helpers at `src/voice_clone.py`. React frontend in sibling dir at `../web/` (Next.js 15 + Tailwind v4 + shadcn + `@livekit/components-react`, bootstrapped from the `agent-starter-react` template).

**Landing page picks the voice up front.** The user either chooses one of 4 preset Fish voices or "clone your voice" (reads a short script, then the call begins in their clone). That choice rides **agent metadata** to the worker via NAMED dispatch. On top of any voice, the **user** flips the speaking register (casual/professional) with an on-screen toggle — a `set_mode` RPC swaps the agent's expressive preset and triggers a short demo line — and a **separate, cosmetic mood-classifier LLM** (in the agent process) reads each line the agent speaks and drives the on-screen mood ring. There is no `set_style` tool and no agent-controlled mood anymore.

This is a LiveKit Agents (Python) project: use `uv` for everything, app code lives under `src/` with `agent.py` as the entrypoint, and `uv run ruff check src/` / `uv run ruff format src/` must stay green. For up-to-date LiveKit docs, use the `lk docs` CLI or the LiveKit docs MCP server.

## Stack

- **STT**: AssemblyAI `universal-streaming-english` (`livekit-plugins-assemblyai`)
- **LLM**: OpenAI `gpt-5.1` (`livekit-plugins-openai`, direct via `OPENAI_API_KEY`); model overridable via `OPENAI_MODEL`. (The cosmetic mood-ring classifier runs separately on the cheaper `MOOD_MODEL`, default `gpt-4.1-mini`.) (We evaluated the LiveKit inference gateway and Google/Gemma: the gateway doesn't serve `gemma-4-31b-it`, and Gemma 4 via the google plugin breaks the `set_style` tool on Gemini's function-call turn-ordering rule when expressive instructions are injected — so the demo stays on OpenAI direct.)
- **TTS**: Fish Audio `s2.1-pro` (`livekit-plugins-fishaudio`)
- **VAD / turn**: silero VAD only (no separate turn-detector model — keeps the worker footprint inside Render's 512MB Starter tier)
- Runs against self-hosted `livekit-server --dev` (defaults: `ws://localhost:7880`, key `devkey`, secret `secret`) — also works against LiveKit Cloud.

## `.env.local` (gitignored)

```
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret
# LLM via inference gateway → LiveKit Cloud creds (local devkey won't auth):
LIVEKIT_INFERENCE_API_KEY=...
LIVEKIT_INFERENCE_API_SECRET=...
ASSEMBLYAI_API_KEY=...
OPENAI_API_KEY=...  # optional: only for scripts/probe_tag_fidelity.py
FISH_API_KEY=...
```

Fish reads `FISH_API_KEY`, not `FISH_AUDIO_API_KEY`.

## Common commands

All from `/Users/cale/code/livekit-demo/fish/` (the dir with `pyproject.toml`).

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

Open http://localhost:3000, hit "Start call". The frontend uses **named dispatch** — it requests the agent `fish-demo` (see "Voice selection" below), so the worker must be registered under that name (it is, via `@server.rtc_session(agent_name="fish-demo")`). `web/.env.local` is preconfigured to point at the local dev server.

## Expressiveness & style switching (the demo's hero)

The demo leads with **expressive TTS**, not cloning. The agent opens (in **casual** mode) by introducing itself as a Fish Audio-powered expressive voice and noting the user can flip it to professional with the on-screen toggle; cloning is a secondary, opt-in offer.

- **Expressive delivery comes from the SDK presets, not the prompt.** `_PRESET_FOR_MODE` maps the user-facing register to an SDK expressive preset (`casual` → `presets.CASUAL`, `professional` → `presets.CUSTOMER_SERVICE`). `_expressive_for(mode)` spreads the preset into a fresh dict; the Agents framework injects that register's markup-authoring guidance per turn and converts/strips the XML tags. `CORE_INSTRUCTIONS` carries only persona + product framing + the "fish dot audio" rule — never bracket/tag tutorials.
- **Register switch is USER-driven (no tool).** The frontend toggle (`web/components/app/mode-toggle.tsx`) calls the agent's **`set_mode` RPC** (registered on the agent's local participant in `my_agent`). The handler calls `Assistant.apply_mode(session, mode)`, which: sets `self._mode`, calls `self.update_expressive(_expressive_for(mode))` (re-resolved next reply), echoes `style.mode` back, and — unless mid clone-read — fires a one-line demo reply in the new register via `_safe_generate_reply`. `Assistant` tracks `self._mode` (default `"casual"`) and `self._cloned`.
- **Mood is a separate, cosmetic LLM — it never touches the agent's prompt or delivery.** On every `conversation_item_added` for an assistant message, `Assistant._on_conversation_item_added` (re)launches `_classify_mood`: a cheap, independent `AsyncOpenAI` call (`MOOD_MODEL`, default `gpt-4.1-mini`) that reads the spoken line, returns `{mood, color}` JSON, and writes `style.mood`/`style.color`. Only the latest line matters (a still-running classification is cancelled). Best-effort: failures are logged and swallowed.

## Frontend: `style.*` mood-ring indicator

Three `style.*` participant attributes drive the bottom-cluster UI (in `agent-session-block.tsx`, above the slim mic + END CALL control bar):
- `style.mode` — `casual` | `professional`. Written by `apply_mode` (the RPC handler) to echo the applied register; read by `web/components/app/mode-toggle.tsx`, which reconciles its optimistic state against it.
- `style.mood` — the one-word feeling from the mood-classifier LLM (`""` until the first classification). Read by `web/components/app/mood-indicator.tsx`.
- `style.color` — one of `gray`/`amber`/`green`/`blue`/`violet`, picked by the same classifier (gray = tense, amber = unsettled, green = calm, blue = happy/at-ease, violet = passionate/excited). The mood-indicator maps it to a glowing, state-aware dot (it pulses while the agent is thinking/speaking and shows the live state next to the mood). Seeded to the mode's resting color (`DEFAULT_MODE_COLOR`) on session start.

The text-chat input was removed (voice-only): `agent-control-bar.tsx` no longer has the chat input/toggle, and the transcript panel is always shown.

## Voice selection: landing page → agent (NAMED dispatch + agent metadata)

The chosen voice (or clone flag) is picked on the landing page and travels to the worker as **agent dispatch metadata**:
- Frontend `web/components/app/app.tsx` holds the selection (`useState`, default = first preset). It passes `{ agentName: 'fish-demo', agentMetadata: JSON.stringify(...) }` to `useSession` — `agentMetadata` is `{"voice":"<id>"}` for a preset or `{"clone":true}` for clone-first.
- LiveKit's `TokenSourceEndpoint` maps `agentMetadata` → `room_config.agents[0].metadata` in the POST body to `/api/token`; the route forwards `room_config` into the token unchanged. (No token-route change was needed.)
- The worker reads it as **`ctx.job.metadata`** (a JSON string) at the top of `my_agent`, validates the voice against `PRESET_VOICES` (falls back to `DEFAULT_VOICE_ID` = Stellan), and either greets normally (preset) or runs the clone-first flow.

**This requires NAMED dispatch.** `@server.rtc_session(agent_name="fish-demo")` (constant `AGENT_NAME`) must match `APP_CONFIG_DEFAULTS.agentName` in `web/app-config.ts` (hardcoded `'fish-demo'`). A mismatch = NO agent dispatches, silently (the frontend just times out via `useAgentErrors`). The 4 preset `voice_id`s live in `PRESET_VOICES` in **both** `src/agent.py` and `web/app-config.ts` — keep them in sync. Preview clips at `web/public/voice-samples/<id>.mp3` are generated by `scripts/gen_voice_samples.py`.

## Frontend: `clone.state` state machine

Only **clone-first** sessions (`{"clone":true}`) touch this; preset sessions never set it. The agent calls `self._set_clone_state("<state>")` at each transition (read-modify-write — see the `set_attributes` gotcha below). Values: `idle → prompt → cloning → ready → playing`:
- `prompt` — set on entry to `run_clone_first`; the user is reading the on-screen script. Also publishes `clone.script` (the script text), `clone.heard` (live STT of the read, throttled ~3 Hz, from the `user_input_transcribed` event), and `clone.capture_secs`.
- `cloning` — upload started.
- `ready` — Fish returned the model_id.
- `playing` — TTS swapped to the clone; reveal greeting about to play.

React reads it via `useParticipantAttribute('clone.state', ...)`. It drives `web/components/app/clone-script-card.tsx` — the centered card that, while `state === 'prompt'`, shows the "read this aloud" script and **highlights words as they're read**: it fuzzy-matches `clone.heard` against the script (greedy align with a forward window to skip STT drops + a small backward window to recover, plus bounded edit distance) and uses an elapsed-time floor so the highlight keeps progressing if STT lags. No seconds counter is shown. Once `state === 'cloning'` the same card swaps the script for the loading dot (`AgentChatIndicator`, the indicator used elsewhere for "thinking").

**The read is kept out of the chat.** `agent-chat-transcript.tsx` (`FilteredMessages`) hides any message seen while `clone.state` is `prompt`/`cloning` (the user reading + the agent's read prompt/ack), via a persistent id set — so the script read never lands in the transcript, but the post-clone reveal + conversation do. (There's no clean backend toggle: `session.output.set_transcription_enabled` gates only the agent's transcript, not the user-transcript forwarding path.)

Don't reuse the built-in `lk.agent.state` attribute (`listening`/`thinking`/`speaking`) for cloning UI — it flickers during `session.say` and tool execution and isn't a clean source of truth.

## Clone-first flow (upfront, controller-driven)

Cloning is **upfront-only** — there is no opportunistic mid-conversation clone anymore (no `clone_my_voice` tool). `Assistant.run_clone_first(session, ctx)` runs the whole thing as a straight-line coroutine, reusing the capture/upload machinery:

1. `install_capture(session)` tees `session.input.audio` through `PassthroughCaptureAudioInput` (forwards every frame, buffers when `tee.recording`, hard-capped at `CAPTURE_MAX_SECS=60`). `_reading_script = True`.
2. Publish `clone.script` + `clone.state="prompt"`, `await ctx.connect()` (so the mic is live), then `session.say(CLONE_PROMPT_LINE)` in the starting preset voice asking the user to read the on-screen script.
3. `user_state_changed` accumulates `_cumulative_speech_secs`; when it crosses `CLONE_SCRIPT_TARGET_SECS` (12s) it sets the `_capture_target_reached` asyncio.Event. The controller `await asyncio.wait_for(... , CLONE_SCRIPT_TIMEOUT_SECS=25)`.
4. **Reply suppression:** while `_reading_script`, `on_user_turn_completed` raises `StopResponse` (and `on_user_turn_exceeded` no-ops) so the agent stays silent and never talks over the read. (This is why `preemptive_generation` must stay OFF — it would start the reply before `on_user_turn_completed` runs.)
5. Under-read fallback: if `< CLONE_MIN_SECS` (6s) buffered (or no frames), reset to `idle`, clear `_reading_script`, and greet in the preset voice (`CLONE_FALLBACK_GREETING`).
6. Otherwise `clone.state="cloning"`, fire `_run_clone_upload(frames, vad)` as a task (silero VAD-trim → POST `/model` to Fish, `train_mode=fast`, **no reference transcript**), and `session.say` a one-line ack in the preset voice to fill the window. `await` the upload (fall back to `idle` + preset greeting on failure). We deliberately skip computing a reference transcript: AssemblyAI's streaming STT runs at ~1× realtime, so transcribing ~15s of read added ~15–20s and dominated the clone time (pushing the whole flow past the frontend agent-connect timeout). Fish clones fine from audio alone, and skipping it is more mis-read-robust (no text/audio mismatch). The clone trigger is purely time-of-speech (`CLONE_SCRIPT_TARGET_SECS=12`, min `6`), never script-match, so a mis-read still clones.
7. On model_id: store it, `clone.state="ready"`, await the ack's `wait_for_playout()`, `fishaudio.TTS.update_options(voice_id=model_id)`, `clone.state="playing"`. Set `_cloned=True`, `update_instructions(build_instructions(..., cloned=True))` (adds the slim "you're in their cloned voice; fish dot audio for permanent" note), clear `_reading_script`, and `generate_reply(CLONE_REVEAL_GREETING)` — the first line is already in the cloned voice.
8. On session end, `ctx.add_shutdown_callback` `DELETE`s the Fish model.

Preset sessions skip all of this: `my_agent` just seeds the mood-ring and `generate_reply(PRESET_GREETING)` then `ctx.connect()`.

## Things that will bite you

- **Console mode mocks `ctx.room`.** Anything that touches `rtc.AudioStream.from_participant` or `participant._ffi_handle` will crash with `AttributeError: Mock object has no attribute '_ffi_handle'`. For audio capture, go through `session.input.audio` — uniform across console + rtc.
- **The STT plugin is streaming-only** (`assemblyai.STT` is a realtime websocket model; no batch `recognize()`). The session STT drives turn detection AND the live clone-read highlighting (`user_input_transcribed` → `clone.heard`). The clone upload no longer computes a reference transcript (it dominated latency — see the clone-first flow), so `voice_clone.transcribe_frames` exists but is currently unused.
- **Silero `END_OF_SPEECH` requires trailing silence** (~`min_silence_duration`). `vad_trim_frames` pads with ~1s of silence so the event fires even when the user is still mid-word at the buffered-frames cutoff.
- **`fishaudio.TTS.update_options(voice_id=...)` applies to the *next* synthesis**, not mid-utterance. `ChunkedStream`/`SynthesizeStream` copy `_opts` on construction.
- **The clone-first read holds the agent in a long pre-greeting phase — the frontend's agent-connect timeout must cover it.** `useSession`'s default `agentConnectTimeoutMilliseconds` is **20s**; it's a one-shot check that flips the agent to `state==="failed"` (→ `useAgentErrors` ends the session) if `lk.agent.state` isn't `listening`/`thinking`/`speaking` at that instant. In a clone session the agent only `generate_reply`s *after* the read + clone build, and the high-frequency `clone.heard` attribute writes during the read lag/contend with the SDK's own `lk.agent.state` updates — so at 20s the frontend may not have registered "listening" yet. We pass `agentConnectTimeoutMilliseconds: 90_000` in `web/components/app/app.tsx` so the check lands well after the read+clone settles (the clone itself is now fast — no reference transcript). Any `generate_reply`/`say` in `run_clone_first` must also tolerate a closed session (the user can disconnect mid-read) — use `_safe_generate_reply`, which swallows the `RuntimeError("AgentSession isn't running")` instead of crashing the job.
- **`preemptive_generation=True` races with `on_user_turn_completed`.** It starts generating the reply while the user is still speaking, before `on_user_turn_completed` runs — so the `StopResponse` we raise there to keep the agent silent during the clone-script read would land too late to suppress the reply, and the agent talks over the reading. Keep it **off** as long as reply suppression relies on `on_user_turn_completed`.
- **`livekit.rtc.LocalParticipant.set_attributes` clobbers all attributes you don't pass.** The implementation (rtc/participant.py:552-571) builds the outgoing set from a fresh empty `FfiRequest` instead of reading the current attributes, so calling it with a single key wipes everything else — including `lk.agent.state`, which the React `useAgent` hook reads to determine connection state. With it missing, `agent.state` flips to `"failed"` and the template's `useAgentErrors` ends the session. `Assistant._push_attrs` writes **non-destructively**: it reads `participant.attributes`, then re-asserts (a) every attr we've ever set (`self._own_attrs`) and (b) the live `lk.agent.state` (cached from `agent_state_changed`, wired in `my_agent`). This matters because the SDK *also* writes `lk.agent.state` via the same clobber-prone call — the high-frequency `clone.heard` writes during the read would otherwise race it and drop the state. Never call `set_attributes` directly; go through `_set_clone_attrs`/`_set_style_attrs`.

## Editing conventions

- One `Agent` subclass (`Assistant`); **no `@function_tool`s** — register switching is a `set_mode` RPC (frontend → `apply_mode`), and the clone flow is driven imperatively from `run_clone_first` (a coroutine). No agent handoffs / `AgentTask` unless the flow grows.
- For any "the agent should speak something not from the LLM" use `session.say(text, add_to_chat_ctx=...)`. The clone-first prompt/ack use `add_to_chat_ctx=False` (system-only cues) so the LLM's chat context stays clean.
- To keep the agent silent for a stretch of user turns (e.g. while they read the clone script), set a flag and raise `StopResponse` from `on_user_turn_completed` (and no-op `on_user_turn_exceeded`). The activity catches `StopResponse` and skips that turn's reply while still flushing the STT transcript.
- `build_instructions(cloned=False)` is the single source of the system prompt (CORE + an optional cloned-voice note); the register/mood are NOT in it. Register changes go through `update_expressive(...)` (preset swap), not `update_instructions(...)`; only the post-clone swap rebuilds instructions (to add `CLONED_VOICE_NOTE`).
- **Fixing TTS pronunciation without changing the transcript**: override `Agent.tts_node` (audio) — NOT `transcription_node` (the on-screen text). `Assistant.tts_node` streams the text through `_fix_tts_pronunciation`, which rewrites `LiveKit` → `LIVEKIT_PHONEME` (`<|phoneme_start|>L AY1 V<|phoneme_end|> Kit`) so Fish stops saying "liv-kit". Direct-API testing nailed down the format: phoneme control **does** work on s2.1-pro (an `<|phoneme_start|>EH1 N JH AH0 N IH1 R<|phoneme_end|>` reliably says "engineer"), but the full-word phoneme `L AY1 V K IH0 T` broke it — a phoneme on just "Live" plus a plain "Kit" is what lands. The streaming rewrite holds back only a trailing prefix-of-"livekit" so the word is never split across chunk boundaries. Note: cloned voices honor this less reliably than base voices, but a single approach is used for simplicity.

## Project layout

```
src/
├── agent.py         # Assistant, set_style tool, clone-first flow, server entrypoint
└── voice_clone.py   # capture tee, VAD trim, STT transcribe, Fish HTTP (model create/delete)
scripts/
└── gen_voice_samples.py  # one-off: synth the 4 preset preview clips → web/public/voice-samples/
tests/               # test_agent.py — 3 LLM-judge eval tests (friendliness, grounding, refusal)
```
