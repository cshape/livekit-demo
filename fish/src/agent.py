import asyncio
import contextlib
import json
import logging
import os
import random
import re
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
    RoomInputOptions,
    StopResponse,
    TurnHandlingOptions,
    cli,
)
from livekit.agents.voice import presets
from livekit.plugins import deepgram, fishaudio, silero

from llm import build_llm, build_mood_client
from voice_clone import (
    PassthroughCaptureAudioInput,
    create_designed_voice,
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

# Hard cap on buffered audio that gets uploaded to Fish. The clone read window is
# CLONE_READ_SECS (15s) plus whatever the user speaks during the prompt line, so cap
# well above that — every buffered second is memory held while the upload builds.
CAPTURE_MAX_SECS = 30.0

# --- Voice selection ---------------------------------------------------------
# The 4 preset Fish Audio voices offered on the landing page. The frontend sends
# the chosen voice_id in the agent metadata; we validate it against this set and
# fall back to DEFAULT_VOICE_ID for anything unexpected (incl. clone sessions,
# which start in this voice while the user reads the clone script).
PRESET_VOICES: dict[str, str] = {
    "0e24ff9936d34df4bddce26398cf1311": "Maren (American F)",
    "747b05c0add940baa95270cf68c0cc2e": "Stellan (American M)",
    "41db1fc3c3624332bec9997ff3d3d353": "Maeve (British F)",
    "9a3a69c63dbc4774ac41b03945229dc8": "Alistair (British M)",
}
DEFAULT_VOICE_ID = "0e24ff9936d34df4bddce26398cf1311"  # Maren (American F)

# --- Clone-first flow --------------------------------------------------------
# When the user picks "clone your voice" on the landing page, they read this
# script aloud at the start of the call; we capture it, clone, and switch into
# their voice before the real conversation begins. ~50 words — more than fits in
# the CLONE_READ_SECS window, so nobody runs out of script mid-countdown. No
# bracket markers — the user reads it verbatim.
CLONE_SCRIPT = (
    "The quick morning light spread over the harbor as the boats headed out to sea. "
    "Honestly, there's nothing like a fresh cup of coffee and a clear blue sky to get "
    "the day going. I could talk about this stuff for hours — but let's hear how it sounds."
)
# Fixed read window: once the read prompt finishes playing we publish
# clone.state="reading", wait exactly this long, and clone whatever was captured.
# The frontend mirrors the same countdown on the script card. Purely time-based so
# a mis-read, a skipped line, or off-script chatter still clones fine.
CLONE_READ_SECS = 15.0
# Minimum captured speech (per the capture tee's buffered seconds) to attempt a
# clone; under this we fall back to the preset voice.
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


# Opt-in debug logging (off by default; set the env var to 1 to enable). LOG_TTS_PAYLOAD
# logs the per-utterance text Fish synthesizes; LOG_LLM_PROMPT logs the full per-turn LLM
# prompt — handy for tuning the expressive prompts, but too verbose (and prompt-leaking)
# to ship on by default.
_LOG_TTS_PAYLOAD = os.getenv("LOG_TTS_PAYLOAD", "0") != "0"
_LOG_LLM_PROMPT = os.getenv("LOG_LLM_PROMPT", "0") != "0"


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
You are the voice of a live demo of Fish Audio's expressive text to speech. The whole point is to show off speech that sounds genuinely human and emotionally alive — so let real feeling into your delivery: react, vary your energy, and never sound flat or read-aloud.

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
# the agent process, on its own cheap model so it's fast and doesn't compete with the
# conversation LLM. Provider follows the same LLM_BASE_URL switch as the agent LLM (see
# llm.build_mood_client); default is OpenAI gpt-4.1-mini.
DEFAULT_MOOD_MODEL = "gpt-4.1-mini"
_RING_COLORS = {"gray", "amber", "green", "blue", "violet"}
_MOOD_SYSTEM_PROMPT = (
    "You are a mood ring for a voice assistant. You are given the single line the "
    "assistant just spoke. Judge the EMOTION its delivery conveys and reply with ONLY a "
    "compact JSON object, no prose, no markdown:\n"
    '{"mood": "<one lowercase word>", "color": "<gray|amber|green|blue|violet>"}\n'
    "mood: ONE vivid, specific word for the feeling. Aim for subtle variety turn to turn "
    "and don't keep defaulting to the same generic word (e.g. 'playful' or 'happy'); reach "
    "for a fresh, precise shade instead (cheerful, curious, tickled, breezy, wistful, "
    "earnest, mischievous, wry, tender, buoyant, wistful, chuffed, gleeful, ...). Get "
    "creative as long as the word genuinely fits the line. color picks the closest ring: "
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


DESIGNED_VOICE_NOTE = (
    "VOICE NOTE: you are speaking in a voice the user just DESIGNED from a short written "
    "description at the start of this call. It's a quick, temporary demo voice — it's deleted "
    "when the call ends. If they want to design and keep production-grade voices, point them to "
    "fish dot audio (say it as the three words 'fish dot audio'; a clickable link appears in the "
    "transcript). Don't dwell on the design process — keep the focus on expressive speech, your "
    "modes, and moods."
)


def build_instructions(cloned: bool = False, designed: bool = False) -> str:
    """Assemble the system prompt: CORE plus, for clone/design sessions, a slim note.

    Register and mood no longer live in the instructions — they're carried by the
    expressive preset (see `_expressive_for`). When `cloned` (or `designed`) is set, a
    note is appended so the agent knows whose voice it's speaking in and keeps the fish
    dot audio CTA. Preset-voice sessions never include any cloning/design text.
    """
    parts = [CORE_INSTRUCTIONS]
    if cloned:
        parts.append(CLONED_VOICE_NOTE)
    if designed:
        parts.append(DESIGNED_VOICE_NOTE)
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

# --- Design-first flow -------------------------------------------------------
# When the user picks "design a voice" on the landing page, they type a description
# of the voice they want; it rides the agent metadata as {"design": "<text>"}. The
# worker starts building the voice (voice-design API -> create-model) the moment the
# job starts — in parallel with session start and room connect — then greets in it.
# Fish's API caps the instruction at 2000 chars; clamp whatever the frontend sends.
DESIGN_INSTRUCTION_MAX_CHARS = 2000
# Design generation + model creation budget; past this we fall back to the preset.
DESIGN_TIMEOUT_SECS = 75.0


# Instructions for the ack spoken (in the starting preset voice) while the designed
# voice builds. LLM-generated rather than canned so it can make a light, specific
# comment on what the user actually asked for. The LLM round trip runs while the
# design API calls are already in flight, so it adds no wall-clock to the flow.
def design_ack_instructions(description: str) -> str:
    return (
        "The user just asked you to DESIGN a brand-new voice from this description: "
        f'"{description}". In ONE short, warm sentence: react with a light, playful '
        "comment on their choice, and tell them to hang on just a moment while you "
        "put it together. Don't greet them yet, don't ask any questions, and don't "
        "mention modes, toggles, or the technical process."
    )


# Greeting after a successful design — first line is already in the designed voice.
DESIGN_REVEAL_GREETING = (
    "You are NOW speaking in a brand-new voice just designed from the user's own written "
    "description. In one or two short sentences: warmly greet them in this new voice, point out "
    "that this is the voice they designed, then ask them how it sounds. Don't mention modes or "
    "toggles, and don't over-explain the design process."
)
# Greeting when the design failed — stays in the starting preset voice.
DESIGN_FALLBACK_GREETING = (
    "Designing the custom voice didn't go through, so you're staying in your current voice. In "
    "one or two short sentences: lightly apologize that their designed voice didn't come "
    "together this time, give a warm hello, and ask a curious question like what brought them "
    "here. Don't mention modes or toggles, and don't dwell on the failure."
)


def build_tts(voice_id: str):
    return fishaudio.TTS(
        model="s2.1-pro",
        voice_id=voice_id,
        latency_mode="low",
        # PCM, not the default WAV — avoids the WAV-container decode path.
        output_format="pcm",
        # No prebuffer/prewarm config here on purpose: the plugin handles both by
        # default. It reuses one /v1/tts/live socket per session (pre-warmed via the
        # framework's prewarm() hook, so the first reply skips the ~330ms handshake)
        # and, by default (prebuffer_chunks=2), waits for Fish's second chunk before
        # starting playout — a built-in stopgap for the cold-start underrun that
        # caused the first-utterance crackle over WebRTC, until Fish's inference emits
        # a smoother first/second chunk (then the plugin default flips to start on
        # chunk 1).
    )


class Assistant(Agent):
    def __init__(self) -> None:
        # The register starts casual; the user flips it at runtime via the on-screen
        # toggle (set_mode RPC -> apply_mode), which swaps the expressive preset.
        self._mode: str = "casual"
        super().__init__(
            # Provider chosen by env (see llm.build_llm): our own OpenAI-compatible
            # endpoint when LLM_BASE_URL is set, else direct OpenAI gpt-5.1 (which
            # follows the expressive markup well). The mood classifier below stays on
            # direct OpenAI regardless.
            llm=build_llm(default_openai_model="gpt-5.1"),
            instructions=build_instructions(),
            # Drives the SDK expressive pipeline: injects the register's markup
            # authoring guidance per turn and converts/strips the tags. Per-Agent
            # `expressive` overrides the session; apply_mode mutates it via
            # update_expressive so a register change takes effect next turn.
            expressive=_expressive_for(self._mode),
        )
        # Cheap, separate LLM that reads each spoken line and classifies the mood it
        # conveys for the on-screen ring. Independent of the conversation LLM/prompt.
        self._mood_client, self._mood_model = build_mood_client(
            default_openai_model=DEFAULT_MOOD_MODEL
        )
        self._mood_task: asyncio.Task[None] | None = None
        # Recent mood labels fed back into the classifier so it varies its word choice
        # turn to turn instead of getting stuck on one (e.g. "playful").
        self._recent_moods: list[str] = []
        # Temporary Fish models built for this session (clone and/or designed voice);
        # all deleted by the shutdown callback.
        self._ephemeral_voice_ids: list[str] = []
        self._cloned: bool = False
        self._job_ctx: JobContext | None = None
        self._capture: PassthroughCaptureAudioInput | None = None
        # While the user reads the clone script (or the designed voice is building)
        # we suppress agent replies (on_user_turn_completed raises StopResponse) so
        # the setup flow drives all speech.
        self._suppress_replies: bool = False
        # Non-destructive attribute writes: the rtc `set_attributes` clobbers keys
        # you don't pass, so we re-send our own attrs + the live `lk.agent.state`
        # on every write. Without this, our clone/design/style writes race the SDK's
        # own state writes and can drop `lk.agent.state`, which trips the frontend's
        # "agent did not finish initializing" failure. `_agent_state` is kept fresh
        # from `agent_state_changed` (wired in `my_agent`).
        self._agent_state: str = "initializing"
        self._own_attrs: dict[str, str] = {}
        # Serialize attribute writes: a mode switch fires several at once (apply_mode's
        # style.mode write + the demo line's mood-classifier write) which would otherwise
        # interleave read-modify-write and could transiently drop keys.
        self._attrs_lock: asyncio.Lock = asyncio.Lock()
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
        async with self._attrs_lock:
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

    async def _set_design_state(self, state: str) -> None:
        """Push the `design.state` attribute that drives the on-screen design card."""
        await self._push_attrs({"design.state": state})

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
            logger.info("session no longer running; skipping queued reply")

    async def on_user_turn_completed(
        self, turn_ctx: ChatContext, new_message: ChatMessage
    ) -> None:
        """While the user is reading the clone script (or the designed voice is still
        building), suppress the agent's reply so it doesn't talk over the setup flow —
        the controller drives all speech in that window. Otherwise a no-op."""
        if self._suppress_replies:
            raise StopResponse()

    async def on_user_turn_exceeded(self, ev) -> None:
        """Default behavior cuts in with a reply when the user speaks too long; while
        reading the (long) clone script we must stay silent, so skip it then."""
        if self._suppress_replies:
            return
        await super().on_user_turn_exceeded(ev)

    def install_capture(self, session: AgentSession) -> None:
        """Tee session.input.audio so we silently buffer the user's voice while they
        speak. The tee's buffered_secs is the "did they read enough" signal."""
        original = session.input.audio
        if original is None:
            logger.warning("session has no audio input; voice-clone capture disabled")
            return
        tee = PassthroughCaptureAudioInput(source=original, max_secs=CAPTURE_MAX_SECS)
        session.input.audio = tee
        self._capture = tee

        def _on_user_state_changed(ev) -> None:
            tee.recording = ev.new_state == "speaking"

        session.on("user_state_changed", _on_user_state_changed)

    async def _run_clone_upload(self, frames, vad_model) -> str:
        """Trim → upload the buffered frames to Fish, returning the new model_id.
        Pure network/CPU work with NO speaking.

        We intentionally do NOT compute a reference transcript: transcribing the
        ~15s read at streaming (~1x realtime) speed added ~15-20s of latency and
        dominated the clone time (pushing the whole flow past the frontend's
        agent-connect timeout). Fish clones fine from audio alone with
        train_mode=fast, and skipping the transcript is also more robust to
        mis-reads (no text/audio mismatch)."""
        if vad_model is not None:
            try:
                frames = await vad_trim_frames(vad_model, frames)
            except Exception:
                logger.exception("VAD trim failed; using raw frames")

        wav_bytes = frames_to_wav(frames)
        # Free the raw audio frames now (this is the only remaining reference, since the
        # capture tee was cleared on hand-off) so they don't coexist with the WAV bytes
        # and the multipart upload body in memory.
        del frames
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
        capture a fixed CLONE_READ_SECS window of it, build the clone, switch the TTS
        into it, and only then kick off the real (expressive) conversation. Falls back
        to the starting preset voice if too little was captured or the clone fails.

        All speech in the read/clone window is driven from here; user turns are
        suppressed via `_suppress_replies` so the agent doesn't talk over the reading."""
        self.install_capture(session)
        self._suppress_replies = True

        # Publish the script for the on-screen card, connect so the mic is live, then
        # prompt the read (in the starting preset voice) and let it finish playing.
        await self._set_clone_attrs(
            script=CLONE_SCRIPT, read_secs=f"{CLONE_READ_SECS:.0f}"
        )
        await self._set_clone_state("prompt")
        await ctx.connect()
        prompt = None
        with contextlib.suppress(RuntimeError):
            prompt = session.say(
                CLONE_PROMPT_LINE, add_to_chat_ctx=False, allow_interruptions=False
            )
        if prompt is not None:
            with contextlib.suppress(Exception):
                await prompt.wait_for_playout()

        # Fixed read window. The frontend starts its countdown when it sees state
        # flip to "reading"; when the window ends we clone whatever was captured.
        # (The capture tee buffers whenever the user is speaking — installed before
        # connect — so anyone who started reading during the prompt line is captured.)
        await self._set_clone_state("reading")
        await asyncio.sleep(CLONE_READ_SECS)

        captured_secs = self._capture.buffered_secs if self._capture else 0.0
        logger.info(
            "clone read window closed (%.1fs of speech captured)", captured_secs
        )

        # Under-read / no audio → fall back to the starting preset voice.
        if self._capture is None or captured_secs < CLONE_MIN_SECS:
            logger.warning(
                "clone-first under-read (%.1fs); falling back to preset voice",
                captured_secs,
            )
            await self._set_clone_state("idle")
            self._suppress_replies = False
            self._safe_generate_reply(session, CLONE_FALLBACK_GREETING)
            return

        # Enough audio: build the clone while a short ack fills the upload window.
        await self._set_clone_state("cloning")
        # Hand the buffered frames to the upload task and release the capture tee's hold
        # immediately, so we don't keep a second copy of the recording alive during the
        # memory-heavy WAV build + upload on the 512MB worker.
        frames = self._capture.frames
        self._capture.frames = []
        self._capture.recording = False
        upload = asyncio.create_task(self._run_clone_upload(frames, session.vad))
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
            self._suppress_replies = False
            if ack is not None:
                with contextlib.suppress(Exception):
                    await ack.wait_for_playout()
            self._safe_generate_reply(
                session,
                f"{CLONE_FALLBACK_GREETING} (Internal note: clone error was {e}.)",
            )
            return

        self._ephemeral_voice_ids.append(model_id)
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
        self._suppress_replies = False
        self._safe_generate_reply(session, CLONE_REVEAL_GREETING)

    async def run_design_first(
        self,
        session: AgentSession,
        ctx: JobContext,
        design_task: "asyncio.Task[str]",
        instruction: str,
    ) -> None:
        """Design-first session flow: the voice build (`design_task`, kicked off at
        job start so it overlaps session/room setup) runs while an LLM-generated ack
        (a light comment on the user's description) plays in the starting preset
        voice; when the model is ready we switch the TTS into it and greet in the
        designed voice. Falls back to the preset voice on failure.

        Replies are suppressed until the swap so a user who talks during the build
        doesn't trigger a reply in the wrong (preset) voice."""
        self._suppress_replies = True
        await self._set_design_state("designing")
        await ctx.connect()
        ack = None
        with contextlib.suppress(RuntimeError):
            ack = session.generate_reply(
                instructions=design_ack_instructions(instruction),
                allow_interruptions=False,
            )

        try:
            model_id = await asyncio.wait_for(design_task, timeout=DESIGN_TIMEOUT_SECS)
        except Exception:
            logger.exception("voice design failed; falling back to preset voice")
            await self._set_design_state("failed")
            self._suppress_replies = False
            if ack is not None:
                with contextlib.suppress(Exception):
                    await ack.wait_for_playout()
            self._safe_generate_reply(session, DESIGN_FALLBACK_GREETING)
            return

        # (The model id is recorded for shutdown cleanup by the done-callback wired
        # in my_agent, so it's deleted even if this coroutine dies before here.)

        # Let the ack finish in the starting voice before the designed-voice reveal.
        if ack is not None:
            with contextlib.suppress(Exception):
                await ack.wait_for_playout()

        tts = session.tts
        if isinstance(tts, fishaudio.TTS):
            tts.update_options(voice_id=model_id)
            logger.info("switched TTS to designed voice id=%s", model_id)
        else:
            logger.warning("session TTS is not Fish Audio; cannot switch to design")

        await self._set_design_state("ready")
        await self.update_instructions(build_instructions(designed=True))
        self._suppress_replies = False
        self._safe_generate_reply(session, DESIGN_REVEAL_GREETING)

    async def apply_mode(self, session: AgentSession, mode: str) -> None:
        """Switch the speaking register, driven by the user's on-screen toggle.

        Swaps the agent's expressive preset (the framework re-resolves it on the next
        reply), echoes the new register to the frontend via `style.mode`, and — unless
        we're mid clone-read — reacts in the new voice. Idempotent: a redundant switch
        still re-asserts the preset and attr.

        If the agent is mid-utterance when the user flips the toggle, we CANCEL the
        current line (stop playback) and immediately respond in the new register, so the
        switch feels instant rather than waiting for the old line to finish.
        """
        if mode not in _PRESET_FOR_MODE:
            logger.warning("ignoring unknown mode: %r", mode)
            return
        changed = mode != self._mode
        self._mode = mode
        self.update_expressive(_expressive_for(mode))
        await self._set_style_attrs(mode=mode)
        logger.info("mode switched -> %s", mode)
        if not changed or self._suppress_replies:
            return
        # Cut off whatever the agent is currently saying so the new tone lands right
        # away. interrupt() is a no-op when nothing is speaking; force so an in-progress
        # (interruptible) line always stops.
        with contextlib.suppress(Exception):
            await session.interrupt(force=True)
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
        the clone/design setup window."""
        if self._suppress_replies:
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
        the on-screen ring (`style.mood`/`style.color`). Feeds the recent labels back in
        and runs warm so the word shifts subtly each turn instead of sticking on one.
        Best-effort and isolated: failures are logged, never surfaced, and never touch
        the agent's delivery."""
        user_content = text
        if self._recent_moods:
            user_content += (
                "\n\n[Recent mood words already used (most recent last): "
                f"{', '.join(self._recent_moods)}. Do NOT reuse any of these; pick a "
                "different, fresh word that still genuinely fits this line.]"
            )
        try:
            resp = await self._mood_client.chat.completions.create(
                model=self._mood_model,
                messages=[
                    {"role": "system", "content": _MOOD_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                response_format={"type": "json_object"},
                max_tokens=24,
                temperature=0.9,
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
        # Remember the last few labels so the next turn avoids repeating them.
        self._recent_moods.append(mood)
        self._recent_moods = self._recent_moods[-5:]
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
    design_instruction = meta.get("design")
    if isinstance(design_instruction, str):
        design_instruction = design_instruction.strip()[:DESIGN_INSTRUCTION_MAX_CHARS]
    if not design_instruction or want_clone:
        design_instruction = None
    logger.info(
        "session config: clone=%s design=%s start_voice=%s (requested=%s)",
        want_clone,
        bool(design_instruction),
        start_voice,
        requested_voice,
    )

    # Kick off the voice design NOW — the API round trips (design + create-model)
    # overlap the whole session/room setup instead of starting after connect.
    design_task: asyncio.Task[str] | None = None
    if design_instruction:
        design_task = asyncio.create_task(
            create_designed_voice(os.environ["FISH_API_KEY"], design_instruction)
        )

    session = AgentSession(
        # Deepgram Flux: a conversational STT model that does turn-taking itself
        # (native EndOfTurn / EagerEndOfTurn events over /v2/listen), so the STT — not
        # a separate turn-detector model or VAD — decides when the user is done.
        # eot_threshold is the end-of-turn confidence needed to finish a turn;
        # eot_timeout_ms forces a turn end after that much trailing silence;
        # eager_eot_threshold is the lower confidence at which Flux fires an early
        # "probably done" signal that drives preemptive generation (see turn_handling
        # below). Values match the fish-bare-agent Flux setup.
        stt=deepgram.STTv2(
            model="flux-general-en",
            eot_threshold=0.7,
            eot_timeout_ms=3000,
            eager_eot_threshold=0.5,
        ),
        tts=build_tts(start_voice),
        # VAD is kept only for interruption / barge-in handling now (Flux owns turn
        # detection). Loaded once in prewarm and shared across thread jobs.
        vad=ctx.proc.userdata["vad"],
        turn_handling=TurnHandlingOptions(
            # Let Flux's EndOfTurn drive turns instead of VAD or a turn-detector model.
            turn_detection="stt",
            # No added floor after Flux's end-of-speech (min_delay is additive in STT
            # mode); Flux's own eot_threshold / eot_timeout_ms already gate the turn.
            # max_delay stays at its 3.0s default, matching eot_timeout_ms so the SDK
            # never terminates a turn ahead of Flux.
            endpointing={"min_delay": 0.0},
            # Preemptive generation, enabled for EVERY session. Flux's EagerEndOfTurn
            # (eager_eot_threshold) emits a PREFLIGHT transcript while the user is likely
            # still finishing; the SDK then speculatively runs BOTH the LLM and — because
            # preemptive_tts is on — Fish TTS, buffering the audio. On the real EndOfTurn
            # it just plays the already-synthesized reply, so time-to-first-audio is
            # near-zero. preemptive_tts is what matches fish-bare-agent's latency (its
            # engine also starts LLM+TTS on EagerEndOfTurn); without it only the LLM runs
            # early and Fish's time-to-first-audio is still paid after the turn confirms.
            # Safe for the clone/design flows: the speculative reply (audio included) is
            # only PLAYED when the speech handle is scheduled, which happens AFTER
            # on_user_turn_completed — so the StopResponse gate we raise there still
            # suppresses it during the read/build window, and reads longer than
            # max_speech_duration (10s) skip preemption entirely. The trade-off is wasted
            # Fish synthesis when a speculative turn is abandoned (TurnResumed), which is
            # the same bet bare-agent makes.
            preemptive_generation={"enabled": True, "preemptive_tts": True},
        ),
    )

    assistant = Assistant()
    assistant._job_ctx = ctx

    # Record the designed model id for shutdown cleanup the moment the build task
    # finishes — even if the session dies before run_design_first can use it.
    if design_task is not None:

        def _record_design_model(t: "asyncio.Task[str]") -> None:
            if t.cancelled() or t.exception() is not None:
                return
            assistant._ephemeral_voice_ids.append(t.result())

        design_task.add_done_callback(_record_design_model)

    async def _cleanup_ephemeral_voices(_reason: str) -> None:
        api_key = os.environ.get("FISH_API_KEY")
        if not api_key:
            return
        for model_id in assistant._ephemeral_voice_ids:
            await delete_voice_clone(api_key, model_id)

    ctx.add_shutdown_callback(_cleanup_ephemeral_voices)

    # Start the session, which initializes the voice pipeline and warms up the models.
    await session.start(
        agent=assistant,
        room=ctx.room,
        # Don't tear the agent session down the instant the user's connection blips —
        # give a brief reconnect a chance (the frontend stays on the call too).
        room_input_options=RoomInputOptions(close_on_disconnect=False),
    )

    # Track the live agent state so our attribute writes never drop `lk.agent.state`
    # (session.start has already moved it to "listening").
    assistant._agent_state = session.agent_state
    session.on("agent_state_changed", assistant._on_agent_state_changed)

    # Log connection churn and the REASON a participant or the room disconnected — useful
    # ops visibility (tells a client-initiated teardown from a network/signal drop).
    def _reason_name(r: object) -> str:
        try:
            from livekit import rtc as _rtc

            return f"{_rtc.DisconnectReason.Name(r)}({r})"
        except Exception:
            return str(r)

    ctx.room.on(
        "reconnecting", lambda: logger.warning("room RECONNECTING (agent-side blip)")
    )
    ctx.room.on("reconnected", lambda: logger.info("room reconnected"))
    ctx.room.on(
        "disconnected",
        lambda *a: logger.warning(
            "room DISCONNECTED reason=%s", _reason_name(a[0]) if a else "?"
        ),
    )
    ctx.room.on(
        "participant_disconnected",
        lambda p: logger.info(
            "participant disconnected: %s reason=%s",
            getattr(p, "identity", "?"),
            _reason_name(getattr(p, "disconnect_reason", None)),
        ),
    )

    # (The cosmetic mood ring is driven from `tts_node` via `_mood_tee`, so it updates
    # as the agent starts speaking rather than after the turn is committed.)

    # Register switching is user-driven: the frontend toggle calls this RPC, which
    # swaps the expressive preset and triggers a short demo line in the new register.
    @ctx.room.local_participant.register_rpc_method("set_mode")
    async def _handle_set_mode(data) -> str:
        try:
            mode = (data.payload or "").strip().lower()
            if mode not in _PRESET_FOR_MODE:
                return json.dumps({"ok": False, "error": f"unknown mode {mode!r}"})
            await assistant.apply_mode(session, mode)
            return json.dumps({"ok": True, "mode": mode})
        except Exception as e:  # never let a switch error bubble into / disrupt the job
            logger.exception("set_mode failed")
            return json.dumps({"ok": False, "error": str(e)})

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
    elif design_task is not None:
        # Design-first: the voice build (already running) finishes behind a short
        # ack, then the TTS swaps into the designed voice for the greeting.
        await assistant.run_design_first(session, ctx, design_task, design_instruction)
    else:
        # Preset voice: open straight into the expressive conversation.
        session.generate_reply(instructions=PRESET_GREETING)
        await ctx.connect()


if __name__ == "__main__":
    cli.run_app(server)
