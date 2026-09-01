"""Text chat over the OpenAI Realtime API (WebSocket).

Talks to the same endpoint main.py uses; configured via .env or env vars:

    OPENAI_API_KEY   API key
    OPENAI_BASE_URL  http(s) base url, e.g. http://localhost:8089/v1
    REALTIME_MODEL   model name

Run:  uv run realtime.py  ["your first message"]
"""

import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

API_KEY = os.environ.get(
    "OPENAI_API_KEY",
    "",
)
BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://localhost:8089/v1")
MODEL = os.environ.get("REALTIME_MODEL", "gpt-realtime")

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)


def ask(connection, text: str) -> None:
    """Send one user turn and print the streamed reply."""
    connection.conversation.item.create(
        item={
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": text}],
        }
    )
    connection.response.create()

    for event in connection:
        if event.type == "response.output_text.delta":
            print(event.delta, end="", flush=True)
        elif event.type == "response.output_text.done":
            print()
        elif event.type == "response.done":
            break
        elif event.type == "error":
            print(f"\n[error] {event.error.message}", file=sys.stderr)
            break


def main() -> None:
    prompt = " ".join(sys.argv[1:]) or "Write Python code for quicksort"

    with client.realtime.connect(model=MODEL) as connection:
        connection.session.update(
            session={
                "type": "realtime",
                "output_modalities": ["text"],
                "instructions": "You are a helpful assistant.",
            }
        )

        while True:
            print(f"\n> {prompt}\n")
            ask(connection, prompt)
            try:
                prompt = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not prompt or prompt in {"exit", "quit"}:
                break


if __name__ == "__main__":
    main()
