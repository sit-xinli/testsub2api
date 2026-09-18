"""Web UI for the three demos: image generation, coding, and chat.

Wraps image.py / coding.py / chat.py behind a small FastAPI app and serves a
Japanese single-page front end from static/.

Configured through .env, the same keys the scripts already use:

    OPENAI_API_KEY / OPENAI_BASE_URL / OPENAI_IMAGE_MODEL / OPENAI_CHAT_MODEL
    ANTHROPIC_API_KEY / ANTHROPIC_API_URL / ANTHROPIC_MODEL

Run:  uv run app.py          then open http://127.0.0.1:8000
"""

import asyncio
import base64
import json
import os
import urllib.request
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import APIConnectionError, APIStatusError, OpenAI
from pydantic import BaseModel

load_dotenv()

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

OPENAI_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_BASE = os.environ.get("OPENAI_BASE_URL", "http://localhost:8089/v1")
IMAGE_MODEL = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-2")
CHAT_MODEL = os.environ.get("OPENAI_CHAT_MODEL", "gpt-5.6-luna")

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
# The SDK appends /v1/messages itself, so hand it the origin without the /v1 suffix.
ANTHROPIC_BASE = os.environ.get("ANTHROPIC_API_URL", "http://localhost:8089/v1").rstrip("/")
ANTHROPIC_BASE = ANTHROPIC_BASE[: -len("/v1")] if ANTHROPIC_BASE.endswith("/v1") else ANTHROPIC_BASE
CODE_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5")
CODE_EFFORT = os.environ.get("ANTHROPIC_EFFORT", "low")

IMAGE_DIR = Path(os.environ.get("IMAGE_OUTPUT_DIR", "images"))

openai_client = OpenAI(api_key=OPENAI_KEY, base_url=OPENAI_BASE, timeout=180.0)
anthropic_client = anthropic.Anthropic(
    api_key=ANTHROPIC_KEY, base_url=ANTHROPIC_BASE, timeout=180.0
)

app = FastAPI(title="AI ツールキット")


class ImageRequest(BaseModel):
    prompt: str
    size: str = "1024x1024"
    n: int = 1


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    system: str = ""


def sse(event: str, **data) -> str:
    """One server-sent-event frame carrying a JSON payload."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def image_to_data_url(image) -> str:
    """Return a data: URL, whether the API sent back b64 or a remote url."""
    if getattr(image, "b64_json", None):
        return "data:image/png;base64," + image.b64_json
    if getattr(image, "url", None):
        with urllib.request.urlopen(image.url) as response:
            raw = response.read()
        return "data:image/png;base64," + base64.b64encode(raw).decode()
    raise RuntimeError("image contained neither b64_json nor url")


async def drain(produce: Callable[[], None], queue: asyncio.Queue) -> AsyncIterator[str]:
    """Run the blocking producer in a thread and forward its items as SSE."""
    task = asyncio.create_task(asyncio.to_thread(produce))
    try:
        while True:
            item = await queue.get()
            if item is None:
                break
            kind, payload = item
            if kind == "error":
                yield sse("error", message=payload)
            else:
                yield sse(kind, text=payload)
    finally:
        await task
    yield sse("done")


@app.get("/api/config")
def config() -> dict:
    """Model names shown in the footer of the UI."""
    return {
        "image_model": IMAGE_MODEL,
        "chat_model": CHAT_MODEL,
        "code_model": CODE_MODEL,
        "openai_base": OPENAI_BASE,
        "anthropic_base": ANTHROPIC_BASE,
    }


@app.post("/api/image")
async def generate_image(request: ImageRequest) -> dict:
    """Generate images and also keep a copy under images/."""
    prompt = request.prompt.strip()
    if not prompt:
        return {"error": "プロンプトを入力してください。"}

    def call():
        return openai_client.images.generate(
            model=IMAGE_MODEL,
            prompt=prompt,
            size=request.size,
            n=max(1, min(request.n, 4)),
        )

    try:
        response = await asyncio.to_thread(call)
    except APIStatusError as exc:
        return {"error": f"[{exc.status_code}] {exc.message}"}
    except APIConnectionError:
        return {"error": f"{OPENAI_BASE} に接続できません。"}
    except Exception as exc:  # noqa: BLE001 - surface whatever the proxy throws
        return {"error": f"{type(exc).__name__}: {exc}"}

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    images = []
    for index, image in enumerate(response.data, start=1):
        try:
            data_url = image_to_data_url(image)
        except Exception as exc:  # noqa: BLE001
            return {"error": f"画像の取得に失敗しました: {exc}"}
        path = IMAGE_DIR / f"{stamp}-{index}.png"
        path.write_bytes(base64.b64decode(data_url.split(",", 1)[1]))
        images.append(
            {
                "data_url": data_url,
                "saved_as": str(path),
                "revised_prompt": getattr(image, "revised_prompt", None),
            }
        )

    return {"images": images, "model": IMAGE_MODEL}


@app.post("/api/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    """Stream a chat turn from the OpenAI-compatible endpoint."""
    messages = [message.model_dump() for message in request.messages]
    if request.system:
        messages.insert(0, {"role": "system", "content": request.system})

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def emit(kind: str, payload: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (kind, payload))

    def produce() -> None:
        try:
            stream = openai_client.chat.completions.create(
                model=CHAT_MODEL, messages=messages, stream=True
            )
            try:
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        emit("text", delta.content)
            finally:
                stream.close()
        except APIStatusError as exc:
            emit("error", f"[{exc.status_code}] {exc.message}")
        except APIConnectionError:
            emit("error", f"{OPENAI_BASE} に接続できません。")
        except Exception as exc:  # noqa: BLE001
            emit("error", f"{type(exc).__name__}: {exc}")
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    return StreamingResponse(drain(produce, queue), media_type="text/event-stream")


@app.post("/api/code")
async def code(request: ChatRequest) -> StreamingResponse:
    """Stream a coding answer from the Claude Messages API, thinking included."""
    messages = [message.model_dump() for message in request.messages]
    system = request.system or (
        "あなたは熟練したソフトウェアエンジニアです。日本語で簡潔に答え、"
        "コードは言語名つきのコードブロックで示してください。"
    )

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def emit(kind: str, payload: str) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, (kind, payload))

    def produce() -> None:
        try:
            with anthropic_client.messages.stream(
                model=CODE_MODEL,
                max_tokens=16000,
                system=system,
                # display defaults to "omitted" on Opus 5; ask for a summary so we see it.
                thinking={"type": "adaptive", "display": "summarized"},
                output_config={"effort": CODE_EFFORT},
                messages=messages,
            ) as stream:
                for event in stream:
                    if event.type != "content_block_delta":
                        continue
                    delta = event.delta
                    if delta.type == "text_delta":
                        emit("text", delta.text)
                    elif delta.type == "thinking_delta":
                        emit("thinking", delta.thinking)
        except anthropic.APIStatusError as exc:
            emit("error", f"[{exc.status_code}] {exc.message}")
        except anthropic.APIConnectionError:
            emit("error", f"{ANTHROPIC_BASE} に接続できません。")
        except Exception as exc:  # noqa: BLE001
            emit("error", f"{type(exc).__name__}: {exc}")
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    return StreamingResponse(drain(produce, queue), media_type="text/event-stream")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
