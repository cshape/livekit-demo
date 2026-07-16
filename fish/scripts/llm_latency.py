"""Latency + disfluency probe across conversation LLMs (gpt-5.1 vs self-hosted Gemma).

Hits each model with the SAME realistic prompt the agent uses at runtime
(CORE_INSTRUCTIONS + the casual Fish expressive preset the SDK injects each turn),
streams representative turns, and reports:
  - TTFT (gates perceived voice latency) + total wall time + tok/s
  - disfluency counts on the spoken text (fillers / stutters / repeats / hedges)

The disfluency table is the cross-model consistency check: we want the casual prompt
to land a similar disfluency rate on every model, not near-zero on gpt-5.1 and a flood
on Gemma. Reads both endpoints' creds from .env.local; a model with missing creds is
skipped.

Run from fish/:  uv run python scripts/llm_latency.py
"""

from __future__ import annotations

import asyncio
import os
import re
import statistics
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(_ROOT, ".env.local"))

# Real runtime prompts, imported so this never drifts from production.
from livekit.agents.tts import _provider_format as pf  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402

from src.agent import build_instructions  # noqa: E402

REPS = 3  # samples per query per model

# The casual register's tts_instructions are injected by the SDK as a second system
# message each turn; concatenating matches the prefill the endpoint actually sees.
_CASUAL = pf._FISHAUDIO_CASUAL["tts_instructions_template"].common
CONV_SYSTEM = build_instructions() + "\n\n" + _CASUAL

# (label, model, base_url|None, api_key) — base_url None => direct OpenAI.
TARGETS = [
    (
        "gpt-5.1",
        os.getenv("OPENAI_MODEL", "gpt-5.1"),
        None,
        os.getenv("OPENAI_API_KEY"),
    ),
    (
        "gemma-26b",
        os.getenv("LLM_MODEL", "google/gemma-4-26B-A4B-it"),
        os.getenv("LLM_BASE_URL"),
        os.getenv("LLM_API_KEY"),
    ),
]

# Representative user turns for the casual expressive demo, each with a little history.
CONV_TURNS: list[tuple[str, list[dict]]] = [
    (
        "opening follow-up",
        [
            {
                "role": "user",
                "content": "yeah hey! this is pretty cool. so what can you actually do?",
            }
        ],
    ),
    (
        "product question",
        [
            {"role": "user", "content": "this is pretty cool"},
            {
                "role": "assistant",
                "content": "Oh, ha, thanks! Yeah, I'm a Fish Audio voice. What brought you by?",
            },
            {"role": "user", "content": "wait is this a real product or just a demo?"},
        ],
    ),
    (
        "sad pivot (range)",
        [
            {
                "role": "user",
                "content": "honestly today's been rough. my dog's been really sick.",
            }
        ],
    ),
    (
        "how cloning works",
        [{"role": "user", "content": "so how does the voice cloning actually work?"}],
    ),
    (
        "longer ask",
        [
            {
                "role": "user",
                "content": "can you tell me a quick funny story about something?",
            }
        ],
    ),
    ("simple factual", [{"role": "user", "content": "what's the capital of france?"}]),
    (
        "agree / backchannel",
        [{"role": "user", "content": "yeah i totally agree with that, makes sense."}],
    ),
    (
        "excited news",
        [{"role": "user", "content": "dude i just got the job i interviewed for!!"}],
    ),
]

# --- disfluency counting (on the spoken text, with markup stripped) ---------------
_TAG_RE = re.compile(r"<[^>]+>|\[[^\]]+\]")
_FILLER_RE = re.compile(r"\b(?:um+|uh+|er|erm|hmm+|mm-?hm+)\b", re.I)
# mid-word stutter: short prefix + hyphen + word ("y-yeah", "th-this", "b-because").
_STUTTER_RE = re.compile(r"\b\w{1,2}-\w", re.I)
# repeated word, optionally split by a filler ("I, I", "that's, that's", "the, uh, the").
_REPEAT_RE = re.compile(r"\b(\w+)\b\s*,\s+(?:(?:um+|uh+|er|hmm+)\s*,?\s+)?\1\b", re.I)
_HEDGE_RE = re.compile(r"\b(?:kind of|sort of|sorta|i mean|i guess|you know)\b", re.I)


def disfluency(text: str) -> dict[str, int]:
    spoken = _TAG_RE.sub(" ", text)
    counts = {
        "filler": len(_FILLER_RE.findall(spoken)),
        "stutter": len(_STUTTER_RE.findall(spoken)),
        "repeat": len(_REPEAT_RE.findall(spoken)),
        "hedge": len(_HEDGE_RE.findall(spoken)),
    }
    counts["total"] = sum(counts.values())
    return counts


def _kwargs_for(model: str) -> dict:
    # gpt-5 / o-series: max_completion_tokens, no custom temperature, thinking off.
    if model.startswith(("gpt-5", "o1", "o3", "o4")):
        return {"max_completion_tokens": 300, "reasoning_effort": "none"}
    return {"max_tokens": 300, "temperature": 0.7}


async def _stream_once(client: AsyncOpenAI, model: str, messages: list[dict]):
    t0 = time.perf_counter()
    ttft = None
    out_tokens = 0
    parts: list[str] = []
    stream = await client.chat.completions.create(
        model=model,
        messages=messages,
        stream=True,
        stream_options={"include_usage": True},
        **_kwargs_for(model),
    )
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
            if ttft is None:
                ttft = time.perf_counter() - t0
            parts.append(chunk.choices[0].delta.content)
        if chunk.usage is not None:
            out_tokens = chunk.usage.completion_tokens
    total = time.perf_counter() - t0
    return ttft or total, total, out_tokens, "".join(parts)


def _fmt(samples: list[float]) -> str:
    s = sorted(samples)
    p50 = statistics.median(s)
    p90 = s[min(len(s) - 1, round(0.9 * (len(s) - 1)))]
    return (
        f"p50 {p50 * 1000:6.0f}ms  p90 {p90 * 1000:6.0f}ms  max {s[-1] * 1000:6.0f}ms"
    )


async def run_target(
    label: str, model: str, base_url: str | None, api_key: str | None
) -> dict | None:
    if not api_key:
        print(f"\n### {label}: SKIPPED (missing api key)\n")
        return None
    client = (
        AsyncOpenAI(base_url=base_url, api_key=api_key)
        if base_url
        else AsyncOpenAI(api_key=api_key)
    )
    print(
        f"\n{'=' * 64}\n### {label}   model={model}   {'(self-hosted)' if base_url else '(openai)'}\n{'=' * 64}"
    )
    try:
        await _stream_once(client, model, [{"role": "user", "content": "hi"}])  # warm
    except Exception as e:
        print(f"  WARMUP FAILED: {type(e).__name__}: {e}")
        return None

    all_ttft: list[float] = []
    agg = {"filler": 0, "stutter": 0, "repeat": 0, "hedge": 0, "total": 0}
    n_replies = 0
    print(f"{'turn':24}{'TTFT':>9}{'total':>9}{'tok/s':>8}{'disfl/reply':>13}")
    for tlabel, history in CONV_TURNS:
        msgs = [{"role": "system", "content": CONV_SYSTEM}, *history]
        ttfts, totals, toks, dis = [], [], [], []
        for _ in range(REPS):
            ttft, total, n, text = await _stream_once(client, model, msgs)
            ttfts.append(ttft)
            totals.append(total)
            toks.append(n)
            d = disfluency(text)
            dis.append(d["total"])
            for k in agg:
                agg[k] += d[k]
            n_replies += 1
        all_ttft.extend(ttfts)
        tps = statistics.mean(
            t / tot for t, tot in zip(toks, totals, strict=False) if tot > 0
        )
        print(
            f"{tlabel:24}{statistics.median(ttfts) * 1000:7.0f}ms"
            f"{statistics.median(totals) * 1000:7.0f}ms{tps:8.0f}{statistics.mean(dis):13.1f}"
        )
    per = {k: agg[k] / n_replies for k in agg}
    print(f"\n  TTFT  {_fmt(all_ttft)}")
    print(
        f"  disfluency / reply:  total {per['total']:.2f}   "
        f"(filler {per['filler']:.2f}, stutter {per['stutter']:.2f}, "
        f"repeat {per['repeat']:.2f}, hedge {per['hedge']:.2f})"
    )
    return {"label": label, "ttft": all_ttft, "per": per}


async def main() -> None:
    print(
        f"prompt prefill ~{len(CONV_SYSTEM)} chars   reps {REPS}   turns {len(CONV_TURNS)}"
    )
    results = []
    for t in TARGETS:
        r = await run_target(*t)
        if r:
            results.append(r)
    if len(results) >= 2:
        print(
            f"\n{'=' * 64}\n### CROSS-MODEL DISFLUENCY (want these close)\n{'=' * 64}"
        )
        print(
            f"{'model':14}{'total':>8}{'filler':>8}{'stutter':>9}{'repeat':>8}{'hedge':>7}"
        )
        for r in results:
            p = r["per"]
            print(
                f"{r['label']:14}{p['total']:8.2f}{p['filler']:8.2f}{p['stutter']:9.2f}{p['repeat']:8.2f}{p['hedge']:7.2f}"
            )


if __name__ == "__main__":
    asyncio.run(main())
