#!/usr/bin/env python
"""Generate (or edit) images through the OpenAI Images API using .env credentials.

Agent-facing driver for the testsub2api repo. Unlike image.py it writes to a
path *you* choose, loops client-side for n>1 (the endpoint rejects n>1), and
reports the real pixel dimensions of what came back (the endpoint ignores the
requested `size`).

Credentials are read from .env at the repo root -- resolved explicitly, not via
bare load_dotenv(), which resolves relative to the calling script and therefore
misses the repo .env when the driver is invoked from elsewhere.

    OPENAI_API_KEY   API key                         (required)
    OPENAI_BASE_URL  base url incl. /v1              (default https://www.sunyai.com/sub2api/v1)
    OPENAI_MODEL     model name                      (default gpt-image-2)

Run:  uv run .claude/skills/generate-image/driver.py "a red panda" --out out.png
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import struct
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

from openai import APIConnectionError, APIStatusError, OpenAI

OPENAI_BASE_URL = "https://www.sunyai.com/sub2api/v1"
OPENAI_IMAGE_MODEL = "gpt-image-2.5-flare"

def dimensions(data: bytes) -> str:
    """Pixel size of a PNG/JPEG without pulling in Pillow (not a project dep)."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        width, height = struct.unpack(">II", data[16:24])
        return f"{width}x{height}"
    if data[:2] == b"\xff\xd8":
        offset = 2
        while offset < len(data) - 9:
            if data[offset] != 0xFF:
                offset += 1
                continue
            marker = data[offset + 1]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack(">HH", data[offset + 5 : offset + 9])
                return f"{width}x{height}"
            offset += 2 + struct.unpack(">H", data[offset + 2 : offset + 4])[0]
    return "unknown"


def image_bytes(image) -> bytes:
    """This endpoint always returns b64_json, but honour url responses too."""
    if getattr(image, "b64_json", None):
        return base64.b64decode(image.b64_json)
    if getattr(image, "url", None):
        with urllib.request.urlopen(image.url) as response:
            return response.read()
    raise RuntimeError("image contained neither b64_json nor url")


def output_paths(out: str | None, count: int, outdir: str) -> list[Path]:
    """One explicit --out, or timestamped names under --outdir for n>1."""
    if out and count == 1:
        return [Path(out)]

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if out:
        base = Path(out)
        return [
            base.with_name(f"{base.stem}-{index}{base.suffix or '.png'}")
            for index in range(1, count + 1)
        ]
    return [Path(outdir) / f"{stamp}-{index}.png" for index in range(1, count + 1)]


def read_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return Path(args.prompt_file).read_text(encoding="utf-8").strip()
    if args.prompt:
        return " ".join(args.prompt).strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    return ""


def generate_one(client, args, prompt: str):
    """One API call. n is always 1 -- the endpoint 400s on n>1."""
    if args.edit:
        with open(args.edit, "rb") as source:
            kwargs = dict(model=args.model, image=source, prompt=prompt, size=args.size)
            if args.mask:
                with open(args.mask, "rb") as mask:
                    return client.images.edit(**kwargs, mask=mask)
            return client.images.edit(**kwargs)

    kwargs = dict(model=args.model, prompt=prompt, size=args.size, n=1)
    if args.quality:
        kwargs["quality"] = args.quality
    return client.images.generate(**kwargs)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate or edit images via the OpenAI Images API (.env credentials)."
    )
    parser.add_argument("prompt", nargs="*", help="prompt text (or use --prompt-file / stdin)")
    parser.add_argument("--prompt-file", help="read the prompt from this file (avoids shell quoting)")
    parser.add_argument("--out", help="output path; with -n>1 becomes <stem>-1.png, <stem>-2.png")
    parser.add_argument("--outdir", default="images", help="dir for timestamped names (default: images)")
    parser.add_argument("-n", "--count", type=int, default=1, help="how many images (looped client-side)")
    parser.add_argument("--model", help="override OPENAI_MODEL")
    parser.add_argument("--size", default="1024x1024", help="requested size (advisory -- endpoint ignores it)")
    parser.add_argument("--quality", help="low|medium|high (accepted; effect unverified)")
    parser.add_argument("--edit", help="source image to edit instead of generating from scratch")
    parser.add_argument("--mask", help="optional mask PNG for --edit")
    parser.add_argument("--env", help="explicit path to .env")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON on stdout")
    parser.add_argument("--timeout", type=float, default=600.0, help="per-request timeout seconds")
    args = parser.parse_args()

    prompt = read_prompt(args)
    if not prompt:
        parser.error("no prompt given (positional, --prompt-file, or stdin)")

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print(f"OPENAI_API_KEY is empty -- checked env variables", file=sys.stderr)
        raise SystemExit(2)

    base_url = os.environ.get("OPENAI_BASE_URL", OPENAI_BASE_URL)
    args.model = args.model or os.environ.get("OPENAI_MODEL", OPENAI_IMAGE_MODEL)

    if not args.json:
        print(f"model: {args.model}  base: {base_url}  n: {args.count}", file=sys.stderr)
        print(f"> {prompt}\n", file=sys.stderr)

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=args.timeout)
    paths = output_paths(args.out, args.count, args.outdir)
    results = []

    for index, path in enumerate(paths, start=1):
        try:
            response = generate_one(client, args, prompt)
        except APIStatusError as exc:
            print(f"[error] {exc.status_code}: {exc.message}", file=sys.stderr)
            raise SystemExit(1)
        except APIConnectionError:
            print(f"[error] cannot reach {base_url}", file=sys.stderr)
            raise SystemExit(1)

        image = response.data[0]
        data = image_bytes(image)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

        entry = {
            "path": str(path),
            "bytes": len(data),
            "dimensions": dimensions(data),
            "revised_prompt": getattr(image, "revised_prompt", None),
        }
        results.append(entry)

        if not args.json:
            print(f"saved {path}  ({entry['dimensions']}, {len(data):,} bytes)", file=sys.stderr)
            if entry["revised_prompt"] and entry["revised_prompt"] != prompt:
                print(f"  revised prompt: {entry['revised_prompt']}", file=sys.stderr)

    if args.json:
        print(json.dumps({"model": args.model, "prompt": prompt, "images": results}, indent=2))


if __name__ == "__main__":
    main()
