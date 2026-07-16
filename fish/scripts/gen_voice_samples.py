"""One-off generator for the landing-page voice previews.

Synthesizes a short expressive line in each of the 4 preset Fish Audio voices via
the Fish HTTP TTS endpoint (POST /v1/tts, msgpack body — same wire format the
livekit-plugins-fishaudio plugin uses) and writes them as static mp3s under
web/public/voice-samples/<voice_id>.mp3 for the picker's play buttons.

Run once (and re-run if you change voices or the sample line):

    cd fish && uv run python scripts/gen_voice_samples.py

Needs FISH_API_KEY (read from fish/.env.local).
"""

import asyncio
import os
import pathlib

import aiohttp
import msgpack
from dotenv import load_dotenv

load_dotenv(".env.local")

FISH_BASE_URL = "https://api.fish.audio"
MODEL = "s2.1-pro"

# A short one-liner for the preview, per language. The leading [happy] is a Fish
# delivery cue (performed, not spoken) so the sample still sounds expressive.
SAMPLE_TEXT = {
    "en": "[happy] I'm one of Fish Audio's expressive voices.",
    "ja": "[happy] 私はFish Audioの表現力豊かな声のひとつです。",
}

# Keep in sync with PRESET_VOICES in src/agent.py and PRESET_VOICES /
# PRESET_VOICES_JA in web/app-config.ts. voice_id -> (label, lang).
PRESET_VOICES = {
    "747b05c0add940baa95270cf68c0cc2e": ("Stellan (American M)", "en"),
    "41db1fc3c3624332bec9997ff3d3d353": ("Maeve (British F)", "en"),
    "9a3a69c63dbc4774ac41b03945229dc8": ("Alistair (British M)", "en"),
    "0e24ff9936d34df4bddce26398cf1311": ("Maren (US F)", "en"),
    "297a6fd278df47c3b9da9bfdf55ac89a": ("さとる (Japanese M)", "ja"),
    "88ee033403f24744965262d7369686e1": ("まり (Japanese F)", "ja"),
    "8d7ac3b4f8cc4f7cbe2f39887e8c5247": ("丁寧な青年 (Japanese M)", "ja"),
    "b2d9d8db057042688a5e318b8f405bc2": ("きょうこ (Japanese F)", "ja"),
}

OUT_DIR = (
    pathlib.Path(__file__).resolve().parents[2] / "web" / "public" / "voice-samples"
)


def _build_payload(text: str, voice_id: str) -> dict:
    return {
        "text": text,
        "chunk_length": 200,
        "format": "mp3",
        "sample_rate": 44100,
        "mp3_bitrate": 128,
        "opus_bitrate": 64000,
        "references": [],
        "reference_id": voice_id,
        "normalize": True,
        "latency": "normal",
        "prosody": None,
        "top_p": 0.7,
        "temperature": 0.7,
    }


async def synth(
    session: aiohttp.ClientSession, api_key: str, voice_id: str, text: str
) -> bytes:
    async with session.post(
        f"{FISH_BASE_URL}/v1/tts",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/msgpack",
            "model": MODEL,
        },
        data=msgpack.packb(_build_payload(text, voice_id), use_bin_type=True),
        timeout=aiohttp.ClientTimeout(total=60),
    ) as resp:
        resp.raise_for_status()
        return await resp.read()


async def main() -> None:
    api_key = os.environ.get("FISH_API_KEY")
    if not api_key:
        raise SystemExit("FISH_API_KEY not set (expected in fish/.env.local)")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    async with aiohttp.ClientSession() as session:
        for voice_id, (label, lang) in PRESET_VOICES.items():
            print(f"synthesizing {label} ({voice_id}) ...")
            audio = await synth(session, api_key, voice_id, SAMPLE_TEXT[lang])
            out = OUT_DIR / f"{voice_id}.mp3"
            out.write_bytes(audio)
            print(f"  wrote {out} ({len(audio)} bytes)")

    print(f"done — {len(PRESET_VOICES)} samples in {OUT_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
