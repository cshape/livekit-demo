"""Conversation-LLM factory.

The single seam where we choose the LLM provider, kept out of the SDK's path so
`livekit-agents` / `livekit-plugins-openai` stay freely upgradable.

The LiveKit `openai.LLM` plugin is a generic OpenAI-compatible `/v1/chat/completions`
client (`base_url` + `api_key` are first-class args), so pointing it at our own
self-hosted model needs no fork and no custom `llm.LLM` subclass — just a base_url.
When `LLM_BASE_URL` is set we target that endpoint (e.g. the Gemma model served via
SGLang at `https://...api.fish.audio/v1`); otherwise we fall back to direct OpenAI.

The conversation LLM follows `LLM_BASE_URL`. The cosmetic mood-ring classifier is
decoupled: it follows its OWN `MOOD_BASE_URL` (default: direct OpenAI on the cheap
`MOOD_MODEL`), so the conversation can run on our self-hosted model while the mood
ring stays on a small OpenAI model — set `MOOD_BASE_URL` only if you also want the
mood ring on a custom endpoint.
"""

import os

from livekit.plugins import openai
from openai import AsyncOpenAI


def build_llm(default_openai_model: str) -> openai.LLM:
    """Build the conversation LLM from the environment.

    - `LLM_BASE_URL` set  -> our own OpenAI-compatible endpoint, using
      `LLM_MODEL` (default Gemma) + `LLM_API_KEY`, optional `LLM_TEMPERATURE`.
    - `LLM_BASE_URL` unset -> direct OpenAI, model from `OPENAI_MODEL` or the
      project default passed in.
    """
    base_url = os.getenv("LLM_BASE_URL")
    if base_url:
        kwargs = {}
        temperature = os.getenv("LLM_TEMPERATURE")
        if temperature is not None:
            kwargs["temperature"] = float(temperature)
        return openai.LLM(
            model=os.getenv("LLM_MODEL", "google/gemma-4-26B-A4B-it"),
            base_url=base_url,
            api_key=os.getenv("LLM_API_KEY"),
            **kwargs,
        )
    model = os.getenv("OPENAI_MODEL", default_openai_model)
    kwargs = {}
    # Thinking off: gpt-5 / o-series support reasoning_effort="none" for low-latency,
    # non-reasoning replies (older chat models don't take the param at all).
    if model.startswith(("gpt-5", "o1", "o3", "o4")):
        kwargs["reasoning_effort"] = "none"
    return openai.LLM(model=model, **kwargs)


def build_mood_client(default_openai_model: str) -> tuple[AsyncOpenAI, str]:
    """Build the (client, model) for the cosmetic mood-ring classifier.

    A raw `AsyncOpenAI` rather than the LiveKit plugin (the classifier makes a
    direct `chat.completions.create` JSON-mode call, off the agent pipeline).

    Decoupled from `build_llm`'s `LLM_BASE_URL`: the mood ring follows its OWN
    `MOOD_BASE_URL` (with `MOOD_API_KEY`, falling back to `LLM_API_KEY`), else direct
    OpenAI on the cheap `MOOD_MODEL` (default `gpt-4.1-mini`). So switching the
    conversation onto our own endpoint leaves the mood ring on OpenAI unless you opt
    it in too.
    """
    base_url = os.getenv("MOOD_BASE_URL")
    if base_url:
        client = AsyncOpenAI(
            base_url=base_url,
            api_key=os.getenv("MOOD_API_KEY") or os.getenv("LLM_API_KEY"),
        )
        model = os.getenv("MOOD_MODEL") or os.getenv(
            "LLM_MODEL", "google/gemma-4-26B-A4B-it"
        )
        return client, model
    return AsyncOpenAI(), os.getenv("MOOD_MODEL", default_openai_model)
