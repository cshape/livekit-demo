import contextlib
import logging
import os
import textwrap

from dotenv import load_dotenv
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    RunContext,
    cli,
    function_tool,
)
from livekit.plugins import cartesia, fishaudio, groq, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel

from voice_clone import (
    create_voice_clone,
    delete_voice_clone,
    frames_to_wav,
    record_session_audio,
    transcribe_frames,
    vad_trim_frames,
)

logger = logging.getLogger("agent")
load_dotenv(".env.local")


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            llm=groq.LLM(model="openai/gpt-oss-120b"),
            instructions=textwrap.dedent(
                """
                You are a friendly, reliable voice assistant.
                1-2 sentences max and use disfluencies and other mistakes to sound like a natural person speaking off the cuff.

                Early in the conversation, ask the user if they've ever cloned their voice before — pitch it as fun and easy.
                If they want to try it, tell them they'll need to talk continuously for about 15 seconds (any topic), and ask if they're ready.
                When they say they're ready, in the SAME turn:
                  - say one or two short casual sentences that (a) tell them to speak for about fifteen seconds about anything they want, (b) reassure them you'll holler when you've got enough audio, and (c) end with a clear "go" cue. Example feel: "OK — speak for about fifteen seconds about whatever you want, and I'll holler when I've got enough. Go ahead!"
                  - call the `clone_my_voice` tool
                The tool starts recording the instant your spoken sentence finishes, so don't pad it.
                The tool handles recording and uploading and only returns once the clone is fully ready. Follow its return instruction exactly — usually that means asking the user in one short, excited sentence if they want to hear their cloned voice.
                If the user agrees to hear it, call `play_cloned_voice`. If they decline, drop the topic and keep chatting in your normal voice.
                If the user declines cloning at any step, drop the topic and chat normally.
                """
            ),
        )
        self._cloned_voice_id: str | None = None
        self._job_ctx: JobContext | None = None

    async def _set_clone_state(self, state: str) -> None:
        """Push the cloning state to the room participant attributes so the frontend
        UI can show recording / cloning / ready / playing indicators.

        IMPORTANT: livekit-rtc's `set_attributes` has a bug — it builds the outgoing
        attribute set from a fresh empty FfiRequest instead of reading the current
        attributes, so it clobbers everything not in the dict you pass. We have to
        re-send `lk.agent.state` (managed by the Agents SDK) and any other keys
        ourselves, or the frontend's `useAgent` hook flips to `state==="failed"`
        and `useAgentErrors` kills the session.
        """
        if self._job_ctx is None:
            return
        try:
            participant = self._job_ctx.room.local_participant
            merged = dict(participant.attributes)
            merged["clone.state"] = state
            await participant.set_attributes(merged)
        except Exception:
            logger.exception("failed to set clone.state=%s", state)

    @function_tool
    async def clone_my_voice(self, context: RunContext) -> str:
        """Record ~15 seconds of the user's voice, upload to Fish Audio, and only return once the clone is ready.

        Call this only after the user has confirmed they're ready to speak continuously.
        IMPORTANT: in the same turn you call this tool, you MUST also speak a 1-2 sentence
        cue that tells the user to speak for ~15 seconds and that you'll holler when you've
        got enough audio. Recording starts the instant your spoken cue finishes.
        The tool plays a short "got it!" interrupt when the recording ends, blocks while
        the upload runs, and returns with instructions for you to ask if they want to hear
        their new voice.
        """
        session = context.session
        api_key = os.environ["FISH_API_KEY"]

        # No start cue here — the LLM already said "go!" as part of the same turn
        # that called this tool (per system instructions). Start recording immediately.
        await self._set_clone_state("recording")

        try:
            frames = await record_session_audio(session, duration_secs=15.0)
        except Exception as e:
            logger.exception("voice recording failed")
            await self._set_clone_state("idle")
            return f"Recording failed: {e}. Tell the user something went wrong and offer to retry."

        # If the user disconnected mid-recording, the session is closing — bail
        # before we waste time/money on Fish and crash on session.say().
        if session._activity is None:
            logger.info("session closed mid-recording; aborting clone flow")
            await self._set_clone_state("idle")
            return "Session ended before cloning finished."

        # Discard any pending user turn so the buffered monologue doesn't trigger another tool call.
        session.clear_user_turn()
        await self._set_clone_state("cloning")

        # Short verbatim acknowledgment to fill the upload window. Verbatim (not
        # generate_reply) because generate_reply inside a tool sets tool_choice="none"
        # and Groq's gpt-oss strictly errors when the model tries to call a tool
        # anyway. allow_interruptions=False so the user — who may still be talking
        # from the monologue — can't bury it.
        try:
            ack_handle = session.say(
                "Got it! Give me just a sec to clone your voice.",
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
            logger.exception("STT for reference transcript failed; uploading without texts")
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
        return "Voice switched. Say something short and warm so the user hears their new voice."

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
        tts=fishaudio.TTS(),
        turn_detection=MultilingualModel(),
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

    # Open the conversation — agent greets and immediately pitches the cloning demo.
    session.generate_reply(
        instructions=(
            "Greet the user warmly in one short, casual sentence and ask if they "
            "want to try cloning their voice — mention it only takes about fifteen seconds."
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
