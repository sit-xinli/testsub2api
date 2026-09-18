---
name: generate-image
description: Generate or edit an image with the OpenAI Images API using the credentials in .env. Use whenever an image, picture, illustration, icon, banner, mockup asset, or photo needs to be created or modified from a text prompt - including "make me an image", "generate a picture", "edit this image", "replace the background". Runs the driver at .claude/skills/generate-image/driver.py via uv.
---

# generate-image

Creates images through the OpenAI Images API at the `OPENAI_BASE_URL` proxy in
`.env` (currently `https://www.sunyai.com/sub2api/v1`, model `gpt-image-2`).
The driver is `.claude/skills/generate-image/driver.py`; drive it with `uv run`.
**Every call costs money and takes 30-90 seconds** - generate deliberately, not
speculatively.

All paths below are relative to the repo root (`<unit>/`).

## Prerequisites

`uv` and a populated `.env` at the repo root. Nothing else - no apt packages,
no Pillow, no browser.

```bash
uv sync
```

`.env` must contain (it already does; `.env` is gitignored):

```
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://www.sunyai.com/sub2api/v1
OPENAI_MODEL=gpt-image-2
```

Available image models on this endpoint: `gpt-image-1`, `gpt-image-1.5`,
`gpt-image-2`.

## Run (agent path)

Generate one image to a path you choose:

```bash
uv run .claude/skills/generate-image/driver.py \
  "A wide panoramic banner, 16:9 letterbox, minimal flat vector mountains at dawn" \
  --out images/banner.png
```

```
model: gpt-image-2  base: https://www.sunyai.com/sub2api/v1  n: 1
> A wide panoramic banner, 16:9 letterbox, minimal flat vector mountains at dawn

saved images\banner.png  (1672x941, 1,012,217 bytes)
```

Then **look at what you made** - `Read` the PNG. The API happily returns a
plausible-looking image for a prompt it misread.

### Machine-readable output

`--json` puts a JSON report on stdout and all progress chatter on stderr, so
`... --json | jq -r '.images[].path'` is safe:

```bash
uv run .claude/skills/generate-image/driver.py "a red panda coding" --out images/panda.png --json
```

```json
{
  "model": "gpt-image-2",
  "prompt": "a red panda coding",
  "images": [
    {
      "path": "images\\panda.png",
      "bytes": 2195117,
      "dimensions": "1329x1183",
      "revised_prompt": "a red panda coding"
    }
  ]
}
```

### Several variations

`-n` is looped client-side (the endpoint rejects `n>1` - see Gotchas). Files
become `<stem>-1.png`, `<stem>-2.png`. Cost and time scale linearly:

```bash
uv run .claude/skills/generate-image/driver.py "A tiny origami crane on a wooden desk, soft daylight" \
  -n 2 --out images/crane.png
```

```
saved images\crane-1.png  (1402x1122, 1,645,020 bytes)
saved images\crane-2.png  (1402x1122, 1,778,990 bytes)
```

### Edit an existing image

`--edit` is real image-to-image: it preserves the source composition and
dimensions, changing only what the prompt asks for.

```bash
uv run .claude/skills/generate-image/driver.py \
  "Replace the sky with a dramatic night sky full of stars, keep the mountains" \
  --edit images/banner.png --out images/banner-night.png
```

```
saved images\banner-night.png  (1672x941, 1,605,139 bytes)
```

`--mask mask.png` is accepted for inpainting.

### Long or awkward prompts

Shell quoting mangles prompts containing quotes, `$`, or newlines. Use a file
or stdin instead - both were verified:

```bash
uv run .claude/skills/generate-image/driver.py --prompt-file prompt.txt --out images/out.png
echo "A single smooth grey pebble on white sand, top down" | \
  uv run .claude/skills/generate-image/driver.py --out images/pebble.png
```

### Calling it from outside the repo

`uv` needs to be pointed at the project, or the import of `dotenv` fails:

```bash
uv run --project /c/Users/xinxi/WORKS/testsub2api \
  /c/Users/xinxi/WORKS/testsub2api/.claude/skills/generate-image/driver.py "a blue circle" --out /tmp/c.png
```

## Run (human path)

`image.py` at the repo root is the original demo: `uv run image.py "prompt"`.
It writes a timestamped file into `images/` that you cannot name, and its
`IMAGE_N` env var is broken (see Gotchas). Prefer the driver.

## Gotchas

- **`--size` is ignored by this endpoint.** Requesting `1024x1024` returned
  1254x1254, 1329x1183, and 1448x1086 on three different calls; `1536x1024`
  returned 1254x1254; `auto` returned 1254x1254. The driver prints the *real*
  dimensions it received. If you need exact pixels, resize after the fact.
- **Aspect ratio is steerable through the prompt text, not the parameter.**
  Putting "wide panoramic banner, 16:9 letterbox" in the prompt produced
  1672x941 (= 1.777:1). This is the only lever that works.
- **`n>1` is rejected server-side** with a confusing error that leaks the
  proxy's internals - `400 unknown_parameter: Unknown parameter: 'tools[0].n'`.
  The proxy re-expresses images.generate as a tool call. The driver's `-n`
  therefore loops one request at a time. `image.py`'s `IMAGE_N` env var hits
  this error directly.
- **Responses are always `b64_json`, never `url`,** on this endpoint. A
  ~1MB image arrives as a ~1.2M-character base64 string, so `--json` output is
  small but the HTTP response is not. Requests take 30-90s; the driver's
  timeout is 600s.
- **Bare `load_dotenv()` does not find the repo `.env` reliably** - it resolves
  relative to the *calling script's* directory, so a script run from elsewhere
  silently gets no key and dies with `KeyError: 'OPENAI_API_KEY'`. The driver
  resolves `.env` explicitly: `--env`, then `$CWD/.env`, then upward from the
  driver file. That last rule is why running from `images/` works.
- **`images/` is gitignored.** Generated output is never committed; don't
  expect a teammate to see the file you just made.
- **`quality` is accepted but its effect is unverified.** `--quality low` still
  returned an ~880KB image. Don't count on it to save money.
- **`revised_prompt` came back identical to the input** on every call here, so
  it is not a useful signal about how the prompt was interpreted.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'dotenv'` | You ran `uv run` from outside the repo. Add `--project /c/Users/xinxi/WORKS/testsub2api`. |
| `OPENAI_API_KEY is empty -- checked <path>` (exit 2) | The named `.env` has no key, or an empty `OPENAI_API_KEY` is exported in the shell and shadows it. |
| `400: images endpoint requires an image model, got "..."` (exit 1) | `--model` / `OPENAI_MODEL` is not one of `gpt-image-1`, `gpt-image-1.5`, `gpt-image-2`. |
| `400 unknown_parameter: Unknown parameter: 'tools[0].n'` | Something passed `n>1` to the API. Use the driver's `-n`, which loops. |
| `[error] cannot reach <base url>` (exit 1) | Proxy unreachable. Check `OPENAI_BASE_URL` and the network. |
| Output is the wrong shape | Expected - `size` is ignored. Describe the aspect ratio in the prompt. |
