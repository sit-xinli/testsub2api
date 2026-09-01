"""Smoke-test the Claude Messages API with the credentials in .env.

Configured the same way server.py is:

    ANTHROPIC_API_KEY   API key
    ANTHROPIC_API_URL   http(s) base url, e.g. http://localhost:8089/v1
    ANTHROPIC_MODEL     model name, default claude-opus-5

Run:  uv run test_anthropic.py
"""

import os
import sys

import anthropic
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
# The SDK appends /v1/messages itself, so hand it the origin without the /v1 suffix.
BASE_URL = os.environ.get("ANTHROPIC_API_URL", "http://localhost:8089/v1").rstrip("/")
BASE_URL = BASE_URL[: -len("/v1")] if BASE_URL.endswith("/v1") else BASE_URL
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")
EFFORT = os.environ.get("ANTHROPIC_EFFORT", "low")


def check_models(client: anthropic.Anthropic) -> None:
    """List what the upstream advertises; not every proxy implements this."""
    try:
        models = client.models.list(limit=20)
    except anthropic.APIError as exc:
        print(f"models.list  [{type(exc).__name__}] {exc}")
        return
    print(f"models.list  {', '.join(model.id for model in models.data)}")


def check_messages(client: anthropic.Anthropic) -> None:
    """One non-streaming round trip."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        # display defaults to "omitted" on Opus 5; ask for a summary so we see it.
        thinking={"type": "adaptive", "display": "summarized"},
        output_config={"effort": EFFORT},
        messages=[{"role": "user", "content": "Reply with exactly: pong"}],
    )
    for block in response.content:
        if block.type == "thinking" and block.thinking:
            print(f"  thinking: {block.thinking}")
        elif block.type == "text":
            print(f"  text: {block.text}")
    print(f"  model={response.model} stop_reason={response.stop_reason}")
    print(
        f"  input_tokens={response.usage.input_tokens} "
        f"output_tokens={response.usage.output_tokens}"
    )


def check_stream(client: anthropic.Anthropic) -> None:
    """The same call, streamed."""
    with client.messages.stream(
        model=MODEL,
        max_tokens=64000,
        thinking={"type": "adaptive", "display": "summarized"},
        output_config={"effort": EFFORT},
        messages=[{"role": "user", "content": "Count from 1 to 5, space separated."}],
    ) as stream:
        print("  ", end="")
        for text in stream.text_stream:
            print(text, end="", flush=True)
        final = stream.get_final_message()
    print(f"\n  stop_reason={final.stop_reason}")
    print(
        f"  input_tokens={final.usage.input_tokens} "
        f"output_tokens={final.usage.output_tokens}"
    )


def main() -> None:
    if not API_KEY:
        print("ANTHROPIC_API_KEY is empty -- check .env", file=sys.stderr)
        raise SystemExit(1)

    print(f"key:   {API_KEY[:8]}...{API_KEY[-4:]} ({len(API_KEY)} chars)")
    print(f"base:  {BASE_URL}")
    print(f"model: {MODEL}  effort: {EFFORT}\n")

    client = anthropic.Anthropic(api_key=API_KEY, base_url=BASE_URL, timeout=120.0)

    checks = (
        ("models", check_models),
        ("messages.create", check_messages),
        ("messages.stream", check_stream),
    )
    for name, check in checks:
        print(f"--- {name} ---")
        try:
            check(client)
        except anthropic.APIStatusError as exc:
            print(f"  [{type(exc).__name__} {exc.status_code}] {exc.message}", file=sys.stderr)
            raise SystemExit(1)
        except anthropic.APIConnectionError:
            print(f"  cannot reach {BASE_URL}", file=sys.stderr)
            raise SystemExit(1)
        print()

    print("OK")


if __name__ == "__main__":
    main()
