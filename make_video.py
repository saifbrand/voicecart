"""Build the demo video: narration, subtitles and frames, no screen recorder.

Drives the running VoiceCart server, speaks each line with a neural voice,
renders the matching scene for exactly as long as that line takes, burns the
narration in as a subtitle, and muxes it with ffmpeg. Deterministic, so the
video is regenerated after a change rather than re-recorded, and the
conversation on screen is always the one the server actually produced.

    python -m voicecart.server      # in one terminal
    python make_video.py            # in another

Writes submission/voicecart-demo.mp4.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

import edge_tts
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from PIL import Image, ImageDraw, ImageFont

from demo import fresh_start

WIDTH, HEIGHT = 1280, 720
FPS = 15
VOICE = "en-US-AndrewNeural"
RATE = "-4%"

MARGIN = 62
BODY = 21
LINE_H = 29

INK = {
    "bg": (13, 16, 21),
    "chrome": (23, 27, 34),
    "dim": (110, 120, 134),
    "text": (228, 233, 240),
    "accent": (122, 208, 152),
    "warn": (233, 190, 108),
    "you": (110, 194, 232),
    "sub_bg": (8, 10, 13),
    "panel": (26, 31, 39),
}

FONTS = Path("C:/Windows/Fonts")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONTS / ("consolab.ttf" if bold else "consola.ttf")
    return ImageFont.truetype(str(path), size)


# The trip the video walks through, chosen to show the parts that matter.
TRIP = [
    ("Groceries.", "browse_category", {"category": "Groceries"}),
    ("What else is there?", "browse_category", {"category": "Groceries", "offset": 3}),
    ("Show me the home and bath things.", "browse_category",
     {"category": "Home and bath"}),
    ("Add the second one.", "add_to_cart", {"item": "the second one"}),
    ("No, take that back.", "repair", {"said": "take the last one back"}),
    ("Add the third one instead.", "add_to_cart", {"item": "the third one"}),
    ("And nine of the brass lamp.", "add_to_cart",
     {"item": "brass lamp", "quantity": 9}),
    ("Add some cotton.", "add_to_cart", {"item": "cotton"}),
    ("What is in my basket?", "read_cart", {}),
    ("Order it to House 12, Dhanmondi.", "place_order",
     {"address": "House 12, Dhanmondi"}),
    ("Yes.", "place_order", {"address": "House 12, Dhanmondi", "confirmed": True}),
    ("Order the usual again.", "reorder_last", {}),
]


@dataclass
class Line:
    text: str
    colour: tuple[int, int, int]
    indent: bool = False


@dataclass
class Scene:
    say: str
    kind: str
    payload: dict = field(default_factory=dict)


# --- talking to the server -------------------------------------------------

async def capture(url: str) -> tuple[list[Line], dict, list[int]]:
    lines: list[Line] = []
    # Where each exchange ends, so a scene can point at "after the fourth
    # thing they said" instead of a line number that moves when the trip does.
    marks: list[int] = []
    async with streamable_http_client(url) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            tools = await session.list_tools()
            resources = await session.list_resource_templates()
            prompts = await session.list_prompts()

            facts = {
                "protocol": init.protocol_version,
                "tools": len(tools.tools),
                "templates": len(resources.resource_templates) + 1,
                "prompts": len(prompts.prompts),
            }

            for said, tool, args in TRIP:
                lines.append(Line(said, INK["you"]))
                result = await session.call_tool(tool, args)
                reply = result.structured_content or {}
                colour = INK["accent"] if reply.get("ok", True) else INK["warn"]
                for chunk in textwrap.wrap(reply.get("speech", ""), 66) or [""]:
                    lines.append(Line(chunk, colour, indent=True))
                lines.append(Line("", INK["text"]))
                marks.append(len(lines))
            return lines, facts, marks


# --- speech ----------------------------------------------------------------

async def speak(text: str, out: Path) -> None:
    await edge_tts.Communicate(text, VOICE, rate=RATE).save(str(out))


def duration_of(path: Path) -> float:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, check=True)
    return float(json.loads(probe.stdout)["format"]["duration"])


# --- painting --------------------------------------------------------------

def shell(header: str = "") -> Image.Image:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), INK["bg"])
    d = ImageDraw.Draw(canvas)
    d.rectangle([0, 0, WIDTH, 40], fill=INK["chrome"])
    for i, colour in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([22 + i * 22, 14, 34 + i * 22, 26], fill=colour)
    d.text((WIDTH // 2 - 58, 12), "VoiceCart", font=font(16), fill=INK["dim"])
    if header:
        d.text((MARGIN, 62), header, font=font(17), fill=INK["dim"])
    return canvas


def subtitle(canvas: Image.Image, text: str) -> None:
    if not text:
        return
    d = ImageDraw.Draw(canvas)
    rows = textwrap.wrap(text, 74)[:3]
    box = len(rows) * 30 + 26
    d.rectangle([0, HEIGHT - box, WIDTH, HEIGHT], fill=INK["sub_bg"])
    f = font(20)
    y = HEIGHT - box + 14
    for row in rows:
        w = d.textlength(row, font=f)
        d.text(((WIDTH - w) / 2, y), row, font=f, fill=INK["text"])
        y += 30


def conversation(lines: list[Line], upto: int, header: str) -> Image.Image:
    canvas = shell(header)
    d = ImageDraw.Draw(canvas)
    f = font(BODY)
    gutter = d.textlength("you    ", font=f)

    capacity = 13
    window = lines[max(0, upto - capacity):upto]
    y = 110
    for line in window:
        if not line.text:
            y += LINE_H
            continue
        if line.indent:
            d.text((MARGIN + gutter, y), line.text, font=f, fill=line.colour)
        else:
            d.text((MARGIN, y), "you", font=f, fill=INK["dim"])
            d.text((MARGIN + gutter, y), line.text, font=f, fill=line.colour)
        y += LINE_H
    return canvas


def card(title: str, rows: list[str], footer: str = "") -> Image.Image:
    canvas = shell()
    d = ImageDraw.Draw(canvas)
    d.text((MARGIN, 172), title, font=font(42, True), fill=INK["accent"])
    for i, row in enumerate(rows):
        d.text((MARGIN, 258 + i * 38), row, font=font(24), fill=INK["text"])
    if footer:
        d.text((MARGIN, HEIGHT - 150), footer, font=font(20), fill=INK["dim"])
    return canvas


def surface(facts: dict) -> Image.Image:
    canvas = shell()
    d = ImageDraw.Draw(canvas)
    d.text((MARGIN, 150), "More than a tool list", font=font(36, True),
           fill=INK["accent"])
    rows = [
        (f"{facts['tools']} tools", "browse, describe, basket, order, status"),
        (f"{facts['templates']} resources", "read the shop without invoking anything"),
        ("completion", "suggest a department that exists"),
        (f"{facts['prompts']} prompt", "how to run this conversation"),
        ("elicitation", "the shop asks before it orders"),
    ]
    y = 240
    for name, meaning in rows:
        d.rectangle([MARGIN - 14, y - 8, WIDTH - MARGIN, y + 34], fill=INK["panel"])
        d.text((MARGIN, y), f"{name:<14}", font=font(23, True), fill=INK["text"])
        d.text((MARGIN + 220, y), meaning, font=font(21), fill=INK["dim"])
        y += 56
    return canvas


# --- assembly --------------------------------------------------------------

def script(lines: list[Line], facts: dict, marks: list[int]) -> list[Scene]:
    header = (f"MCP protocol {facts['protocol']}   {facts['tools']} tools   "
              f"Streamable HTTP")

    def after(exchange: int):
        """Show the conversation up to the end of the nth thing said."""
        return {"upto": marks[exchange - 1], "header": header}

    return [
        Scene("VoiceCart. A whole storefront you can shop by voice, with no "
              "screen at any point.", "title"),
        Scene("Online shopping assumes you can see. A screen reader makes a "
              "shop operable, but not quick. Measured across seven live "
              "shops: ninety eight words before one product is named. This "
              "finishes a whole order in a hundred and nineteen.", "problem"),
        Scene("So results come three at a time, with a count of what is left, "
              "and the assistant offers rather than continues.",
              "talk", after(1)),
        Scene("And the disqualifying fact is said first. Out of stock lands "
              "before the price, so nobody spends a sentence deciding to buy "
              "something they cannot have.", "talk", after(2)),
        Scene("Nobody says a product code out loud. On a screen you point; in "
              "a conversation you refer back. So the shop remembers the last "
              "list it read you.", "talk", after(3)),
        Scene("Add the second one. Positions, names and a bare that one all "
              "resolve against what was just spoken.", "talk", after(4)),
        Scene("And speech corrects itself. Take that back is its own intent, "
              "and it restores the whole basket rather than reversing an add, "
              "because an add clamped to what was in stock cannot be undone by "
              "subtracting.", "talk", after(6)),
        Scene("It will not oversell either. Nine were asked for, three exist, "
              "and it says so.", "talk", after(7)),
        Scene("When a phrase could mean two products, nothing is added and it "
              "asks which. A wrong item in the basket of somebody who cannot "
              "see it is worse than a second question.", "talk", after(8)),
        Scene("There is no review page to glance at before paying, so one "
              "sentence carries the amount and the address, and nothing else.",
              "talk", after(10)),
        Scene("And the order is never placed on the assistant's own judgement. "
              "If the client can ask, the shop asks through the protocol and "
              "waits.", "talk", after(11)),
        Scene("The basket outlives the conversation, because a voice shopper "
              "has no browser tab to leave open. That is also what makes order "
              "the usual mean something.", "talk", after(12)),
        Scene("Underneath, this uses the rest of MCP, not only tools. "
              "Resources, because reading is not an action. Completion, a "
              "prompt, and elicitation.", "surface"),
        Scene("It runs against a live WooCommerce shop with four settings and "
              "no code changes. Orders are written back as real "
              "cash-on-delivery orders.", "woo"),
        Scene("Seventy five tests. Four drive the whole thing through a real "
              "MCP client over Streamable HTTP. VoiceCart.", "close"),
    ]


def paint(scene: Scene, lines: list[Line], facts: dict) -> Image.Image:
    if scene.kind == "title":
        canvas = card("VoiceCart",
                      ["Shop a whole storefront by voice.",
                       "No screen at any point.",
                       "",
                       "A self-hosted MCP server over Streamable HTTP."],
                      "Amazon Developer Hackathon  .  Alexa+ track")
    elif scene.kind == "problem":
        canvas = card("The problem",
                      ["A screen reader makes a shop operable.",
                       "It does not make it quick.",
                       "",
                       "98 words before a shop names one product.",
                       "119 words for a whole order here.",
                       "",
                       "Median of seven live WooCommerce shops."])
    elif scene.kind == "talk":
        canvas = conversation(lines, scene.payload["upto"], scene.payload["header"])
    elif scene.kind == "surface":
        canvas = surface(facts)
    elif scene.kind == "woo":
        canvas = card("A real shop",
                      ["STORE_SOURCE=woocommerce",
                       "WOO_BASE_URL=https://your-shop.example",
                       "WOO_KEY=ck_...      WOO_SECRET=cs_...",
                       "",
                       "Products read from the shop.",
                       "Orders written back into it."])
    else:
        canvas = card("VoiceCart",
                      ["75 tests. None need an API key.",
                       "Nothing dials, charges or ships without a yes.",
                       "",
                       "One file away from a live store."],
                      "github.com/saifbrand/voicecart")
    subtitle(canvas, scene.say)
    return canvas


def build(url: str, out: Path, work: Path) -> None:
    fresh_start()
    lines, facts, marks = asyncio.run(capture(url))
    work.mkdir(parents=True, exist_ok=True)

    clips, audio = [], []
    scenes = script(lines, facts, marks)
    for index, scene in enumerate(scenes):
        mp3 = work / f"{index:02d}.mp3"
        asyncio.run(speak(scene.say, mp3))
        seconds = duration_of(mp3) + 0.5
        audio.append(mp3)
        clips.append((paint(scene, lines, facts), seconds))
        print(f"  scene {index + 1}/{len(scenes)}  {seconds:4.1f}s  {scene.kind}")

    listing = work / "audio.txt"
    listing.write_text("\n".join(f"file '{p.name}'" for p in audio) + "\n",
                       encoding="utf-8")
    track = work / "narration.mp3"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat",
                    "-safe", "0", "-i", listing.name,
                    "-c:a", "libmp3lame", "-ar", "24000", "-ac", "1", track.name],
                   check=True, cwd=work)

    out.parent.mkdir(parents=True, exist_ok=True)
    silent = work / "silent.mp4"
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-pix_fmt", "yuv420p", str(silent)],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    total = 0
    for image, seconds in clips:
        raw = image.tobytes()
        for _ in range(max(1, int(seconds * FPS))):
            proc.stdin.write(raw)
            total += 1
    proc.stdin.close()
    proc.wait()

    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent),
                    "-i", str(track), "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                    "-shortest", "-movflags", "+faststart", str(out)], check=True)
    print(f"\n{total / FPS:.0f} seconds -> {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080/mcp")
    parser.add_argument("--out", default="submission/voicecart-demo.mp4")
    parser.add_argument("--work", default="submission/.video")
    args = parser.parse_args()
    try:
        build(args.url, Path(args.out), Path(args.work))
    except Exception as exc:  # noqa: BLE001
        print(f"Could not reach {args.url}: {exc}")
        print("Start the server first:  python -m voicecart.server")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
