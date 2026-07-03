import asyncio
import base64
import io
import json
import logging
import wave

import aiohttp
from livekit import rtc
from livekit.agents import vad
from livekit.agents.voice.io import AudioInput

logger = logging.getLogger("voice_clone")

FISH_BASE_URL = "https://api.fish.audio"


class PassthroughCaptureAudioInput(AudioInput):
    """Passes every frame through to the session pipeline unchanged, and (when
    `recording` is True) also appends a copy into `frames` for later voice cloning.

    The buffer is hard-capped at `max_secs` of buffered audio — frames pulled
    after the cap are still forwarded to the pipeline but not appended, so a
    runaway-long session can't blow memory and the eventual upload is bounded."""

    def __init__(self, source: AudioInput, max_secs: float = 30.0) -> None:
        super().__init__(label="voice-clone-passthrough", source=source)
        self.frames: list[rtc.AudioFrame] = []
        self.max_secs = max_secs
        self.recording = False
        self._buffered_secs = 0.0

    @property
    def buffered_secs(self) -> float:
        return self._buffered_secs

    @property
    def is_full(self) -> bool:
        return self._buffered_secs >= self.max_secs

    async def __anext__(self) -> rtc.AudioFrame:
        frame = await super().__anext__()
        if self.recording and not self.is_full:
            self.frames.append(frame)
            self._buffered_secs += frame.samples_per_channel / frame.sample_rate
        return frame


async def vad_trim_frames(
    vad_model: vad.VAD, frames: list[rtc.AudioFrame]
) -> list[rtc.AudioFrame]:
    """Run frames through silero VAD and return only the frames inside speech segments.

    Pads the input with ~1s of silence so END_OF_SPEECH fires even if the user was
    still talking at the moment recording ended. Falls back to the original frames
    if VAD detected no speech."""
    if not frames:
        return frames

    last = frames[-1]
    silence = rtc.AudioFrame(
        data=b"\x00" * last.samples_per_channel * last.num_channels * 2,
        sample_rate=last.sample_rate,
        num_channels=last.num_channels,
        samples_per_channel=last.samples_per_channel,
    )
    frame_secs = last.samples_per_channel / last.sample_rate
    pad_count = max(1, int(1.0 / frame_secs))
    padded = frames + [silence] * pad_count

    stream = vad_model.stream()

    async def push() -> None:
        for f in padded:
            stream.push_frame(f)
        stream.end_input()

    push_task = asyncio.create_task(push())

    speech_frames: list[rtc.AudioFrame] = []
    try:
        async for ev in stream:
            if ev.type == vad.VADEventType.END_OF_SPEECH:
                speech_frames.extend(ev.frames)
    finally:
        await push_task
        await stream.aclose()

    if not speech_frames:
        logger.warning("VAD detected no speech in capture; sending raw frames")
        return frames

    return speech_frames


def frames_to_wav(frames: list[rtc.AudioFrame]) -> bytes:
    sample_rate = frames[0].sample_rate
    num_channels = frames[0].num_channels

    # Stream each frame straight into the wave writer. Avoids building a full-size
    # `pcm` bytearray and a `bytes(pcm)` copy of it (two extra whole-recording copies
    # that, on the 512MB worker, helped tip voice-clone sessions into OOM). Peak here
    # is the BytesIO (the wav) plus one small per-frame copy that's freed each loop.
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(num_channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for f in frames:
            wf.writeframes(bytes(f.data.cast("B")))
    return buf.getvalue()


async def create_voice_clone(
    api_key: str,
    wav_bytes: bytes,
    *,
    title: str,
    transcript: str | None = None,
) -> str:
    form = aiohttp.FormData()
    form.add_field("type", "tts")
    form.add_field("title", title)
    form.add_field("train_mode", "fast")
    form.add_field("visibility", "private")
    form.add_field("enhance_audio_quality", "true")
    if transcript:
        form.add_field("texts", transcript)
    form.add_field(
        "voices",
        wav_bytes,
        filename="reference.wav",
        content_type="audio/wav",
    )

    async with (
        aiohttp.ClientSession() as session,
        session.post(
            f"{FISH_BASE_URL}/model",
            headers={"Authorization": f"Bearer {api_key}"},
            data=form,
        ) as resp,
    ):
        body = await resp.text()
        if resp.status >= 400:
            raise RuntimeError(f"Fish create-model failed: {resp.status} {body}")
        return json.loads(body)["_id"]


# What every voice-design candidate says in its generated sample. The sample is the
# ONLY reference audio the TTS model is built from, so keep it long enough (~10s of
# speech) for a decent clone. The API caps reference_text at 150 characters.
DESIGN_REFERENCE_TEXT = (
    "Well, hello there! I'm brand new — designed from a short description just a "
    "moment ago. Let's find out together how I sound out loud."
)


async def design_voice_sample(api_key: str, instruction: str) -> bytes:
    """Generate ONE candidate voice from a natural-language description via Fish's
    voice-design API and return its audio (WAV bytes). The endpoint is stateless —
    it creates no model; turning the candidate into a usable TTS voice is a separate
    create-model call with this audio as the reference."""
    payload = {
        "instruction": instruction,
        "reference_text": DESIGN_REFERENCE_TEXT,
        "n": 1,
    }
    async with (
        aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session,
        session.post(
            f"{FISH_BASE_URL}/v1/voice-design",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                # The endpoint requires the design model pinned via this header.
                "model": "voice-design-1",
            },
            json=payload,
        ) as resp,
    ):
        body = await resp.text()
        if resp.status >= 400:
            raise RuntimeError(f"Fish voice-design failed: {resp.status} {body}")
        candidates = json.loads(body).get("candidates") or []
        if not candidates:
            raise RuntimeError("Fish voice-design returned no candidates")
        return base64.b64decode(candidates[0]["audio_base64"])


async def create_designed_voice(api_key: str, instruction: str) -> str:
    """Design a voice from `instruction` and register it as a private TTS model.
    Returns the model_id, usable as a fishaudio voice_id (and deletable with
    delete_voice_clone like any other ephemeral demo voice)."""
    sample = await design_voice_sample(api_key, instruction)
    # We know exactly what the sample says (DESIGN_REFERENCE_TEXT), so pass it as
    # the reference transcript — unlike the clone-read flow, there's no risk of a
    # text/audio mismatch and it improves fidelity.
    return await create_voice_clone(
        api_key,
        sample,
        title="livekit-demo-design",
        transcript=DESIGN_REFERENCE_TEXT,
    )


async def delete_voice_clone(api_key: str, model_id: str) -> None:
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.delete(
                f"{FISH_BASE_URL}/model/{model_id}",
                headers={"Authorization": f"Bearer {api_key}"},
            ) as resp,
        ):
            if resp.status >= 400:
                body = await resp.text()
                logger.warning("Fish delete-model failed: %s %s", resp.status, body)
    except Exception as e:
        logger.warning("Fish delete-model raised: %s", e)
