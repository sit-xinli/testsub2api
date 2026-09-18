"""Generate images through the OpenAI Images API.

Talks to the same endpoint main.py uses; configured via .env or env vars:

    OPENAI_API_KEY   API key
    OPENAI_BASE_URL  http(s) base url, e.g. http://localhost:8089/v1
    IMAGE_MODEL      model name (falls back to REALTIME_MODEL, then gpt-image-2)
    IMAGE_SIZE       e.g. 1024x1024, 1536x1024, auto
    IMAGE_N          how many images to generate
    IMAGE_OUTPUT_DIR where to write the .png files

Run:  uv run image.py  ["your prompt"]
"""

import base64
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from openai import APIStatusError, OpenAI

load_dotenv()

API_KEY = os.environ.get("OPENAI_API_KEY", "")
BASE_URL = os.environ.get("OPENAI_BASE_URL", "http://localhost:8089/v1")
MODEL = os.environ.get("IMAGE_OPENAI_MODEL") or os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-2")
SIZE = os.environ.get("IMAGE_SIZE", "512x512")
N = int(os.environ.get("IMAGE_N", "1"))
OUTPUT_DIR = Path(os.environ.get("IMAGE_OUTPUT_DIR", "images"))

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)


def save(image, path: Path) -> None:
    """Write one returned image to disk, whether it came back as b64 or a url."""
    if getattr(image, "b64_json", None):
        path.write_bytes(base64.b64decode(image.b64_json))
    elif getattr(image, "url", None):
        with urllib.request.urlopen(image.url) as response:
            path.write_bytes(response.read())
    else:
        raise RuntimeError("image contained neither b64_json nor url")


def main() -> None:
    prompt = " ".join(sys.argv[1:]) or "A red panda coding on a laptop, flat illustration"

    print(f"model: {MODEL}  size: {SIZE}  n: {N}")
    print(f"> {prompt}\n")

    try:
        response = client.images.generate(model=MODEL, prompt=prompt, size=SIZE, n=N)
    except APIStatusError as exc:
        print(f"[error] {exc.status_code}: {exc.message}", file=sys.stderr)
        raise SystemExit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    for index, image in enumerate(response.data, start=1):
        path = OUTPUT_DIR / f"{stamp}-{index}.png"
        save(image, path)
        print(f"saved {path}")
        if getattr(image, "revised_prompt", None):
            print(f"  revised prompt: {image.revised_prompt}")


if __name__ == "__main__":
    main()
