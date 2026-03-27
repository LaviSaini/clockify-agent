"""OpenAI-compatible chat completion (no LangChain unless you add it later)."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


def complete_analysis(system_prompt: str, user_content: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set (see .env.example).")

    base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip() or None
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()

    client = OpenAI(api_key=api_key, base_url=base_url)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
    )
    choice = resp.choices[0]
    content = choice.message.content
    if not content:
        raise RuntimeError("LLM returned empty content.")
    return content.strip()
