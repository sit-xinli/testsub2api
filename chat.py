"""Chat with the OpenAI Chat Completions API using the credentials in .env.

Configured the same way image.py is:

    OPENAI_API_KEY    API key
    OPENAI_BASE_URL   http(s) base url, e.g. http://localhost:8089/v1
    OPENAI_CHAT_MODEL model name, default gpt-5.6-luna
    CHAT_SYSTEM       optional system prompt
    CHAT_TEMPERATURE  optional sampling temperature

Run:  uv run chat.py                  interactive session
      uv run chat.py "your question"  one shot, then exit
"""

import os
import sys

from dotenv import load_dotenv
from openai import APIConnectionError, APIStatusError, OpenAI

load_dotenv()

API_KEY = os.environ.get("OPENAI_API_KEY", "")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://localhost:8089/v1")
MODEL = os.environ.get("OPENAI_CHAT_MODEL", "gpt-5.6-luna")
SYSTEM = os.environ.get("CHAT_SYSTEM", "")
TEMPERATURE = os.environ.get("CHAT_TEMPERATURE")

client = OpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=120.0)


def ask(messages: list[dict]) -> str:
    """Stream one assistant turn to stdout and return the collected text."""
    kwargs = {"model": MODEL, "messages": messages, "stream": True}
    if TEMPERATURE:
        kwargs["temperature"] = float(TEMPERATURE)

    chunks: list[str] = []
    stream = client.chat.completions.create(**kwargs)
    try:
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                chunks.append(delta.content)
                print(delta.content, end="", flush=True)
    finally:
        stream.close()
    print()
    return "".join(chunks)


def main() -> None:
    if not API_KEY:
        print("OPENAI_API_KEY is empty -- check .env", file=sys.stderr)
        raise SystemExit(1)

    messages: list[dict] = []
    if SYSTEM:
        messages.append({"role": "system", "content": SYSTEM})

    one_shot = " ".join(sys.argv[1:])

    print(f"model: {MODEL}  base: {BASE_URL}")
    if not one_shot:
        print("type your message; /reset clears history, /exit or Ctrl-D quits\n")

    while True:
        if one_shot:
            prompt = one_shot
        else:
            try:
                prompt = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if not prompt:
                continue
            if prompt in ("/exit", "/quit"):
                return
            if prompt == "/reset":
                del messages[1 if SYSTEM else 0 :]
                print("history cleared\n")
                continue

        messages.append({"role": "user", "content": prompt})
        print(f"{MODEL}> ", end="", flush=True)
        try:
            reply = ask(messages)
        except APIStatusError as exc:
            print(f"\n[error {exc.status_code}] {exc.message}", file=sys.stderr)
            messages.pop()
            if one_shot:
                raise SystemExit(1)
            continue
        except APIConnectionError:
            print(f"\ncannot reach {BASE_URL}", file=sys.stderr)
            raise SystemExit(1)
        messages.append({"role": "assistant", "content": reply})

        if one_shot:
            return
        print()


if __name__ == "__main__":
    main()
