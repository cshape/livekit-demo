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

from dotenv import load_dotenv
from livekit.agents.tts import _provider_format as pf
from livekit.agents.voice import presets
from openai import OpenAI

import src.agent as agent

load_dotenv(".env.local")

# Edit these freely. Casual = chatting like with a friend (should pull disfluency,
# sounds, emotional range). Professional = customer-service use cases (returns,
# billing, medical, tech support, info lookups).
CASUAL_QUERIES = [
    "yo what's up — what do you even do for fun?",
    "haha okay that octopus thing is wild, hit me with another weird fact",
    "ugh, I had the longest day, kinda just wanna veg out honestly",
    "wait, no way — you can actually do different voices? that's kinda sick",
    "eh, I'm bored, tell me something interesting or just make me laugh",
]

PROFESSIONAL_QUERIES = [
    "Hi, I'd like to return a blender I bought last week — it stopped working after two uses.",
    "I was charged twice for my subscription this month. Can you sort that out?",
    "I'm calling about my prescription refill — is it ready for pickup yet?",
    "My internet keeps dropping every few minutes and I work from home, this is a serious problem.",
    "Can you tell me what time my appointment is on Thursday, and the address?",
]

MODEL = os.getenv("OPENAI_MODEL", "gpt-5.1")


def system_prompt(mode: str, mood: str | None) -> str:
    # Mood no longer feeds the prompt (it's a cosmetic, separately-classified UI signal
    # now); the CLI still accepts a mood arg, but it only affects the report label.
    opts = presets.resolve_options(
        agent._expressive_for(mode),
        provider_key="fishaudio",
        default=next(iter(presets._REGISTRY["fishaudio"].values())),
    )
    return (
        agent.CORE_INSTRUCTIONS["en"].strip()
        + "\n\n"
        + str(opts["tts_instructions_template"])
    )


def tag_counts(text: str) -> str:
    n = {
        k: len(re.findall(rf"<{k}\b", text))
        for k in ("expression", "sound", "break", "emphasis")
    }
    return " ".join(f"{k}={v}" for k, v in n.items())


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "casual"
    mood = (sys.argv[2] or None) if len(sys.argv) > 2 else None
    default_queries = PROFESSIONAL_QUERIES if mode == "professional" else CASUAL_QUERIES
    queries = [sys.argv[3]] if len(sys.argv) > 3 else default_queries

    sp = system_prompt(mode, mood)
    client = OpenAI()
    header = f"MODEL={MODEL}  MODE={mode}  MOOD={mood or '-'}  | system prompt ~{len(sp) // 4} tok"
    print(header)
    print("=" * len(header))

    # Markdown report (path overridable via MD_OUT; default sits next to this script).
    md_path = os.getenv(
        "MD_OUT",
        os.path.join(
            os.path.dirname(__file__),
            f"prompt_report_{mode}{'_' + mood if mood else ''}.md",
        ),
    )
    md: list[str] = [
        f"# Prompt test — {mode}" + (f" · mood: {mood}" if mood else ""),
        f"`{MODEL}` · system prompt **~{len(sp) // 4} tok**",
        "",
        "## Composed system prompt",
        "```text",
        sp,
        "```",
        "",
        "## Responses",
    ]

    for i, q in enumerate(queries, 1):
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
            md += [f"\n### {i}. {q}", f"**ERROR** {type(e).__name__}: {e}"]
            continue
        fish = pf.convert_markup("fishaudio", pf.normalize_markup("fishaudio", raw))
        transcript = pf.strip_markup("fishaudio", raw).strip()
        tags = tag_counts(raw)
        print(f"\nUSER: {q}")
        print(f"  RAW:        {raw}")
        print(f"  FISH:       {fish}")
        print(f"  TRANSCRIPT: {transcript}")
        print(f"  tags:       {tags}")
        md += [
            f"\n### {i}. {q}",
            f"- **tags:** {tags}",
            "",
            "**RAW (model markup)**",
            f"```\n{raw}\n```",
            "**FISH (synthesized payload)**",
            f"```\n{fish}\n```",
            "**TRANSCRIPT (on-screen)**",
            f"> {transcript}",
        ]

    with open(md_path, "w") as f:
        f.write("\n".join(md) + "\n")
    print(f"\n📝 markdown report → {md_path}")


if __name__ == "__main__":
    main()
