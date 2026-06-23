"""Probe how reliably different LLMs emit the SDK's expressive markup tags.

Replicates what the Agents framework feeds the model under expressive mode: the
agent's CORE instructions plus the active register's resolved Fish preset template
(which inlines the <expression>/<sound>/<break> tag reference). Sends a few user
turns per (model, register) and reports the markup the model produced.

    uv run python scripts/probe_tag_fidelity.py
    MODELS="gpt-5.4-nano,gpt-4.1-mini" uv run python scripts/probe_tag_fidelity.py
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
from openai import OpenAI

import src.agent as agent
from livekit.agents.voice import presets

load_dotenv(".env.local")

MODELS = os.getenv("MODELS", "gpt-5.4-nano,gpt-4.1-mini").split(",")
REGISTERS = ["professional", "casual"]
USER_TURNS = [
    "hey! so what can you actually do?",
    "ugh, my order never showed up and I'm pretty annoyed about it.",
    "haha okay that's amazing, tell me a quick fun fact.",
]

client = OpenAI()


def system_prompt(mode: str) -> str:
    ex = agent._expressive_for(mode, None)
    opts = presets.resolve_options(
        ex,
        provider_key="fishaudio",
        default=list(presets._REGISTRY["fishaudio"].values())[0],
    )
    return agent.CORE_INSTRUCTIONS.strip() + "\n\n" + str(opts["tts_instructions_template"])


def analyze(text: str) -> dict:
    return {
        "expression": len(re.findall(r"<expression\b", text)),
        "sound": len(re.findall(r"<sound\b", text)),
        "break": len(re.findall(r"<break\b", text)),
        "emphasis": len(re.findall(r"<emphasis\b", text)),
        "stray_brackets": len(re.findall(r"\[[^\]]+\]", text)),
        "malformed_lt": len(re.findall(r"<(?!/?(expression|sound|break|emphasis)\b)", text)),
    }


for model in MODELS:
    print(f"\n{'=' * 70}\nMODEL: {model}\n{'=' * 70}")
    for mode in REGISTERS:
        sys = system_prompt(mode)
        print(f"\n--- register: {mode} ---")
        for turn in USER_TURNS:
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": sys},
                        {"role": "user", "content": turn},
                    ],
                )
                out = (resp.choices[0].message.content or "").strip()
            except Exception as e:  # noqa: BLE001
                print(f"  [ERROR calling {model}]: {e}")
                break
            a = analyze(out)
            print(f"  U: {turn}")
            print(f"  A: {out}")
            print(f"     tags -> {a}\n")
