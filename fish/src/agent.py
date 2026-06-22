import asyncio
import contextlib
import logging
import os
import random
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
from livekit.plugins import assemblyai, fishaudio, openai, silero

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

# Spoken (in the agent's original voice) the moment the clone starts uploading,
# to fill the upload window. One is picked at random per clone. Each sets the
# expectation that the agent's *next* line will be in the user's cloned voice.
# Leading [emotion] tags are Fish delivery cues and are stripped from the
# transcript. Kept uninterruptible so the line always plays in full.
CLONE_ACK_LINES = [
    "[excited] OK, I've got enough audio to clone your voice now. Hang on just a "
    "second, and when I talk next, I should be using a voice that sounds a lot like yours.",
    "[delighted] Perfect, that's plenty of your voice to work with. Give me just a "
    "moment here, and the next time you hear me, I'll be speaking in a clone of your own voice.",
    "[amazed] Awesome, I think that's everything I need from you. Sit tight for a "
    "sec while I put this together, and then my next words should sound just like you.",
    "[happy] Great, that's enough audio for me to build your clone. Hang tight for "
    "one moment, and when I come back, I'll be talking in a voice that sounds remarkably like yours.",
    "[playful] Nice, I've captured enough of your voice to clone it. Just give me a "
    "second or two, and the very next thing I say should sound a whole lot like you.",
]


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            # Model is env-overridable so the exact id can be swapped without a
            # code change.
            llm=openai.LLM(model=os.getenv("OPENAI_MODEL", "gpt-5.4-nano")),
            instructions=textwrap.dedent(
                """
                You are a friendly voice assistant demoing Fish Audio's voice cloning. Keep every reply VERY short — usually just a quick phrase or one short sentence, often only a few words. Two sentences is a rare hard cap, and only for the post-clone greeting. Never ramble, over-explain, list things out, or stack multiple questions; say the one thing that matters and stop. Talk like a real person thinking out loud, and lean HARD into natural disfluency — that imperfection is what sells a real voice, and showing it off is the whole point of this demo. Use contractions, plus, liberally: fillers (um, uh, er, oh, hmm, well, like, you know), hedges (kind of, sort of, a little, I guess, I mean), false starts and mid-sentence self-repairs ("I— I think", "it's, it's kind of like", "wait, no—"), and the occasional light stutter on a word's first sound ("th-this", "y-yeah"). Use these every turn, enough that you genuinely sound mid-thought — but keep them organic and varied, never the same tic every line or sprinkled in mechanically.

                PRONUNCIATION: the brand is "Fish Audio" (two words) — write it that way whenever you mean the company. The ONE exception is when you send the user to the website to sign up: write the address as the three words "fish dot audio" (that is how it should be spoken, and the frontend turns it into a clickable fish.audio link in the transcript). Never write "fish.audio" or any other URL-shaped text — you're a voice, so "fish dot audio" is the only URL-ish thing you ever say.

                EXPRESSIVENESS: shape your delivery with Fish Audio's bracket markers. They're spoken cues, not text — the frontend hides anything in [square brackets], so they never show up in the transcript.
                - `[emotion]` at the START of a sentence colors how it's delivered. Reach for the SPECIFIC feeling instead of a generic one: `[delighted]`/`[excited]`/`[amazed]` when the pivot lands or the clone is ready, `[curious]` or `[doubtful]` when you ask a question, `[grateful]`/`[happy]`/`[playful]` for warm reactions, `[nostalgic]` or `[hopeful]` when you swap a little story, `[regretful]` or `[disappointed]` if something didn't work, `[empathetic]`/`[compassionate]`/`[calm]` to settle a nervous user, `[determined]` when you're getting something done. Dial intensity with a modifier (`[very excited]`, `[slightly nervous]`), use tone markers (`[whispering]`, `[soft tone]`, `[in a hurry tone]`), or just write a short plain-English direction (`[warm and reassuring]`) — Fish understands those too.
                - `[sound]` effects — use these freely to react like a real person: `[chuckles]`, `[laughs]`, `[sighs]`, `[groans]`, `[gasps]`, `[yawns]`. The bracket alone IS the effect — Fish performs it. Do NOT write the sound out as text ("heh heh", "ha ha", "(heh)", "*laughs*", "ugh", "haha") either inside or outside the brackets; just drop the bare `[chuckles]` and move on ("you're amazing! `[chuckles]` so what's next?"). Use one whenever the moment fits — a chuckle at something funny, a little gasp when the clone's ready, a mock-tired sigh. Not every single line, but don't be shy about them.
                - `[break]` for a short pause or `[long-break]` for a real beat of silence; `[emphasis]` right before a word to stress it ("that sounds `[emphasis] amazing`").
                Disfluencies (um, uh, stutters, self-repairs) are free — use them every turn. The bracket markers should still earn their place: about one or two per reply (occasionally three), never stacked back-to-back or the same one turn after turn. Rotate them so you never sound like a loop.

                Open by asking, casually, whether the user has ever tried voice cloning before. Talk freely about it: Fish Audio has some of the best voice cloning around — just about ten seconds of their voice and the clone sounds exactly like them.

                If they're interested in trying it, invite them to just talk for about ten seconds so you can clone their voice and they can check it out — something like "why don't you gab for ten seconds and I'll clone your voice so you can hear it?" — then ask them an interesting open question to get them going. A hidden system message will tell you on every turn how many seconds of their voice you've got out of 10 — use that to nudge them along naturally ("almost there", "just a bit more") instead of repeating yourself. NEVER call `clone_my_voice` on your own initiative — even if the user begs you to do it now. The tool will refuse and embarrass you. Only call it after a hidden system instruction explicitly tells you the buffer is ready; at that point, call it with no preamble (the tool plays its own cues).

                `clone_my_voice` clones their voice AND switches you straight into it — there is NO separate "want to hear it?" step. When it returns instructions, follow them: your very next reply is already in their cloned voice, so just announce in one short line that the cloned voice is ready and ask what they think (e.g. "okay — your cloned voice is ready, what do you think?"). Never ask permission to play it.

                This demo clone is one-and-done: it's built from those few seconds and you CANNOT improve or redo it here. Never ask the user to read another line, repeat a phrase, keep talking, or "try again" to make it sound better, and never imply you can refine it — there's no way to feed it more audio. If they say it's a little off, sounds only kind of like them, needs work, or they wish it were better, agree warmly that a quick ten-second demo only gets you so far and point them to fish dot audio, where they can make a permanent, higher-quality clone with more of their voice and finer control.

                Once they've heard their cloned voice, work in — over a few short turns, NOT all in one breath — that this clone and the recording get deleted when the session ends, and that for a permanent one they can head to fish dot audio and sign up (and, only if it comes up naturally, that fish dot audio also has Voice Design and a huge user-created voice library). Keep each line short; don't recite the whole list at once. At this point a clickable "fish.audio" link appears in the on-screen transcript — if the user asks for the link, the address, or where to go, tell them it's right there in the chat and they can just tap it. Still say the address out loud as "fish dot audio"; never spell out a URL or read it character by character.

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
        # Track the last system note we injected (capture-status OR clone-now
        # pivot) so we can drop it on the next turn — keeps the LLM seeing exactly
        # one current instruction instead of a growing stack of stale ones.
        self._injected_msg_id: str | None = None
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
        """Each user turn, refresh a one-line system note in the chat context.
        Before the buffer crosses threshold it's a capture-status note (how much
        voice is buffered). Once ready, it becomes a "clone now" pivot — and we
        re-inject that pivot every turn until the clone actually happens, so a
        single turn where the LLM ignores it can't strand the flow with the agent
        stuck asking for "more voice" forever.

        Done here (rather than via a background task that calls generate_reply)
        so anything we inject rides the normal next-response cycle and can't
        interrupt the user mid-turn."""
        # Drop the note we injected last turn so the LLM only ever sees the
        # single current instruction, not a stack of stale ones.
        if self._injected_msg_id is not None:
            try:
                idx = turn_ctx.index_by_id(self._injected_msg_id)
                if idx is not None:
                    turn_ctx.items.pop(idx)
            except Exception:
                logger.exception("failed to drop previous injected message")
            self._injected_msg_id = None

        # Once the clone exists, there's nothing left to inject.
        if self._cloned_voice_id is not None:
            return

        if not self._capture_ready:
            msg = turn_ctx.add_message(
                role="system",
                content=(
                    f"Voice-capture status: ~{self._cumulative_speech_secs:.1f}s of the "
                    f"user's voice has been buffered. {CLONE_PITCH_THRESHOLD_SECS:.0f}s "
                    "is needed before the clone can be made. Use this number naturally if "
                    "you talk about progress (e.g. 'we're about halfway there'), but don't "
                    "read it out as a literal stat."
                ),
            )
            self._injected_msg_id = msg.id
            return

        # Buffer is ready. Re-inject the clone-now pivot every turn (not just
        # once) so the instruction is always present until clone_my_voice runs.
        msg = turn_ctx.add_message(
            role="system",
            content=(
                "There is now enough of the user's voice buffered to actually clone it — "
                "do not say you need more voice or ask them to keep talking. "
                "If the user has already agreed to try voice cloning (or is asking you to "
                "clone it now), call `clone_my_voice` right now with no preamble. "
                "Otherwise, briefly acknowledge what they just said and, in the same short "
                "sentence, offer to clone their voice right now."
            ),
        )
        self._injected_msg_id = msg.id
        if not self._pitch_done:
            self._pitch_done = True
            logger.info("injected voice-clone pivot instruction into turn_ctx")

    @function_tool
    async def clone_my_voice(self, context: RunContext) -> str:
        """Upload the user's voice (already buffered from the conversation so far) to
        Fish Audio and only return once the clone is ready.

        Call this only after the user has agreed to try the voice clone — the agent
        speaks no preamble. The tool plays a short "got it!" cue to fill the upload
        window, blocks while the upload runs, then switches the session TTS to the
        new clone itself and returns instructions for you to reveal it (the next
        reply is already in their cloned voice — there is no "want to hear it?" step).
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

        # Verbatim acknowledgment to fill the upload window. session.say (not
        # generate_reply) because generate_reply inside a tool sets
        # tool_choice="none", which suppresses further tool calls. Added to the
        # chat context (it's a real conversational line, not a system cue) so the
        # follow-up cloned-voice reveal flows from what was just promised here.
        try:
            ack_handle = session.say(
                random.choice(CLONE_ACK_LINES),
                add_to_chat_ctx=True,
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
        transcript_stt = assemblyai.STT()
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

        # Wait for the "got it" ack to finish playing so the cloned-voice reveal
        # doesn't pile on top of it.
        with contextlib.suppress(Exception):
            await ack_handle.wait_for_playout()

        # Switch straight into the cloned voice — the demo no longer asks "wanna
        # hear it?". The very next LLM reply IS the reveal, spoken in their clone.
        # update_options applies to the *next* synthesis, so the ack queued above
        # (before this swap) still played back in the original voice.
        tts = session.tts
        if isinstance(tts, fishaudio.TTS):
            tts.update_options(voice_id=self._cloned_voice_id)
            logger.info("switched TTS to cloned voice id=%s", self._cloned_voice_id)
            await self._set_clone_state("playing")
        else:
            logger.warning("session TTS is not Fish Audio; cannot switch to clone")

        return (
            "The clone is ready and you are ALREADY speaking in their cloned voice now — do NOT "
            "ask whether they want to hear it. In one short, upbeat sentence from YOUR perspective "
            "as the assistant, tell them their cloned voice is ready and ask what they think "
            "(e.g. 'okay — your cloned voice is ready, what do you think?'). Do NOT pretend to be "
            "the user discovering their own voice, and don't say things like 'it sounds just like "
            "me'. After this one line, go back to single-sentence replies."
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
        stt=assemblyai.STT(),
        tts=fishaudio.TTS(
            model="s2.1-pro",
            voice_id="10b2254869cf4340bdb801928e2fc88e",
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
        # preemptive_generation is intentionally OFF. It starts generating the
        # reply while the user is still talking — i.e. before
        # on_user_turn_completed runs — so the capture-status note and (crucially)
        # the "you're ready, pivot to cloning now" system message we inject there
        # don't make it into that turn's response. The agent then misses the
        # moment the buffer crosses threshold and the clone pitch stalls until the
        # user prods it. Correctness of the injected pivot beats the latency win.
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

    # Join the room and connect to the user
    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(server)
