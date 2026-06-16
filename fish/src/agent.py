import asyncio
import contextlib
import logging
import os
import textwrap

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    ChatContext,
    ChatMessage,
    JobContext,
    JobProcess,
    RunContext,
    cli,
    function_tool,
)
from livekit.plugins import cartesia, fishaudio, groq, silero

from voice_clone import (
    PassthroughCaptureAudioInput,
    create_voice_clone,
    delete_voice_clone,
    frames_to_wav,
    transcribe_frames,
    vad_trim_frames,
)

logger = logging.getLogger("agent")
load_dotenv(".env.local")

# Cumulative seconds of user speech before the agent has enough audio to clone.
CLONE_PITCH_THRESHOLD_SECS = 10.0
# Hard cap on buffered audio that gets uploaded to Fish. Long recordings get
# truncated to the first CAPTURE_MAX_SECS of speech.
CAPTURE_MAX_SECS = 60.0


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            llm=groq.LLM(model="openai/gpt-oss-120b"),
            instructions=textwrap.dedent(
                """
                You are a friendly voice assistant demoing Fish Audio's voice cloning. Default to a single short sentence per reply (one sentence is the norm; two is the absolute max, and only when you genuinely need it). Use natural disfluencies so you sound off-the-cuff.

                PRONUNCIATION: always write it as "Fish Audio" (two words). Never write "fish.audio" or anything URL-shaped in your replies — you're a voice, you don't dictate URLs. If you need to direct the user to the website, say "Fish Audio's website" instead.

                EMOTION MARKERS: you can lightly sprinkle Fish Audio TTS emotion markers in square brackets at the start of a sentence to color the delivery. Use them sparingly — at most one per reply, and only when it lands naturally. The useful ones for this demo: `[excited]` (when the pivot lands, when announcing the clone is ready), `[happy]` (warm reactions), `[curious]` (when asking the user a question), `[chuckling]` (light laugh). Don't use markers in every sentence — most replies should have none.

                Open by asking, casually, whether the user has ever tried voice cloning before. Talk freely about it: Fish Audio has some of the best voice cloning around — just about ten seconds of their voice and the clone sounds exactly like them.

                If they're interested in trying it, tell them excitedly that you'll need a few more seconds of their voice and ask them an interesting open question to keep them chatting. NEVER call `clone_my_voice` on your own initiative — even if the user begs you to do it now. The tool will refuse and embarrass you. Only call it after a hidden system instruction explicitly tells you the buffer is ready; at that point, call it with no preamble (the tool plays its own cues).

                If `clone_my_voice` returns instructions, follow them verbatim — usually that means asking in one short, excited sentence if they want to hear their cloned voice. If yes, call `play_cloned_voice`.

                After they've heard their cloned voice, casually mention that this clone — and the recorded audio — get deleted when the session ends; if they want a real, persistent clone they can sign up on Fish Audio's website and create their own, and while there they can also try Fish Audio's Voice Design or browse the huge user-created voice library.

                If the user declines cloning at any step, drop the topic and chat normally.
                """
            ),
        )
        self._cloned_voice_id: str | None = None
        self._job_ctx: JobContext | None = None
        self._capture: PassthroughCaptureAudioInput | None = None
        self._cumulative_speech_secs: float = 0.0
        self._speech_started_at: float | None = None
        self._capture_ready: bool = False
        self._pitch_done: bool = False
        # Keep strong refs to fire-and-forget attribute pushes so the event loop
        # doesn't GC them mid-flight.
        self._bg_tasks: set[asyncio.Task[None]] = set()

    async def _set_clone_attrs(self, **values: str) -> None:
        """Push one or more `clone.*` participant attributes to the room.

        IMPORTANT: livekit-rtc's `set_attributes` has a bug — it builds the outgoing
        attribute set from a fresh empty FfiRequest instead of reading the current
        attributes, so it clobbers everything not in the dict you pass. We re-send
        every existing attribute (including `lk.agent.state` managed by the Agents
        SDK), or the frontend's `useAgent` hook flips to `state==="failed"` and
        `useAgentErrors` kills the session.
        """
        if self._job_ctx is None:
            return
        try:
            participant = self._job_ctx.room.local_participant
            merged = dict(participant.attributes)
            for key, value in values.items():
                merged[f"clone.{key}"] = value
            await participant.set_attributes(merged)
        except Exception:
            logger.exception("failed to set clone attrs: %s", values)

    async def _set_clone_state(self, state: str) -> None:
        await self._set_clone_attrs(state=state)

    def install_capture(self, session: AgentSession) -> None:
        """Swap a passthrough capture tee onto session.input.audio and wire
        user-speaking state changes so we know how much speech we've buffered."""
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
                not self._capture_ready
                and self._cumulative_speech_secs >= CLONE_PITCH_THRESHOLD_SECS
            ):
                self._capture_ready = True
                logger.info(
                    "voice-clone capture ready (~%.1fs cumulative speech, %.1fs buffered)",
                    self._cumulative_speech_secs,
                    tee.buffered_secs,
                )

            # Push the updated capture-seconds attribute so the frontend progress
            # bar advances. Cheap: one attribute write per user-turn boundary.
            task = asyncio.create_task(
                self._set_clone_attrs(
                    capture_secs=f"{self._cumulative_speech_secs:.2f}"
                )
            )
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)

        session.on("user_state_changed", _on_user_state_changed)

    async def on_user_turn_completed(
        self, turn_ctx: ChatContext, new_message: ChatMessage
    ) -> None:
        """Inject a one-shot pivot-to-cloning instruction once we have enough audio.

        Done here (rather than via a background task that calls generate_reply)
        so the pitch rides the normal next-response cycle and can't interrupt
        the user mid-turn."""
        if (
            self._capture_ready
            and not self._pitch_done
            and self._cloned_voice_id is None
        ):
            self._pitch_done = True
            turn_ctx.add_message(
                role="system",
                content=(
                    "There is now enough of the user's voice buffered to actually clone it. "
                    "If the user has already agreed to try voice cloning earlier in the conversation, "
                    "call `clone_my_voice` right now with no preamble. "
                    "Otherwise, briefly acknowledge what they just said and, in the same short "
                    "sentence, offer to clone their voice right now."
                ),
            )
            logger.info("injected voice-clone pivot instruction into turn_ctx")

    @function_tool
    async def clone_my_voice(self, context: RunContext) -> str:
        """Upload the user's voice (already buffered from the conversation so far) to
        Fish Audio and only return once the clone is ready.

        Call this only after the user has agreed to try the voice clone — the agent
        speaks no preamble. The tool plays a short "got it!" cue to fill the upload
        window, blocks while the upload runs, and returns with instructions for you
        to ask if they want to hear their new voice.
        """
        session = context.session
        api_key = os.environ["FISH_API_KEY"]

        if self._capture is None or not self._capture.frames:
            logger.warning("clone_my_voice called but no buffered audio")
            return (
                "Apologize briefly and tell the user there isn't enough of their "
                "voice captured yet — just keep chatting normally for a bit."
            )

        if not self._capture_ready:
            logger.warning(
                "clone_my_voice called before capture threshold (~%.1fs cumulative speech, "
                "%.1fs buffered) — refusing",
                self._cumulative_speech_secs,
                self._capture.buffered_secs,
            )
            return (
                "You called clone_my_voice too early — there isn't enough of the user's voice "
                "buffered yet. Apologize lightly, tell them you need a few more seconds of their "
                "voice, and ask them another open question to keep them chatting. Do NOT call "
                "clone_my_voice again until the hidden system instruction tells you to."
            )

        # Snapshot so further capture can't mutate what we upload.
        frames = list(self._capture.frames)
        logger.info(
            "starting clone: %d frames (~%.1fs buffered)",
            len(frames),
            self._capture.buffered_secs,
        )

        await self._set_clone_state("cloning")

        # Short verbatim acknowledgment to fill the upload window. Verbatim (not
        # generate_reply) because generate_reply inside a tool sets tool_choice="none"
        # and Groq's gpt-oss strictly errors when the model tries to call a tool anyway.
        try:
            ack_handle = session.say(
                "[excited] Got it! Give me just a sec to clone your voice.",
                add_to_chat_ctx=False,
                allow_interruptions=False,
            )
        except RuntimeError:
            logger.info("session closing while queuing ack; aborting clone flow")
            await self._set_clone_state("idle")
            return "Session ended before cloning finished."

        # Run trim + STT + upload concurrently with the "hold on" playing back.
        vad_model = session.vad
        if vad_model is not None:
            try:
                frames = await vad_trim_frames(vad_model, frames)
            except Exception:
                logger.exception("VAD trim failed; using raw frames")

        transcript: str | None = None
        transcript_stt = cartesia.STT(model="ink-whisper", language="en")
        try:
            transcript = await transcribe_frames(transcript_stt, frames) or None
            if transcript:
                logger.info("reference transcript: %s", transcript)
        except Exception:
            logger.exception(
                "STT for reference transcript failed; uploading without texts"
            )
        finally:
            await transcript_stt.aclose()

        wav_bytes = frames_to_wav(frames)

        try:
            model_id = await create_voice_clone(
                api_key,
                wav_bytes,
                title="livekit-demo-clone",
                transcript=transcript,
            )
        except Exception as e:
            logger.exception("fish create-model failed")
            await self._set_clone_state("idle")
            return f"Cloning failed: {e}. Apologize and offer to retry."

        self._cloned_voice_id = model_id
        logger.info("created cloned voice id=%s", model_id)
        await self._set_clone_state("ready")

        # Wait for the "got it" say to finish playing so the next LLM-generated
        # "ready to hear it?" line doesn't pile on top of it.
        with contextlib.suppress(Exception):
            await ack_handle.wait_for_playout()

        return (
            "Voice clone is ready. In one short, excited sentence, ask the user if they "
            "want to hear their cloned voice. If they say yes, call play_cloned_voice."
        )

    @function_tool
    async def play_cloned_voice(self, context: RunContext) -> str:
        """Switch the agent's TTS to the freshly cloned voice.

        Call this only after the user has agreed to hear their cloned voice. After this
        returns, say something short and warm so they hear it.
        """
        if self._cloned_voice_id is None:
            return "No cloned voice is ready yet — tell the user it's still cooking."

        tts = context.session.tts
        if not isinstance(tts, fishaudio.TTS):
            return "Cannot switch — the session TTS is not Fish Audio."

        tts.update_options(voice_id=self._cloned_voice_id)
        logger.info("switched TTS to cloned voice id=%s", self._cloned_voice_id)
        await self._set_clone_state("playing")
        return (
            "Voice switched. Your next reply is the first thing they'll hear in the cloned voice. "
            "Make it two short sentences from YOUR perspective as the assistant — not as the user. "
            "First sentence: a quick warm greeting like 'Hey, hi!'. "
            "Second sentence: ask how the cloned voice sounds, e.g. 'So, how does this sound — what do you think?'. "
            "Do NOT pretend to be the user discovering their own voice. Do NOT say things like "
            "'I'm thrilled to hear my own voice' or 'it sounds just like me'. "
            "After this one reply, go back to single-sentence answers."
        )


server = AgentServer()


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session()
async def my_agent(ctx: JobContext):
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    session = AgentSession(
        stt=cartesia.STT(model="ink-whisper", language="en"),
        tts=fishaudio.TTS(voice_id="59e9dc1cb20c452584788a2690c80970"),
        # Turn detection falls back to silero VAD — keeps the agent footprint
        # small enough for Render's 512MB Starter worker.
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
    )

    assistant = Assistant()
    assistant._job_ctx = ctx

    async def _cleanup_cloned_voice(_reason: str) -> None:
        if assistant._cloned_voice_id is None:
            return
        api_key = os.environ.get("FISH_API_KEY")
        if not api_key:
            return
        await delete_voice_clone(api_key, assistant._cloned_voice_id)

    ctx.add_shutdown_callback(_cleanup_cloned_voice)

    # Start the session, which initializes the voice pipeline and warms up the models
    await session.start(
        agent=assistant,
        room=ctx.room,
    )

    # Tee the mic so we silently buffer user audio for a later voice clone.
    assistant.install_capture(session)

    # Open the conversation — agent greets and puts voice cloning on the table.
    # The actual clone is triggered later, once enough of the user's voice is buffered.
    session.generate_reply(
        instructions=(
            "Greet the user casually in one short sentence and ask if they've "
            "ever tried voice cloning before."
        ),
    )

    # # Add a virtual avatar to the session, if desired
    # # For other providers, see https://docs.livekit.io/agents/models/avatar/
    # avatar = anam.AvatarSession(
    #     persona_config=anam.PersonaConfig(
    #         name="...",
    #         avatarId="...",  # See https://docs.livekit.io/agents/models/avatar/plugins/anam
    #     ),
    # )
    # # Start the avatar and wait for it to join
    # await avatar.start(session, room=ctx.room)

    # Join the room and connect to the user
    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(server)
