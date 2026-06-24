"""Text-in / text-out tester for iterating on the expressive prompts.

Builds the SAME system prompt the live agent sends (CORE_INSTRUCTIONS from
agent.py + the resolved Fish preset for the chosen mode/mood), runs a small set
of queries through the agent's LLM, and prints, per query:

  RAW        — exactly what the model emitted (with <markup>)
  FISH       — what hits the Fish TTS API (markup converted to [brackets])
  TRANSCRIPT — what the user sees on screen (markup stripped)
  tags       — counts of expression/sound/break/emphasis it used

Reflects edits to agent.py immediately. Edits to the FORK's _provider_format.py
(the mode templates + shared guide) require a re-lock first (ask Claude / run
`uv lock -P livekit-agents ... && uv sync`).

Usage:
  uv run python scripts/prompt_test.py                      # casual, no mood, default query set
  uv run python scripts/prompt_test.py professional         # professional mode
  uv run python scripts/prompt_test.py casual excited       # casual + excited mood
  uv run python scripts/prompt_test.py casual "" "tell me about your day"   # one ad-hoc query
"""

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv  # noqa: E402
from livekit.agents.tts import _provider_format as pf  # noqa: E402
from livekit.agents.voice import presets  # noqa: E402
from openai import OpenAI  # noqa: E402

import src.agent as agent  # noqa: E402

load_dotenv(".env.local")

# Edit this set freely — a small spread of conversational situations.
QUERIES = [
    "hey, what can you do?",
    "ugh, my order still hasn't shown up and it's been two weeks",
    "haha okay that's actually hilarious, tell me a fun fact",
    "eh, i dunno, just kind of hanging out",
    "wait, what's the difference between your modes?",
]

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")


def system_prompt(mode: str, mood: str | None) -> str:
    opts = presets.resolve_options(
        agent._expressive_for(mode, mood),
        provider_key="fishaudio",
        default=list(presets._REGISTRY["fishaudio"].values())[0],
    )
    return agent.CORE_INSTRUCTIONS.strip() + "\n\n" + str(opts["tts_instructions_template"])


def tag_counts(text: str) -> str:
    n = {
        k: len(re.findall(rf"<{k}\b", text))
        for k in ("expression", "sound", "break", "emphasis")
    }
    return " ".join(f"{k}={v}" for k, v in n.items())


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "casual"
    mood = (sys.argv[2] or None) if len(sys.argv) > 2 else None
    queries = [sys.argv[3]] if len(sys.argv) > 3 else QUERIES

    sp = system_prompt(mode, mood)
    client = OpenAI()
    header = f"MODEL={MODEL}  MODE={mode}  MOOD={mood or '-'}  | system prompt ~{len(sp) // 4} tok"
    print(header)
    print("=" * len(header))

    for q in queries:
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": sp},
                    {"role": "user", "content": q},
                ],
            )
            raw = (resp.choices[0].message.content or "").strip()
        except Exception as e:
            print(f"\nUSER: {q}\n  [ERROR] {type(e).__name__}: {e}")
            continue
        fish = pf.convert_markup("fishaudio", pf.normalize_markup("fishaudio", raw))
        transcript = pf.strip_markup("fishaudio", raw)
        print(f"\nUSER: {q}")
        print(f"  RAW:        {raw}")
        print(f"  FISH:       {fish}")
        print(f"  TRANSCRIPT: {transcript.strip()}")
        print(f"  tags:       {tag_counts(raw)}")


if __name__ == "__main__":
    main()
