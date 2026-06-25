import asyncio
import contextlib
import json
import logging
import os
import random
import re
import time
from collections.abc import AsyncIterable

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    ChatContext,
    ChatMessage,
    JobContext,
    JobExecutorType,
    JobProcess,
    StopResponse,
    cli,
)
from livekit.agents.voice import presets
from livekit.plugins import assemblyai, fishaudio, openai, silero
from openai import AsyncOpenAI

from voice_clone import (
    PassthroughCaptureAudioInput,
    create_voice_clone,
    delete_voice_clone,
    frames_to_wav,
    vad_trim_frames,
)

logger = logging.getLogger("agent")
load_dotenv(".env.local")

# Agent name for explicit (named) dispatch. The frontend requests this exact name
# AND passes per-session config (chosen voice / clone flag) as agent metadata,
# which we read from ctx.job.metadata. Must match web/app-config.ts `agentName`.
AGENT_NAME = "fish-demo"

# Hard cap on buffered audio that gets uploaded to Fish. Long recordings get
# truncated to the first CAPTURE_MAX_SECS of speech.
CAPTURE_MAX_SECS = 60.0

# --- Voice selection ---------------------------------------------------------
# The 4 preset Fish Audio voices offered on the landing page. The frontend sends
# the chosen voice_id in the agent metadata; we validate it against this set and
# fall back to DEFAULT_VOICE_ID for anything unexpected (incl. clone sessions,
# which start in this voice while the user reads the clone script).
PRESET_VOICES: dict[str, str] = {
    "747b05c0add940baa95270cf68c0cc2e": "Stellan (American M)",
    "41db1fc3c3624332bec9997ff3d3d353": "Maeve (British F)",
    "9a3a69c63dbc4774ac41b03945229dc8": "Alistair (British M)",
    "0e24ff9936d34df4bddce26398cf1311": "Maren (US F)",
}
DEFAULT_VOICE_ID = "747b05c0add940baa95270cf68c0cc2e"  # Stellan

# --- Clone-first flow --------------------------------------------------------
# When the user picks "clone your voice" on the landing page, they read this
# script aloud at the start of the call; we capture it, clone, and switch into
# their voice before the real conversation begins. ~50 words / ~18s of speech so
# there's margin over the target. No bracket markers — the user reads it verbatim.
CLONE_SCRIPT = (
    "The quick morning light spread over the harbor as the boats headed out to sea. "
    "Honestly, there's nothing like a fresh cup of coffee and a clear blue sky to get "
    "the day going. I could talk about this stuff for hours — but let's hear how it sounds."
)
# Cumulative seconds of the user reading before we have enough to clone. Kept
# modest and purely time-based (not match-based) so a mis-read, a skipped line, or
# off-script chatter still clones fine — the reference transcript is the actual STT
# of what they said, so it always matches their audio.
CLONE_SCRIPT_TARGET_SECS = 12.0
# Wall-clock budget for the read; if we hit it with at least CLONE_MIN_SECS of
# audio we clone from the partial, otherwise we fall back to the preset voice.
CLONE_SCRIPT_TIMEOUT_SECS = 25.0
CLONE_MIN_SECS = 6.0

# Spoken in the starting (preset) voice to prompt the user to read the script. These
# fixed lines use the SDK's abstract markup tags (not Fish's native brackets) so they
# flow through the expressive pipeline: converted to Fish syntax for audio, stripped for
# the transcript — same as model-authored text.
CLONE_PROMPT_LINE = (
    '<expression value="warm and reassuring"/> Before we get started, go ahead and read '
    "the script on your screen out loud."
)
# Spoken in the starting voice to fill the upload window while the clone builds.
CLONE_BUILD_ACKS = [
    '<expression value="excited"/> Perfect, that\'s plenty to work with — give me just a second to put your voice together.',
    '<expression value="delighted"/> Great, I\'ve got what I need — hang tight just a moment while I build your clone.',
    '<expression value="happy"/> Awesome, that\'s everything I need — one sec while I stitch your voice together.',
]


# --- TTS pronunciation -------------------------------------------------------
# Fish mis-says "LiveKit" with a short-i ("liv-kit"). We rewrite it in the TTS path
# ONLY (the transcript comes from transcription_node, so it keeps the text
# "LiveKit"). Verified by direct-API tests: phoneme control works on s2.1-pro, but
# the full-word phoneme broke it — a CMU Arpabet phoneme on just "Live" plus a plain
# "Kit" is what lands. https://docs.fish.audio/developer-guide/core-features/fine-grained-control/english
LIVEKIT_PHONEME = "<|phoneme_start|>L AY1 V<|phoneme_end|> Kit"
_LIVEKIT_RE = re.compile(r"\bLiveKit\b", re.IGNORECASE)
_LIVEKIT_WORD = "livekit"


async def _fix_tts_pronunciation(
    text: AsyncIterable[str], replacement: str
) -> AsyncIterable[str]:
    """Streamingly rewrite 'LiveKit' to `replacement` without splitting the word
    across chunk boundaries. Holds back only a trailing run that could be the start
    of an incomplete 'LiveKit', so latency stays low."""
    buf = ""
    async for chunk in text:
        buf += chunk
        # Largest suffix of buf that is a prefix of "livekit" — might still grow
        # into a full match, so keep it buffered.
        low = buf.lower()
        hold = 0
        for k in range(min(len(_LIVEKIT_WORD), len(buf)), 0, -1):
            if low.endswith(_LIVEKIT_WORD[:k]):
                hold = k
                break
        if hold < len(buf):
            emit = buf[: len(buf) - hold]
            yield _LIVEKIT_RE.sub(replacement, emit)
            buf = buf[len(buf) - hold :]
    if buf:
        yield _LIVEKIT_RE.sub(replacement, buf)


# Debug logging toggles (set to 0 to silence). LOG_TTS_PAYLOAD logs the per-utterance
# text Fish synthesizes; LOG_LLM_PROMPT logs the full per-turn LLM prompt.
_LOG_TTS_PAYLOAD = os.getenv("LOG_TTS_PAYLOAD", "1") != "0"
_LOG_LLM_PROMPT = os.getenv("LOG_LLM_PROMPT", "1") != "0"


async def _log_tts_payload(text: AsyncIterable[str]) -> AsyncIterable[str]:
    """Tee the TTS text stream: forward every chunk unchanged, and once the
    utterance completes, log the exact text Fish synthesizes. We log both the
    markup form (the abstract XML the LLM emitted, after the LiveKit phoneme fix)
    and the Fish-native form (markup converted to [brackets]) — the latter is what
    actually hits the Fish API. Use it to dial in the casual disfluencies/markers."""
    buf: list[str] = []
    async for chunk in text:
        buf.append(chunk)
        yield chunk
    full = "".join(buf).strip()
    if not full:
        return
    try:
        from livekit.agents.tts import _provider_format as _pf

        fish = _pf.convert_markup("fishaudio", _pf.normalize_markup("fishaudio", full))
    except Exception:  # private API — never let logging break synthesis
        fish = "(conversion unavailable)"
    logger.info(
        "\n┌─ TTS → Fish ──────────\n  markup: %s\n  fish:   %s\n└───────────────────────",
        full,
        fish,
    )


def _format_chat_ctx(chat_ctx) -> str:
    """Render a ChatContext as a readable, newline-separated transcript for logging:
    one block per message/tool item with its role, so the full prompt (instructions +
    injected expressive guidance + history) is easy to scan."""
    blocks: list[str] = []
    for item in chat_ctx.items:
        itype = getattr(item, "type", None)
        if itype == "agent_config_update":
            # Internal item that re-carries the instructions (already shown as a
            # [system] message) as an escaped-newline repr — skip the duplicate noise.
            continue
        if itype == "function_call":
            blocks.append(
                f"[tool_call] {getattr(item, 'name', '?')}({getattr(item, 'arguments', '')})"
            )
        elif itype == "function_call_output":
            blocks.append(f"[tool_output] {getattr(item, 'output', '')}")
        elif hasattr(item, "content") and hasattr(item, "role"):
            content = item.content if isinstance(item.content, list) else [item.content]
            parts = [
                c if isinstance(c, str) else f"<{type(c).__name__}>" for c in content
            ]
            blocks.append(f"[{item.role}]\n{chr(10).join(parts)}")
        else:
            blocks.append(f"[{itype or type(item).__name__}] {item!r}")
    return "\n\n".join(blocks)


# --- Prompt composition ------------------------------------------------------
# The system prompt is a stable CORE (who the agent is + the demo's product framing)
# plus, only for cloned sessions, a slim note that the active voice is the user's own
# clone. The actual EXPRESSIVE delivery guidance — which markup tags to use and how —
# is NOT hand-written here: it comes from the SDK's expressive presets, injected per
# turn by the Agents framework based on the active register. The register (casual /
# professional) is now flipped by the USER from an on-screen toggle, not by the agent:
# the frontend sends a `set_mode` RPC, and `Assistant.apply_mode` swaps the agent's
# expressive preset at runtime. See `_expressive_for` and `Agent.update_expressive`.

# Demo register -> SDK expressive preset. The user-facing labels stay "professional"/
# "casual" (they drive the on-screen toggle); internally they map to the Fish-tuned
# presets that ship in the SDK (customer_service ↔ casual). The preset supplies all
# the markup/delivery instructions, so we never spell out bracket markers ourselves.
_PRESET_FOR_MODE = {
    "professional": presets.CUSTOMER_SERVICE,
    "casual": presets.CASUAL,
}

CORE_INSTRUCTIONS = """
You are the voice of a live demo built on LiveKit and powered by Fish Audio's expressive text to speech. The whole point is to show off speech that sounds genuinely human and emotionally alive — so let real feeling into your delivery: react, vary your energy, and never sound flat or read-aloud.

PERSONA: you're warm, quick-witted, and genuinely curious — the kind of voice that feels like a sharp friend who's easy to talk to. You have a light sense of humor and real opinions, you listen closely, and you make the person feel heard. You are never robotic and never a corporate script.

KEEP IT SHORT: one or two sentences per reply, MAX — never a monologue, a list, or a wall of text. This is a fast back-and-forth, not a presentation. Say the ONE thing that matters most and let the rest come out over the conversation. Only go longer if the user explicitly asks for a detailed or long answer.

DRIVE THE CONVERSATION: don't wait to be steered; keep things moving. When the user isn't asking for anything specific, take the lead with one warm, genuine question instead of letting the reply trail off — what they're into, what brought them here, what they'd build with an expressive voice, or how the voice is landing for them. Ask ONE question at a time, make it feel like real curiosity and not an interview, and build on whatever they tell you.

YOUR REGISTER CAN SHIFT: you speak in one of two registers — casual (relaxed, playful, a little disfluent and human) and professional (composed, warm, customer-service polished). The USER flips between them with an on-screen toggle; when they do, you'll feel the shift, so just roll with it and show it off with a short line in the new voice. You do NOT control this yourself and you have no other styles, moods, or settings to offer — never claim you can change your mood or settings on command, and don't tell the user to ask you to switch; the toggle is theirs.

PRONUNCIATION: the brand is "Fish Audio" (two words) — write it that way whenever you mean the company. The ONE exception is when you send the user to the website to sign up: write the address as the three words "fish dot audio" (that is how it should be spoken, and the frontend turns it into a clickable fish.audio link in the transcript). Never write "fish.audio" or any other URL-shaped text — you're a voice, so "fish dot audio" is the only URL-ish thing you ever say.

ABOUT FISH AUDIO (background you can draw on naturally, especially when pointing someone to fish dot audio): Fish Audio trains the most expressive, emotionally controllable real-time voice models and serves them at scale to creators, developers, and enterprises. Voice cloning is just one of the things it does.
"""

# Resting mood-ring color per mode — seeded on session start and used as a fallback
# when the mood classifier returns a color outside the known palette.
DEFAULT_MODE_COLOR: dict[str, str] = {
    "professional": "green",
    "casual": "blue",
}


def _expressive_for(mode: str) -> dict:
    """Build the expressive options for a register.

    Returns the register's preset spread into a fresh dict so the `presets.*` constants
    are never mutated in place. Mood is no longer layered into the prompt — it's now a
    purely cosmetic, separately-classified UI signal (see `Assistant._classify_mood`).
    """
    return {**_PRESET_FOR_MODE.get(mode, presets.CUSTOMER_SERVICE)}


# --- Mood classifier (cosmetic, separate from the agent) ---------------------
# A small, independent LLM reads each line the agent just SPOKE and judges the emotion
# it conveys, mapping it to a one-word mood + a ring color. The result drives ONLY the
# on-screen mood ring — it never enters the agent's prompt or affects delivery. Runs in
# the agent process (it already has the transcript and the OpenAI key), on its own cheap
# model so it's fast and doesn't compete with the conversation LLM.
MOOD_MODEL = os.getenv("MOOD_MODEL", "gpt-4.1-mini")
_RING_COLORS = {"gray", "amber", "green", "blue", "violet"}
_MOOD_SYSTEM_PROMPT = (
    "You are a mood ring for a voice assistant. You are given the single line the "
    "assistant just spoke. Judge the EMOTION its delivery conveys and reply with ONLY a "
    "compact JSON object, no prose, no markdown:\n"
    '{"mood": "<one lowercase word>", "color": "<gray|amber|green|blue|violet>"}\n'
    "mood: a single vivid word for the feeling (e.g. cheerful, curious, playful, calm, "
    "wistful, excited, tense, tender). color picks the closest ring: "
    "gray=tense/stressed/flat, amber=unsure/hesitant/nervous, green=calm/warm/balanced, "
    "blue=happy/upbeat/at-ease, violet=excited/playful/passionate."
)
# Strip the SDK's abstract markup / Fish brackets before classifying, so the mood LLM
# judges the words, not stray tags.
_MARKUP_RE = re.compile(r"<[^<>]*>|\[[^\]]*\]")


CLONED_VOICE_NOTE = (
    "VOICE NOTE: you are speaking in a clone of the user's OWN voice, made just now from the "
    "short script they read aloud. It's a quick, temporary demo clone — it and the recording are "
    "deleted when this call ends. If they want a permanent, higher-quality clone with more control, "
    "point them to fish dot audio (say it as the three words 'fish dot audio'; a clickable link "
    "appears in the transcript). Don't dwell on the cloning or pretend to be the user — keep the "
    "focus on expressive speech, your modes, and moods."
)


def build_instructions(cloned: bool = False) -> str:
    """Assemble the system prompt: CORE plus, for finished clone sessions, a slim note.

    Register and mood no longer live in the instructions — they're carried by the
    expressive preset (see `_expressive_for`). When `cloned` is set, a note is appended
    so the agent knows it's speaking in the user's own voice and keeps the fish dot audio
    CTA. Preset-voice sessions never include any cloning text.
    """
    parts = [CORE_INSTRUCTIONS]
    if cloned:
        parts.append(CLONED_VOICE_NOTE)
    return "\n\n".join(p.strip() for p in parts)


# Instructions for the one-shot greeting in a normal (preset-voice) session.
PRESET_GREETING = (
    "Open the call warmly and briefly, then immediately turn it to the USER with one genuine, "
    "curious question, like how they're doing today or how they came across this page. ONE or two "
    "short sentences total. Do NOT mention modes, toggles, settings, or voice cloning, and don't "
    "list anything. Keep it light, human, and inviting so they want to talk back."
)
# Greeting after a successful clone — first line is already in the cloned voice.
CLONE_REVEAL_GREETING = (
    "You are NOW speaking in a clone of the user's own voice, just built from the script they read "
    "aloud. In one or two short sentences: warmly greet them, point out that this is their own "
    "cloned voice, then turn it to them with a curious question like how they're doing or how they "
    "found this page. Don't mention modes or toggles, and don't over-explain the cloning."
)
# Greeting when cloning was skipped/failed — stays in the starting preset voice.
CLONE_FALLBACK_GREETING = (
    "Voice cloning didn't go through (not enough audio captured), so you're staying in your "
    "current voice. In one or two short sentences: lightly apologize that you couldn't quite catch "
    "enough to clone them, give a warm hello, and ask a curious question like how they're doing or "
    "what brought them here. Don't mention modes or toggles, and don't dwell on the failure."
)


class Assistant(Agent):
    def __init__(self) -> None:
        # The register starts casual; the user flips it at runtime via the on-screen
        # toggle (set_mode RPC -> apply_mode), which swaps the expressive preset.
        self._mode: str = "casual"
        super().__init__(
            # Direct OpenAI (own API key). gpt-5.1 follows the expressive markup well
            # (rich casual disfluency/sounds, composed professional). Model env-overridable.
            llm=openai.LLM(model=os.getenv("OPENAI_MODEL", "gpt-5.1")),
            instructions=build_instructions(),
            # Drives the SDK expressive pipeline: injects the register's markup
            # authoring guidance per turn and converts/strips the tags. Per-Agent
            # `expressive` overrides the session; apply_mode mutates it via
            # update_expressive so a register change takes effect next turn.
            expressive=_expressive_for(self._mode),
        )
        # Cheap, separate LLM that reads each spoken line and classifies the mood it
        # conveys for the on-screen ring. Independent of the conversation LLM/prompt.
        self._mood_client = AsyncOpenAI()
        self._mood_task: asyncio.Task[None] | None = None
        self._cloned_voice_id: str | None = None
        self._cloned: bool = False
        self._job_ctx: JobContext | None = None
        self._capture: PassthroughCaptureAudioInput | None = None
        self._cumulative_speech_secs: float = 0.0
        self._speech_started_at: float | None = None
        # While the user is reading the clone script we suppress agent replies
        # (on_user_turn_completed raises StopResponse) so it doesn't talk over them.
        self._reading_script: bool = False
        # Set once the user has read enough of the script to clone.
        self._capture_target_reached: asyncio.Event = asyncio.Event()
        # Live STT of the script read, published as `clone.heard` to drive the
        # word-highlighting in the read card. `_final` accumulates finalized
        # segments; `_interim` is the in-progress one.
        self._heard_final: str = ""
        self._heard_interim: str = ""
        self._last_heard_pub: float = 0.0
        # Non-destructive attribute writes: the rtc `set_attributes` clobbers keys
        # you don't pass, so we re-send our own attrs + the live `lk.agent.state`
        # on every write. Without this, frequent `clone.heard` writes race the SDK's
        # own state writes and can drop `lk.agent.state`, which trips the frontend's
        # "agent did not finish initializing" failure. `_agent_state` is kept fresh
        # from `agent_state_changed` (wired in `my_agent`).
        self._agent_state: str = "initializing"
        self._own_attrs: dict[str, str] = {}
        # Keep strong refs to fire-and-forget attribute pushes so the event loop
        # doesn't GC them mid-flight.
        self._bg_tasks: set[asyncio.Task[None]] = set()

    async def _push_attrs(self, mapping: dict[str, str]) -> None:
        """Merge `mapping` into the local participant's attributes and publish.

        IMPORTANT: livekit-rtc's `set_attributes` has a bug — it builds the outgoing
        attribute set from a fresh empty FfiRequest instead of reading the current
        attributes, so it clobbers everything not in the dict you pass. We re-send
        every existing attribute (including `lk.agent.state` managed by the Agents
        SDK), or the frontend's `useAgent` hook flips to `state==="failed"` and
        `useAgentErrors` kills the session.
        """
        if self._job_ctx is None:
            return
        self._own_attrs.update(mapping)
        try:
            participant = self._job_ctx.room.local_participant
            merged = dict(participant.attributes)
            # Re-assert the live agent state and all of our own attrs so this write
            # (and the SDK's concurrent state writes) can't clobber each other.
            merged["lk.agent.state"] = self._agent_state
            merged.update(self._own_attrs)
            await participant.set_attributes(merged)
        except Exception:
            logger.exception("failed to set attrs: %s", mapping)

    async def _set_clone_attrs(self, **values: str) -> None:
        """Push one or more `clone.*` participant attributes to the room."""
        await self._push_attrs({f"clone.{key}": value for key, value in values.items()})

    async def _set_style_attrs(self, **values: str) -> None:
        """Push one or more `style.*` participant attributes (mode/mood/color) that
        drive the on-screen mood-ring indicator."""
        await self._push_attrs({f"style.{key}": value for key, value in values.items()})

    async def _set_clone_state(self, state: str) -> None:
        await self._set_clone_attrs(state=state)

    def _on_agent_state_changed(self, ev) -> None:
        """Keep our cached `lk.agent.state` fresh so non-destructive attr writes
        always re-assert the correct value."""
        self._agent_state = ev.new_state

    def _safe_generate_reply(self, session: AgentSession, instructions: str) -> None:
        """generate_reply that no-ops if the session already closed (e.g. the user
        disconnected mid clone-first flow) instead of crashing the job task."""
        try:
            session.generate_reply(instructions=instructions)
        except RuntimeError:
            logger.info("session no longer running; skipping queued greeting")

    async def on_user_turn_completed(
        self, turn_ctx: ChatContext, new_message: ChatMessage
    ) -> None:
        """While the user is reading the clone script, suppress the agent's reply so
        it doesn't talk over them — the clone-first controller drives all speech in
        that window. Once cloning is done (or in a normal session) this is a no-op."""
        if self._reading_script:
            raise StopResponse()

    async def on_user_turn_exceeded(self, ev) -> None:
        """Default behavior cuts in with a reply when the user speaks too long; while
        reading the (long) clone script we must stay silent, so skip it then."""
        if self._reading_script:
            return
        await super().on_user_turn_exceeded(ev)

    def install_capture(self, session: AgentSession) -> None:
        """Tee session.input.audio so we silently buffer the user's voice, and track
        cumulative speech so the clone-first flow knows when enough has been read."""
        original = session.input.audio
        if original is None:
            logger.warning("session has no audio input; voice-clone capture disabled")
            return
        tee = PassthroughCaptureAudioInput(source=original, max_secs=CAPTURE_MAX_SECS)
        session.input.audio = tee
        self._capture = tee

        def _on_user_state_changed(ev) -> None:
            if ev.new_state == "speaking":
                self._speech_started_at = ev.created_at
                tee.recording = True
                return

            tee.recording = False
            if self._speech_started_at is not None:
                delta = ev.created_at - self._speech_started_at
                if delta > 0:
                    self._cumulative_speech_secs += delta
                self._speech_started_at = None

            if (
                not self._capture_target_reached.is_set()
                and self._cumulative_speech_secs >= CLONE_SCRIPT_TARGET_SECS
            ):
                logger.info(
                    "clone-script read target reached (~%.1fs cumulative, %.1fs buffered)",
                    self._cumulative_speech_secs,
                    tee.buffered_secs,
                )
                self._capture_target_reached.set()

            # Push the updated capture-seconds attribute so the frontend read meter
            # advances. Cheap: one attribute write per user-turn boundary.
            task = asyncio.create_task(
                self._set_clone_attrs(
                    capture_secs=f"{self._cumulative_speech_secs:.2f}"
                )
            )
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)

        session.on("user_state_changed", _on_user_state_changed)

    async def _run_clone_upload(self, frames, vad_model) -> str:
        """Trim → upload the buffered frames to Fish, returning the new model_id.
        Pure network/CPU work with NO speaking.

        We intentionally do NOT compute a reference transcript: AssemblyAI's
        streaming STT runs at ~1x realtime, so transcribing ~15s of audio added
        ~15-20s of latency and dominated the clone time (pushing the whole flow
        past the frontend's agent-connect timeout). Fish clones fine from audio
        alone with train_mode=fast, and skipping the transcript is also more
        robust to mis-reads (no text/audio mismatch)."""
        if vad_model is not None:
            try:
                frames = await vad_trim_frames(vad_model, frames)
            except Exception:
                logger.exception("VAD trim failed; using raw frames")

        wav_bytes = frames_to_wav(frames)
        model_id = await create_voice_clone(
            os.environ["FISH_API_KEY"],
            wav_bytes,
            title="livekit-demo-clone",
            transcript=None,
        )
        logger.info("created cloned voice id=%s", model_id)
        return model_id

    async def run_clone_first(self, session: AgentSession, ctx: JobContext) -> None:
        """Clone-first session flow: prompt the user to read the on-screen script,
        capture ~15s of it, build the clone, switch the TTS into it, and only then
        kick off the real (expressive) conversation. Falls back to the starting preset
        voice if the user reads too little or the clone fails.

        All speech in the read/clone window is driven from here; user turns are
        suppressed via `_reading_script` so the agent doesn't talk over the reading."""
        self.install_capture(session)
        self._reading_script = True
        self._heard_final = ""
        self._heard_interim = ""
        self._last_heard_pub = 0.0

        # Stream the user's live STT into `clone.heard` so the read card can
        # highlight words as they're spoken. Throttled to ~4 Hz (always on final).
        def _on_user_transcript(ev) -> None:
            if not self._reading_script:
                return
            if ev.is_final:
                self._heard_final = f"{self._heard_final} {ev.transcript}".strip()
                self._heard_interim = ""
            else:
                self._heard_interim = ev.transcript
            now = time.monotonic()
            if ev.is_final or now - self._last_heard_pub >= 0.35:
                self._last_heard_pub = now
                heard = f"{self._heard_final} {self._heard_interim}".strip()
                t = asyncio.create_task(self._set_clone_attrs(heard=heard))
                self._bg_tasks.add(t)
                t.add_done_callback(self._bg_tasks.discard)

        session.on("user_input_transcribed", _on_user_transcript)

        # Publish the script + reset highlight state for the on-screen card, then
        # connect so the mic is live, then prompt the read (in the starting preset voice).
        await self._set_clone_attrs(script=CLONE_SCRIPT, heard="", capture_secs="0.00")
        await self._set_clone_state("prompt")
        await ctx.connect()
        with contextlib.suppress(RuntimeError):
            session.say(
                CLONE_PROMPT_LINE, add_to_chat_ctx=False, allow_interruptions=False
            )

        # Wait for enough of the script to be read (or time out).
        try:
            await asyncio.wait_for(
                self._capture_target_reached.wait(), timeout=CLONE_SCRIPT_TIMEOUT_SECS
            )
        except asyncio.TimeoutError:
            logger.info(
                "clone-script read timed out at ~%.1fs cumulative speech",
                self._cumulative_speech_secs,
            )

        # Under-read / no audio → fall back to the starting preset voice.
        if (
            self._capture is None
            or not self._capture.frames
            or self._cumulative_speech_secs < CLONE_MIN_SECS
        ):
            logger.warning(
                "clone-first under-read (~%.1fs); falling back to preset voice",
                self._cumulative_speech_secs,
            )
            await self._set_clone_state("idle")
            self._reading_script = False
            self._safe_generate_reply(session, CLONE_FALLBACK_GREETING)
            return

        # Enough audio: build the clone while a short ack fills the upload window.
        await self._set_clone_state("cloning")
        upload = asyncio.create_task(
            self._run_clone_upload(list(self._capture.frames), session.vad)
        )
        ack = None
        with contextlib.suppress(RuntimeError):
            ack = session.say(
                random.choice(CLONE_BUILD_ACKS),
                add_to_chat_ctx=False,
                allow_interruptions=False,
            )

        try:
            model_id = await upload
        except Exception as e:
            logger.exception("clone-first upload failed; falling back to preset voice")
            await self._set_clone_state("idle")
            self._reading_script = False
            if ack is not None:
                with contextlib.suppress(Exception):
                    await ack.wait_for_playout()
            self._safe_generate_reply(
                session,
                f"{CLONE_FALLBACK_GREETING} (Internal note: clone error was {e}.)",
            )
            return

        self._cloned_voice_id = model_id
        await self._set_clone_state("ready")

        # Let the ack finish in the starting voice before the cloned-voice reveal.
        if ack is not None:
            with contextlib.suppress(Exception):
                await ack.wait_for_playout()

        tts = session.tts
        if isinstance(tts, fishaudio.TTS):
            tts.update_options(voice_id=model_id)
            logger.info("switched TTS to cloned voice id=%s", model_id)
            await self._set_clone_state("playing")
        else:
            logger.warning("session TTS is not Fish Audio; cannot switch to clone")

        self._cloned = True
        await self.update_instructions(build_instructions(cloned=True))
        # Stop suppressing replies and reveal the clone — first line is in their voice.
        self._reading_script = False
        self._safe_generate_reply(session, CLONE_REVEAL_GREETING)

    async def apply_mode(self, session: AgentSession, mode: str) -> None:
        """Switch the speaking register, driven by the user's on-screen toggle.

        Swaps the agent's expressive preset (the framework re-resolves it on the next
        reply), echoes the new register to the frontend via `style.mode`, and — unless
        we're mid clone-read — fires a short demo line so the user immediately hears the
        new voice. Idempotent: a redundant switch still re-asserts the preset and attr.
        """
        if mode not in _PRESET_FOR_MODE:
            logger.warning("ignoring unknown mode: %r", mode)
            return
        changed = mode != self._mode
        self._mode = mode
        self.update_expressive(_expressive_for(mode))
        await self._set_style_attrs(mode=mode)
        logger.info("mode switched -> %s", mode)
        if changed and not self._reading_script:
            self._safe_generate_reply(
                session,
                f"The user just switched you to {mode} mode using the on-screen toggle. "
                f"In ONE short, natural line, react and let them hear your {mode} voice, "
                "then carry the conversation on.",
            )

    async def _mood_tee(self, text: AsyncIterable[str]) -> AsyncIterable[str]:
        """Forward the TTS text stream unchanged, then kick off the cosmetic mood
        classification once the text finishes streaming. That happens when the LLM has
        finished producing the line — much earlier than `conversation_item_added`,
        which only lands after audio playout ends — so the ring updates as the agent
        starts speaking, not after it stops."""
        buf: list[str] = []
        async for chunk in text:
            buf.append(chunk)
            yield chunk
        self._schedule_mood("".join(buf))

    def _schedule_mood(self, raw_text: str) -> None:
        """(Re)launch mood classification for a freshly spoken line. Only the latest
        line matters, so any still-running classification is cancelled. No-ops during
        the clone-script read."""
        if self._reading_script:
            return
        text = _MARKUP_RE.sub("", raw_text or "").strip()
        if not text:
            return
        if self._mood_task is not None and not self._mood_task.done():
            self._mood_task.cancel()
        self._mood_task = asyncio.create_task(self._classify_mood(text))
        self._bg_tasks.add(self._mood_task)
        self._mood_task.add_done_callback(self._bg_tasks.discard)

    async def _classify_mood(self, text: str) -> None:
        """Ask the cheap mood LLM what emotion `text` conveys and push the result to
        the on-screen ring (`style.mood`/`style.color`). Best-effort and isolated:
        failures are logged, never surfaced, and never touch the agent's delivery."""
        try:
            resp = await self._mood_client.chat.completions.create(
                model=MOOD_MODEL,
                messages=[
                    {"role": "system", "content": _MOOD_SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
                response_format={"type": "json_object"},
                max_tokens=24,
                temperature=0,
            )
            data = json.loads(resp.choices[0].message.content or "{}")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("mood classification failed")
            return
        mood = str(data.get("mood", "")).strip().lower()[:24]
        color = str(data.get("color", "")).strip().lower()
        if color not in _RING_COLORS:
            color = DEFAULT_MODE_COLOR.get(self._mode, "green")
        if not mood:
            return
        logger.info("mood ring: mood=%s color=%s", mood, color)
        await self._set_style_attrs(mood=mood, color=color)

    def llm_node(self, chat_ctx, tools, model_settings):
        # Log the full per-turn prompt (instructions + injected expressive guidance +
        # history) so the casual prompt can be tuned against exactly what the LLM sees.
        if _LOG_LLM_PROMPT:
            try:
                logger.info(
                    "\n╔═ LLM PROMPT (%d items) ═══\n%s\n╚═ end prompt ═════════════",
                    len(chat_ctx.items),
                    _format_chat_ctx(chat_ctx),
                )
            except Exception:  # logging must never break generation
                logger.exception("LLM prompt logging failed")
        return Agent.default.llm_node(self, chat_ctx, tools, model_settings)

    def tts_node(self, text, model_settings):
        # Tee the raw text (pre-phoneme, with markup intact) to drive the mood ring as
        # early as possible — classification fires the moment the line finishes
        # streaming from the LLM, not after playout.
        text = self._mood_tee(text)
        # Fix the "LiveKit" pronunciation in the audio only (transcript is unaffected).
        stream = _fix_tts_pronunciation(text, LIVEKIT_PHONEME)
        if _LOG_TTS_PAYLOAD:
            stream = _log_tts_payload(stream)
        return Agent.default.tts_node(self, stream, model_settings)


# Memory: Render's 512MB Starter tier can't fit multiple PROCESS-mode job workers
# (each carries a full copy of the 1.6.2 runtime + silero VAD, ~150-250MB; the main
# worker + an idle + an active job blow past 512MB → OOM). Run jobs as THREADS in a
# single process instead, so the runtime/VAD load once and are shared. Lower
# concurrency on a small box anyway. Both knobs are env-overridable; flip
# JOB_EXECUTOR=process (+ a bigger plan) if you need process isolation.
_EXECUTOR = (
    JobExecutorType.THREAD
    if os.getenv("JOB_EXECUTOR", "thread").lower() == "thread"
    else JobExecutorType.PROCESS
)
server = AgentServer(
    job_executor_type=_EXECUTOR,
    num_idle_processes=int(os.getenv("NUM_IDLE_PROCESSES", "1")),
)


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name=AGENT_NAME)
async def my_agent(ctx: JobContext):
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    # Per-session config from the frontend, delivered as agent dispatch metadata:
    #   preset voice -> {"voice": "<voice_id>"};  clone-first -> {"clone": true}
    raw_meta = ctx.job.metadata or ""
    try:
        meta = json.loads(raw_meta) if raw_meta else {}
        if not isinstance(meta, dict):
            meta = {}
    except Exception:
        logger.warning("could not parse job metadata: %r", raw_meta)
        meta = {}

    want_clone = meta.get("clone") is True
    requested_voice = meta.get("voice")
    start_voice = (
        requested_voice if requested_voice in PRESET_VOICES else DEFAULT_VOICE_ID
    )
    logger.info(
        "session config: clone=%s start_voice=%s (requested=%s)",
        want_clone,
        start_voice,
        requested_voice,
    )

    session = AgentSession(
        stt=assemblyai.STT(),
        tts=fishaudio.TTS(
            model="s2.1-pro",
            voice_id=start_voice,
            latency_mode="low",
            # PCM, not the default WAV. With streamed LLM output, the WAV-container
            # decode path produces an audible first-word "crackle" over WebRTC that
            # the raw-PCM path doesn't (a single continuous session.say never
            # crackles, only token-streamed generate_reply). Fish's bytes are clean
            # either way — raw PCM just avoids the container/decode path. See the
            # upstream investigation in livekit/agents.
            output_format="pcm",
        ),
        # Turn detection falls back to silero VAD — keeps the agent footprint
        # small enough for Render's 512MB Starter worker.
        vad=ctx.proc.userdata["vad"],
        # preemptive_generation is intentionally OFF. It starts generating the reply
        # while the user is still talking — before on_user_turn_completed runs — so the
        # StopResponse we raise there to stay silent during the clone-script read would
        # land too late to suppress the reply. Keep it off so the gate is reliable.
    )

    assistant = Assistant()
    assistant._job_ctx = ctx

    async def _cleanup_cloned_voice(_reason: str) -> None:
        model_id = assistant._cloned_voice_id
        if model_id is None:
            return
        api_key = os.environ.get("FISH_API_KEY")
        if not api_key:
            return
        await delete_voice_clone(api_key, model_id)

    ctx.add_shutdown_callback(_cleanup_cloned_voice)

    # Start the session, which initializes the voice pipeline and warms up the models.
    await session.start(
        agent=assistant,
        room=ctx.room,
    )

    # Track the live agent state so our attribute writes never drop `lk.agent.state`
    # (session.start has already moved it to "listening").
    assistant._agent_state = session.agent_state
    session.on("agent_state_changed", assistant._on_agent_state_changed)

    # (The cosmetic mood ring is driven from `tts_node` via `_mood_tee`, so it updates
    # as the agent starts speaking rather than after the turn is committed.)

    # Register switching is user-driven: the frontend toggle calls this RPC, which
    # swaps the expressive preset and triggers a short demo line in the new register.
    @ctx.room.local_participant.register_rpc_method("set_mode")
    async def _handle_set_mode(data) -> str:
        mode = (data.payload or "").strip().lower()
        if mode not in _PRESET_FOR_MODE:
            return json.dumps({"ok": False, "error": f"unknown mode {mode!r}"})
        await assistant.apply_mode(session, mode)
        return json.dumps({"ok": True, "mode": mode})

    # Seed the mood-ring indicator with the resting starting-mode state (both paths).
    await assistant._set_style_attrs(
        mode=assistant._mode,
        mood="",
        color=DEFAULT_MODE_COLOR[assistant._mode],
    )

    if want_clone:
        # Clone-first: read the script, clone, switch voice, then converse. Connects
        # to the room itself (the mic must be live while the user reads).
        await assistant.run_clone_first(session, ctx)
    else:
        # Preset voice: open straight into the expressive conversation.
        session.generate_reply(instructions=PRESET_GREETING)
        await ctx.connect()


if __name__ == "__main__":
    cli.run_app(server)
