# CLAUDE.md

LiveKit Agents (Python) **expressive-voice** demo (Fish Audio TTS). Single agent at `src/agent.py`, voice-clone + voice-design helpers at `src/voice_clone.py`. React frontend in sibling dir at `../web/` (Next.js 15 + Tailwind v4 + shadcn + `@livekit/components-react`, bootstrapped from the `agent-starter-react` template).

**Landing page picks the voice up front.** The user chooses one of 4 preset Fish voices, "clone your voice" (reads a short script, then the call begins in their clone), or "design a voice" (types a description; the worker builds it via Fish's voice-design API and greets in it). That choice rides **agent metadata** to the worker via NAMED dispatch. On top of any voice, the **user** flips the speaking register (casual/professional) with an on-screen toggle — a `set_mode` RPC swaps the agent's expressive preset and triggers a short demo line — and a **separate, cosmetic mood-classifier LLM** (in the agent process) reads each line the agent speaks and drives the on-screen mood ring. There is no `set_style` tool and no agent-controlled mood anymore.

This is a LiveKit Agents (Python) project: use `uv` for everything, app code lives under `src/` with `agent.py` as the entrypoint, and `uv run ruff check src/` / `uv run ruff format src/` must stay green. For up-to-date LiveKit docs, use the `lk docs` CLI or the LiveKit docs MCP server.

## Stack

- **STT + turn detection**: Deepgram Flux `flux-general-en` via `deepgram.STTv2` (`livekit-plugins-deepgram`, the `/v2/listen` conversational API). Flux does turn-taking itself — native `EndOfTurn` / `EagerEndOfTurn` events — so `AgentSession` is set to `turn_handling=TurnHandlingOptions(turn_detection="stt", ...)` and there is no turn-detector model. Flux knobs (in `agent.py` `AgentSession`): `eot_threshold=0.7`, `eot_timeout_ms=3000`, `eager_eot_threshold=0.5` — matched to the sibling `fish-bare-agent` setup. The `eager_eot_threshold` fires an early PREFLIGHT transcript that the SDK turns into **preemptive generation** (enabled for every session via `turn_handling.preemptive_generation`, with **`preemptive_tts=True`** so Fish TTS — not just the LLM — runs during the eager window; this is what matches fish-bare-agent's latency, since time-to-first-audio is otherwise paid only after the turn confirms).
- **LLM**: chosen by `src/llm.py` (`build_llm` for the conversation LLM, `build_mood_client` for the mood classifier). Default is OpenAI `gpt-5.1` (`livekit-plugins-openai`, direct via `OPENAI_API_KEY`, override with `OPENAI_MODEL`); the cosmetic mood-ring classifier runs separately on the cheaper `MOOD_MODEL` (default `gpt-4.1-mini`). Set `LLM_BASE_URL` to point **both** at our own OpenAI-compatible endpoint instead — e.g. self-hosted Gemma via SGLang at `https://sglang-fish-agent-gemma4-26b-a4b.dallas.api.fish.audio/v1` (`LLM_MODEL=google/gemma-4-26B-A4B-it`, `LLM_API_KEY=<bearer>`; `MOOD_MODEL` can override just the mood model). No SDK fork — the plugin is a generic `/v1/chat/completions` client, so `livekit-agents` stays freely upgradable; the provider choice is the one seam we own (`src/llm.py`).
- **TTS**: Fish Audio `s2.1-pro` (`livekit-plugins-fishaudio`)
- **VAD**: silero VAD, kept only for interruption / barge-in handling (Flux owns turn detection — see STT above). It's still required: without a VAD the agent can't detect the user speaking over its reply. Loaded once in `prewarm` and shared across thread jobs. `JOB_EXECUTOR=thread` / `NUM_IDLE_PROCESSES=1` in `agent.py` was a footprint tuning for Render's old 512MB worker; the worker now runs on LiveKit Cloud Agents (8 cores / 16GB), so there's headroom to flip `JOB_EXECUTOR=process` if wanted — not done yet.
- Runs against self-hosted `livekit-server --dev` (defaults: `ws://localhost:7880`, key `devkey`, secret `secret`) — also works against LiveKit Cloud.

## Deployment

The worker is deployed to **LiveKit Cloud Agents** (not Render anymore — Render hosts only the web frontend + `/api/token`). Build is the `Dockerfile`; `livekit.toml` pins the agent id + project subdomain. Provider keys (`FISH_API_KEY`, `DEEPGRAM_API_KEY`, `OPENAI_API_KEY`, the `LLM_*` Gemma vars, `MOOD_MODEL`) are **agent secrets** (`lk agent secrets`); `LIVEKIT_URL`/`LIVEKIT_API_KEY`/`LIVEKIT_API_SECRET` are injected by LiveKit, never set as secrets.

```bash
cd fish
lk agent deploy                          # ship a new version after code changes
lk agent status                          # rollout / replicas / CPU / mem
lk agent logs                            # runtime logs
lk agent update-secrets --secrets-file <f>   # change secrets (restarts the agent)
```

Gotcha: `uv sync` clones `livekit-agents` + the fishaudio plugin from a git source (the expressive fork in `pyproject.toml`), so the build image needs `git` — it's installed in the `Dockerfile` build stage. Without it the Cloud build fails at `uv sync` with "Git executable not found" (local/Render builds happen to have git already).

## `.env.local` (gitignored)

```
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret
DEEPGRAM_API_KEY=...
OPENAI_API_KEY=...  # agent LLM + the cosmetic mood classifier (when LLM_BASE_URL unset)
FISH_API_KEY=...
# Own LLM (optional): point the openai plugin + mood classifier at our endpoint
LLM_BASE_URL=https://sglang-fish-agent-gemma4-26b-a4b.dallas.api.fish.audio/v1
LLM_MODEL=google/gemma-4-26B-A4B-it
LLM_API_KEY=...     # bearer token for LLM_BASE_URL
# LLM_TEMPERATURE=0.6 / MOOD_MODEL=...  # optional
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

# Pick a specific mic
uv run python src/agent.py console --list-devices
uv run python src/agent.py console --input-device "<name>"

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
- **Register switch is USER-driven (no tool).** The frontend toggle (`web/components/app/mode-toggle.tsx`) calls the agent's **`set_mode` RPC** (registered on the agent's local participant in `my_agent`). The handler calls `Assistant.apply_mode(session, mode)`, which: sets `self._mode`, calls `self.update_expressive(_expressive_for(mode))` (re-resolved next reply), echoes `style.mode` back, and — unless mid clone-read — interrupts the current line (`session.interrupt(force=True)`) and fires a one-line demo reply in the new register so the switch lands immediately. `Assistant` tracks `self._mode` (default `"casual"`) and `self._cloned`.
- **Mood is a separate, cosmetic LLM — it never touches the agent's prompt or delivery.** It's driven from `tts_node` via `_mood_tee`: as the agent's spoken text finishes streaming (well before playout ends), `_schedule_mood` launches `_classify_mood` — a cheap, independent `AsyncOpenAI` call (`MOOD_MODEL`, default `gpt-4.1-mini`) that reads the line, returns `{mood, color}` JSON, and writes `style.mood`/`style.color`. Recent labels are fed back in (and it runs warm) so the word varies turn to turn instead of sticking on one. Only the latest line matters (a still-running classification is cancelled). Best-effort: failures are logged and swallowed.

## Frontend: `style.*` mood-ring indicator

Three `style.*` participant attributes drive the bottom-cluster UI (in `agent-session-block.tsx`, above the slim mic + END CALL control bar):
- `style.mode` — `casual` | `professional`. Written by `apply_mode` (the RPC handler) to echo the applied register; read by `web/components/app/mode-toggle.tsx`, which reconciles its optimistic state against it.
- `style.mood` — the one-word feeling from the mood-classifier LLM (`""` until the first classification). Read by `web/components/app/mood-indicator.tsx`.
- `style.color` — one of `gray`/`amber`/`green`/`blue`/`violet`, picked by the same classifier (gray = tense, amber = unsettled, green = calm, blue = happy/at-ease, violet = passionate/excited). The mood-indicator maps it to a glowing, state-aware dot (it pulses while the agent is thinking/speaking and shows the live state next to the mood). Seeded to the mode's resting color (`DEFAULT_MODE_COLOR`) on session start.

The text-chat input was removed (voice-only): `agent-control-bar.tsx` no longer has the chat input/toggle, and the transcript panel is always shown.

## Voice selection: landing page → agent (NAMED dispatch + agent metadata)

The chosen voice (or clone/design choice) is picked on the landing page and travels to the worker as **agent dispatch metadata**:
- Frontend `web/components/app/app.tsx` holds the selection (`useState`, default = the locale's first preset) plus the design description. It passes `{ agentName: 'fish-demo', agentMetadata: JSON.stringify(...) }` to `useSession` — `agentMetadata` is `{"voice":"<id>"}` for a preset, `{"clone":true}` for clone-first, or `{"design":"<description>"}` for design-first, always with a `"lang":"en"|"ja"` field (see the Localization section).
- The token source is `lib/token-source.ts` (`createCachingTokenSource`), a `TokenSource.custom` that POSTs the same wire format to `/api/token` that `TokenSource.endpoint` would, plus a module-level prefetch cache (see "Prewarming" below). The sandbox path still uses `getSandboxTokenSource`.
- The token route forwards `room_config` into the token unchanged. (No token-route change was needed.)
- The worker reads it as **`ctx.job.metadata`** (a JSON string) at the top of `my_agent`, validates the voice against the lang's `PRESET_VOICES[lang]` (falls back to `DEFAULT_VOICE_ID[lang]` — Maren for en, さとる for ja), clamps the design instruction to `DESIGN_INSTRUCTION_MAX_CHARS` (2000, Fish's API cap), and runs the preset greeting, clone-first, or design-first flow. `clone` wins if both clone and design are somehow set.

**This requires NAMED dispatch.** `@server.rtc_session(agent_name="fish-demo")` (constant `AGENT_NAME`) must match `APP_CONFIG_DEFAULTS.agentName` in `web/app-config.ts` (hardcoded `'fish-demo'`). A mismatch = NO agent dispatches, silently (the frontend just times out waiting for the agent). The preset `voice_id`s live in `PRESET_VOICES` (per-lang dicts) in `src/agent.py` and in `PRESET_VOICES` / `PRESET_VOICES_JA` in `web/app-config.ts` — keep them in sync. Preview clips at `web/public/voice-samples/<id>.mp3` are generated by `scripts/gen_voice_samples.py`.

## Localization: the /jp Japanese demo

The site is served in English at `/` and fully localized Japanese at `/jp` (built for on-the-go event/expo demos). How the locale flows:

- **Web**: `web/middleware.ts` stamps `x-locale` (`ja` under `/jp`) so `app/layout.tsx` can set `<html lang>` + the localized `<title>`/description (`localizeAppConfig` in `app-config.ts`). `app/jp/page.tsx` renders `<App locale="ja">`; a `LocaleProvider` (`web/lib/i18n.tsx`) carries the locale to every component — **all UI strings live in `UI_STRINGS` there**, and the JP preset voices in `PRESET_VOICES_JA` (`app-config.ts`).
- **Metadata**: the frontend adds `"lang": "ja"` (or `"en"`) to the agent metadata JSON alongside `voice`/`clone`/`design`.
- **Worker**: `my_agent` parses `lang` (unknown → `"en"`). Everything localized is keyed by it: `PRESET_VOICES`/`DEFAULT_VOICE_ID`, `CORE_INSTRUCTIONS`, all greeting instructions, `CLONE_SCRIPTS`/`CLONE_PROMPT_LINE`/`CLONE_BUILD_ACKS`, the design prompts, and `_MOOD_SYSTEM_PROMPT` (JP sessions get Japanese mood words for the ring). `Assistant(lang=...)` threads it through the flows.
- **STT**: Japanese sessions use Deepgram **`flux-general-multi`** with `language_hint=["ja"]` — same conversational Flux API (native EndOfTurn/EagerEndOfTurn), so turn handling and preemptive TTS are identical to English. English stays on `flux-general-en`.
- **fish dot audio linkification**: the JA prompt still tells the agent to write the URL as the ASCII words "fish dot audio" so `agent-chat-transcript.tsx`'s regex keeps working inside Japanese text.
- Full-width Japanese punctuation in prompt strings is allowlisted via `allowed-confusables` in `pyproject.toml` (ruff RUF001).

## Frontend: `clone.state` state machine

Only **clone-first** sessions (`{"clone":true}`) touch this; preset sessions never set it. The agent calls `self._set_clone_state("<state>")` at each transition (read-modify-write — see the `set_attributes` gotcha below). Values: `idle → prompt → reading → cloning → ready → playing`:
- `prompt` — set on entry to `run_clone_first`; the script is on screen and the agent is speaking the "read this aloud" line. Also publishes `clone.script` (the script text) and `clone.read_secs` (the read-window length, "15").
- `reading` — the prompt line finished playing; the fixed `CLONE_READ_SECS` window is running. The frontend starts its countdown when it sees this transition.
- `cloning` — window closed, upload started.
- `ready` — Fish returned the model_id.
- `playing` — TTS swapped to the clone; reveal greeting about to play.

React reads it via `useParticipantAttribute('clone.state', ...)`. It drives `web/components/app/clone-script-card.tsx` — the centered card that shows the full-color script during `prompt`/`reading`, a subtle **mic waveform** (`useMultibandTrackVolume` on the LOCAL mic track — live "we hear you" feedback, no backend involved), and a local countdown + progress bar during `reading` (display-only; the agent's own `asyncio.sleep(CLONE_READ_SECS)` is the authoritative timer). There is no word-highlighting and no `clone.heard`/`clone.capture_secs` anymore — the old STT fuzzy-match highlighting was removed with the fixed-window flow. Once `state === 'cloning'` the same card swaps the script for the loading dot (`AgentChatIndicator`, the indicator used elsewhere for "thinking").

**The read is kept out of the chat.** `agent-chat-transcript.tsx` (`FilteredMessages`) hides any message seen while `clone.state` is `prompt`/`reading`/`cloning` (the user reading + the agent's read prompt/ack), via a persistent id set — so the script read never lands in the transcript, but the post-clone reveal + conversation do. (There's no clean backend toggle: `session.output.set_transcription_enabled` gates only the agent's transcript, not the user-transcript forwarding path.)

## Frontend: `design.state` (design-first sessions)

Only **design-first** sessions (`{"design":"..."}`) touch this. Values: `designing → ready` (or `failed`). `web/components/app/design-status-card.tsx` shows a centered "Designing your voice" card while `designing`; the agent's spoken ack/reveal are NOT filtered from the transcript (there's no user reading to hide, unlike the clone flow).

Don't reuse the built-in `lk.agent.state` attribute (`listening`/`thinking`/`speaking`) for cloning UI — it flickers during `session.say` and tool execution and isn't a clean source of truth.

## Clone-first flow (upfront, controller-driven)

Cloning is **upfront-only** — there is no opportunistic mid-conversation clone anymore (no `clone_my_voice` tool). `Assistant.run_clone_first(session, ctx)` runs the whole thing as a straight-line coroutine with a **fixed read window**:

0. The read script is `random.choice(CLONE_SCRIPTS[lang])` — 10 per language, all about the same length to speak, so repeat demos don't hear the same passage. It's published as `clone.script` for the card; it is **never** sent to Fish as a reference transcript (see step 6).
1. `install_capture(session)` tees `session.input.audio` through `PassthroughCaptureAudioInput` (forwards every frame, buffers when `tee.recording` — toggled by `user_state_changed` speaking/not-speaking — hard-capped at `CAPTURE_MAX_SECS=30`). `_suppress_replies = True`.
2. Publish `clone.script` + `clone.read_secs` + `clone.state="prompt"`, `await ctx.connect()` (so the mic is live), then `session.say(CLONE_PROMPT_LINE)` in the starting preset voice and **wait for its playout**.
3. `clone.state="reading"`, then simply `await asyncio.sleep(CLONE_READ_SECS)` (15s). No STT matching, no speech-time targets — the frontend mirrors the same countdown, and anything the user said during the prompt line is already buffered.
4. **Reply suppression:** while `_suppress_replies`, `on_user_turn_completed` raises `StopResponse` (and `on_user_turn_exceeded` no-ops) so the agent stays silent and never talks over the read. This holds even with preemptive generation on (now enabled for every session): the speculative reply is held (`schedule_speech=False`) until *after* `on_user_turn_completed`, so the `StopResponse` gate still drops it, and a >10s read exceeds `max_speech_duration` and skips preemption anyway. (See the preemptive-generation note in "Things that will bite you".)
5. Under-read fallback: if the tee buffered `< CLONE_MIN_SECS` (6s) of speech, reset to `idle`, clear `_suppress_replies`, and greet in the preset voice (`CLONE_FALLBACK_GREETING`).
6. Otherwise `clone.state="cloning"`, fire `_run_clone_upload(frames, vad)` as a task (silero VAD-trim → POST `/model` to Fish, `train_mode=fast`, **no reference transcript**), and `session.say` a one-line ack in the preset voice to fill the window. `await` the upload (fall back to `idle` + preset greeting on failure). We deliberately skip computing a reference transcript: streaming STT runs at ~1× realtime, so transcribing ~15s of read added ~15–20s and dominated the clone time (pushing the whole flow past the frontend agent-connect timeout). Fish clones fine from audio alone, and skipping it is more mis-read-robust (no text/audio mismatch).
7. On model_id: append it to `_ephemeral_voice_ids`, `clone.state="ready"`, await the ack's `wait_for_playout()`, `fishaudio.TTS.update_options(voice_id=model_id)`, `clone.state="playing"`. Set `_cloned=True`, `update_instructions(build_instructions(cloned=True))` (adds the slim "you're in their cloned voice; fish dot audio for permanent" note), clear `_suppress_replies`, and `generate_reply(CLONE_REVEAL_GREETING)` — the first line is already in the cloned voice.
8. On session end, `ctx.add_shutdown_callback` `DELETE`s every model in `_ephemeral_voice_ids`.

Preset sessions skip all of this: `my_agent` just seeds the mood-ring and `generate_reply(PRESET_GREETING)` then `ctx.connect()`.

## Design-first flow (upfront, controller-driven)

`{"design":"<description>"}` sessions build a brand-new voice from the user's text description via Fish's **voice-design API** (`src/voice_clone.py: design_voice_sample` → one candidate WAV, ~2-3s) and register it as a private TTS model (`create_designed_voice` → the same create-model endpoint the clone flow uses, with `DESIGN_REFERENCE_TEXT` as the known transcript, ~2-3s; ~5s total measured).

- **The build starts at the very top of `my_agent`** (an `asyncio.Task` created right after metadata parsing) so the two Fish round trips overlap session start + room connect. A done-callback appends the model id to `_ephemeral_voice_ids` the moment it exists, so cleanup can't miss it.
- `Assistant.run_design_first(session, ctx, design_task, instruction)`: `_suppress_replies=True`, `design.state="designing"`, `ctx.connect()`, then an **LLM-generated ack** (`generate_reply(design_ack_instructions(instruction))`, preset voice, non-interruptible) that makes a light comment on the user's description while the build finishes — the LLM round trip overlaps the already-running design task. Then `await asyncio.wait_for(design_task, DESIGN_TIMEOUT_SECS=75)`, await the ack's playout, `update_options(voice_id=model_id)`, `design.state="ready"`, `update_instructions(build_instructions(designed=True))` (adds `DESIGNED_VOICE_NOTE`), clear suppression, `generate_reply(DESIGN_REVEAL_GREETING)` — first line in the designed voice. Any failure → `design.state="failed"` + `DESIGN_FALLBACK_GREETING` in the preset voice.
- The voice-design endpoint is **stateless** (returns base64 WAV candidates, no model) and needs the `model: voice-design-1` HTTP header. Instruction is clamped to 2000 chars (both sides), `reference_text` capped at 150.

## Things that will bite you

- **Console mode mocks `ctx.room`.** Anything that touches `rtc.AudioStream.from_participant` or `participant._ffi_handle` will crash with `AttributeError: Mock object has no attribute '_ffi_handle'`. For audio capture, go through `session.input.audio` — uniform across console + rtc.
- **The STT plugin is streaming-only** (`deepgram.STTv2` / Flux is a realtime websocket model on `/v2/listen`; no batch `recognize()`). Flux drives turn detection natively (`turn_detection="stt"`). The clone upload no longer computes a reference transcript (it dominated latency — see the clone-first flow), and the old live read-highlighting (`clone.heard`) was removed with the fixed-window read.
- **Silero `END_OF_SPEECH` requires trailing silence** (~`min_silence_duration`). `vad_trim_frames` pads with ~1s of silence so the event fires even when the user is still mid-word at the buffered-frames cutoff.
- **`fishaudio.TTS.update_options(voice_id=...)` applies to the *next* synthesis**, not mid-utterance. `ChunkedStream`/`SynthesizeStream` copy `_opts` on construction.
- **The clone-first read holds the agent in a long pre-greeting phase — the frontend's agent-connect timeout must cover it.** `useSession`'s default `agentConnectTimeoutMilliseconds` is **20s**; it's a one-shot check that flips the agent to `state==="failed"` if `lk.agent.state` isn't `listening`/`thinking`/`speaking` at that instant. In a clone session the agent only `generate_reply`s *after* the read + clone build, and the high-frequency `clone.heard` attribute writes during the read lag/contend with the SDK's own `lk.agent.state` updates — so at 20s the frontend may not have registered "listening" yet. We pass `agentConnectTimeoutMilliseconds: 90_000` in `web/components/app/app.tsx` so the check lands well after the read+clone settles (the clone itself is now fast — no reference transcript). Any `generate_reply`/`say` in `run_clone_first` must also tolerate a closed session (the user can disconnect mid-read) — use `_safe_generate_reply`, which swallows the `RuntimeError("AgentSession isn't running")` instead of crashing the job.
- **Preemptive generation is enabled for EVERY session** (`turn_handling.preemptive_generation={"enabled": True, "preemptive_tts": True}` in `my_agent`), driven by Flux's `eager_eot_threshold`. `preemptive_tts=True` matters for latency: it starts Fish TTS synthesis during the eager window (not just the LLM), so on the confirmed EndOfTurn the audio is already buffered — matching fish-bare-agent. With it off you still pay Fish's time-to-first-audio after the turn confirms. It's tempting to think it races the clone/design reply-suppression, but it doesn't in this SDK version: `on_preemptive_generation` builds the speculative reply with `schedule_speech=False` (held, silent), and `_on_user_turn_completed` only *schedules* it **after** calling `on_user_turn_completed` — so the `StopResponse` we raise there returns before the handle is ever scheduled, and no audio plays during the read/build window. Two extra guards: preemptive gen doesn't even start while a non-interruptible `session.say` (the read prompt / ack) is playing, and a read longer than `max_speech_duration` (10s default) skips preemption. If you ever need to hard-disable it for a session, set `preemptive_generation={"enabled": False}` — do NOT resurrect the old per-session gating, it's unnecessary.
- **`livekit.rtc.LocalParticipant.set_attributes` clobbers all attributes you don't pass.** The implementation (rtc/participant.py:552-571) builds the outgoing set from a fresh empty `FfiRequest` instead of reading the current attributes, so calling it with a single key wipes everything else — including `lk.agent.state`, which the React `useAgent` hook reads to determine connection state. With it missing, `agent.state` flips to `"failed"` (which now just shows a transient "Reconnecting" pill — `useAgentErrors` is log-only and no longer ends the call — but it still looks broken, so avoid it). `Assistant._push_attrs` writes **non-destructively**: it reads `participant.attributes`, then re-asserts (a) every attr we've ever set (`self._own_attrs`) and (b) the live `lk.agent.state` (cached from `agent_state_changed`, wired in `my_agent`). This matters because the SDK *also* writes `lk.agent.state` via the same clobber-prone call — the high-frequency `clone.heard` writes during the read would otherwise race it and drop the state. Never call `set_attributes` directly; go through `_set_clone_attrs`/`_set_style_attrs`.

## Editing conventions

- One `Agent` subclass (`Assistant`); **no `@function_tool`s** — register switching is a `set_mode` RPC (frontend → `apply_mode`), and the clone flow is driven imperatively from `run_clone_first` (a coroutine). No agent handoffs / `AgentTask` unless the flow grows.
- For any "the agent should speak something not from the LLM" use `session.say(text, add_to_chat_ctx=...)`. The clone-first prompt/ack use `add_to_chat_ctx=False` (system-only cues) so the LLM's chat context stays clean.
- To keep the agent silent for a stretch of user turns (e.g. while they read the clone script), set a flag and raise `StopResponse` from `on_user_turn_completed` (and no-op `on_user_turn_exceeded`). The activity catches `StopResponse` and skips that turn's reply while still flushing the STT transcript.
- `build_instructions(cloned=False)` is the single source of the system prompt (CORE + an optional cloned-voice note); the register/mood are NOT in it. Register changes go through `update_expressive(...)` (preset swap), not `update_instructions(...)`; only the post-clone swap rebuilds instructions (to add `CLONED_VOICE_NOTE`).
- **Fixing TTS pronunciation without changing the transcript**: override `Agent.tts_node` (audio) — NOT `transcription_node` (the on-screen text). `Assistant.tts_node` streams the text through `_fix_tts_pronunciation`, which rewrites `LiveKit` → `LIVEKIT_PHONEME` (`<|phoneme_start|>L AY1 V<|phoneme_end|> Kit`) so Fish stops saying "liv-kit". Direct-API testing nailed down the format: phoneme control **does** work on s2.1-pro (an `<|phoneme_start|>EH1 N JH AH0 N IH1 R<|phoneme_end|>` reliably says "engineer"), but the full-word phoneme `L AY1 V K IH0 T` broke it — a phoneme on just "Live" plus a plain "Kit" is what lands. The streaming rewrite holds back only a trailing prefix-of-"livekit" so the word is never split across chunk boundaries. Note: cloned voices honor this less reliably than base voices, but a single approach is used for simplicity.

## Prewarming (first-line latency)

Both sides shave setup work off the "Start call" click:
- **Frontend** (`web/components/app/app.tsx`): on load it warms the mic (a getUserMedia that immediately stops its tracks — surfaces the permission prompt early and pre-opens the device) and calls `session.prepareConnection()` on load + every selection change (token mint + DNS/TLS + LiveKit Cloud region pinning). Token reuse needs our own cache (`web/lib/token-source.ts`): livekit-client's `TokenSourceCached` has an **inverted cache check** (returns the cached token only when fetch options DIFFER — i.e. exactly when it would be wrong), so app.tsx recreates the token source whenever `agentMetadata` changes (empty outer cache = always correct) and `createCachingTokenSource`'s module-level cache provides the actual prefetch reuse (keyed by agentName+agentMetadata, 10-min max age, cleared on connect since a consumed token pins a used room name).
- **Worker** (`src/agent.py`): the fishaudio plugin (fork) now reuses **one `/v1/tts/live` socket per session** via `utils.ConnectionPool` and implements a real `prewarm()` (`self._pool.prewarm()`) that the framework calls at agent-activity start — so the first utterance skips the ~330ms websocket handshake (DNS+TCP+TLS+WS upgrade) and every later reply reuses the warm socket. It also takes a **`prebuffer_chunks`** count (we pass `2` in `build_tts`) that waits for Fish's second chunk before starting playout, removing the cold-start buffer underrun (Fish's small ~460ms first chunk + a ~250ms gap) that caused the intermittent first-utterance crackle over WebRTC. It's a client-side stopgap for Fish's bursty cold-start pacing; the real fix is smoother server-side chunk delivery. The old app-level `_PrewarmingFishTTS` HEAD-request shim was removed — the plugin's own prewarm supersedes it. The design build starts at the top of `my_agent`; the preset greeting `generate_reply` still runs before `ctx.connect()`; `preemptive_generation` is on for all sessions (Flux eager-EOT driven).

## Project layout

```
src/
├── agent.py         # Assistant, set_mode RPC + apply_mode, mood classifier, clone-first + design-first flows, server entrypoint
└── voice_clone.py   # capture tee, VAD trim, frames->wav, Fish HTTP (model create/delete, voice design)
scripts/
└── gen_voice_samples.py  # one-off: synth the 4 preset preview clips → web/public/voice-samples/
tests/               # test_agent.py — 3 LLM-judge eval tests (friendliness, grounding, refusal)
```
