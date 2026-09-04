"""Render the demo conversation to an MP4, with no screen recorder involved.

Drives a running VoiceCart server, collects what was said on both sides, and
paints it frame by frame into a terminal-looking window, piped straight to
ffmpeg. Deterministic, so the video can be regenerated after a code change
instead of re-recorded.

    python -m voicecart.server      # in one terminal
    python make_video.py            # in another

Writes submission/voicecart-demo.mp4.
"""
from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from PIL import Image, ImageDraw, ImageFont

from demo import TRIP, fresh_start

WIDTH, HEIGHT = 1280, 720
FPS = 15
MARGIN = 56
LINE_HEIGHT = 30
BODY_SIZE = 21
TITLE_SIZE = 44
WRAP = 74

INK = {
    "bg": (14, 17, 22),
    "chrome": (24, 28, 36),
    "dim": (108, 118, 132),
    "you": (108, 196, 232),
    "alexa": (126, 214, 154),
    "warn": (232, 190, 106),
    "text": (226, 231, 238),
    "accent": (126, 214, 154),
}

FONT_DIR = Path("C:/Windows/Fonts")
MONO = FONT_DIR / "consola.ttf"
MONO_BOLD = FONT_DIR / "consolab.ttf"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = MONO_BOLD if bold and MONO_BOLD.exists() else MONO
    if path.exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size)


@dataclass
class Line:
    text: str
    colour: tuple[int, int, int]
    indent: int = 0


async def transcript(url: str) -> tuple[list[Line], str, str]:
    """Run the trip and turn it into lines to paint."""
    lines: list[Line] = []
    async with streamable_http_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = await session.list_tools()

            for said, tool, args in TRIP:
                lines.append(Line(said, INK["you"]))
                result = await session.call_tool(tool, args)
                reply = result.structured_content or {}
                colour = INK["alexa"] if reply.get("ok", True) else INK["warn"]

                shown = ", ".join(f"{k}={v!r}" for k, v in args.items())
                lines.append(Line(f"{tool}({shown})", INK["dim"], indent=1))
                for chunk in textwrap.wrap(reply.get("speech", ""), WRAP) or [""]:
                    lines.append(Line(chunk, colour, indent=1))

                cards = reply.get("cards") or []
                if cards:
                    names = ", ".join(card["title"] for card in cards)
                    label = f"[{len(cards)} card(s) on screen: {names}]"
                    for chunk in textwrap.wrap(label, WRAP):
                        lines.append(Line(chunk, INK["dim"], indent=1))
                lines.append(Line("", INK["text"]))

            return lines, init.protocol_version, str(len(tools.tools))


def frame() -> Image.Image:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), INK["bg"])
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, WIDTH, 40], fill=INK["chrome"])
    for index, colour in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        draw.ellipse([22 + index * 22, 14, 34 + index * 22, 26], fill=colour)
    draw.text((WIDTH // 2 - 60, 12), "VoiceCart", font=font(16), fill=INK["dim"])
    return canvas


def card(title: str, body: list[str], footer: str = "") -> Image.Image:
    canvas = frame()
    draw = ImageDraw.Draw(canvas)
    top = 210
    draw.text((MARGIN + 24, top), title, font=font(TITLE_SIZE, bold=True),
              fill=INK["accent"])
    for index, line in enumerate(body):
        draw.text((MARGIN + 24, top + 86 + index * 36), line, font=font(24),
                  fill=INK["text"])
    if footer:
        draw.text((MARGIN + 24, HEIGHT - 92), footer, font=font(20), fill=INK["dim"])
    return canvas


def conversation(lines: list[Line], upto: int, header: str) -> Image.Image:
    """The terminal, scrolled so the newest line sits near the bottom."""
    canvas = frame()
    draw = ImageDraw.Draw(canvas)
    draw.text((MARGIN, 62), header, font=font(18), fill=INK["dim"])

    body = font(BODY_SIZE)
    capacity = (HEIGHT - 130 - MARGIN) // LINE_HEIGHT
    window = lines[max(0, upto - capacity):upto]

    gutter = draw.textlength("you    ", font=body)
    y = 118
    for line in window:
        if not line.text:
            y += LINE_HEIGHT
            continue
        if line.indent == 0:
            draw.text((MARGIN, y), "you", font=body, fill=INK["dim"])
            draw.text((MARGIN + gutter, y), line.text, font=body, fill=line.colour)
        else:
            draw.text((MARGIN + gutter, y), line.text, font=body, fill=line.colour)
        y += LINE_HEIGHT
    return canvas


def encode(frames, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        ["ffmpeg", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    written = 0
    for image in frames:
        process.stdin.write(image.tobytes())
        written += 1
    process.stdin.close()
    process.wait()
    print(f"{written} frames, {written / FPS:.0f} seconds -> {out}")


def hold(image: Image.Image, seconds: float):
    for _ in range(int(seconds * FPS)):
        yield image


def build(lines: list[Line], protocol: str, tool_count: str, out: Path) -> None:
    header = (f"connected to voicecart 0.1.0   MCP protocol {protocol}   "
              f"{tool_count} tools   Streamable HTTP")

    def frames():
        yield from hold(card(
            "VoiceCart",
            ["Shop a whole storefront by voice.",
             "No screen at any point.",
             "",
             "A self-hosted MCP server over Streamable HTTP."],
            "Amazon Developer Hackathon  .  Alexa+ track",
        ), 4.5)

        yield from hold(card(
            "The problem",
            ["Online shopping assumes you can see.",
             "",
             "A screen reader makes a shop operable, not quick:",
             "you cannot skim a list you have to listen to.",
             "",
             "So this shop is built for listening instead."],
        ), 6.5)

        for index in range(1, len(lines) + 1):
            if not lines[index - 1].text:
                yield from hold(conversation(lines, index, header), 0.45)
            else:
                yield from hold(conversation(lines, index, header), 0.75)

        yield from hold(conversation(lines, len(lines), header), 2.0)

        yield from hold(card(
            "What is underneath",
            ["11 tools, plus resources, completion, a prompt",
             "and elicitation, so the shop asks before it orders.",
             "",
             "Runs against live WooCommerce with four settings.",
             "",
             "43 tests. Nothing dials, charges or ships without a yes."],
            "github.com/saifbrand/voicecart",
        ), 7.0)

    encode(frames(), out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080/mcp")
    parser.add_argument("--out", default="submission/voicecart-demo.mp4")
    args = parser.parse_args()

    fresh_start()
    try:
        lines, protocol, tools = asyncio.run(transcript(args.url))
    except Exception as exc:  # noqa: BLE001
        print(f"Could not reach {args.url}: {exc}")
        print("Start the server first:  python -m voicecart.server")
        raise SystemExit(1)

    build(lines, protocol, tools, Path(args.out))


if __name__ == "__main__":
    main()
