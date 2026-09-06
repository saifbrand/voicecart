"""Render the YouTube thumbnail: a few big words, readable at small size."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1280, 720
OUT = Path("submission/voicecart-thumbnail.png")

INK = {"bg": (13, 16, 21), "panel": (22, 27, 34), "dim": (118, 128, 142),
       "text": (232, 237, 244), "accent": (122, 208, 152),
       "you": (110, 194, 232), "rule": (44, 52, 63)}

FONTS = Path("C:/Windows/Fonts")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / ("consolab.ttf" if bold else "consola.ttf")), size)


def build() -> None:
    canvas = Image.new("RGB", (W, H), INK["bg"])
    d = ImageDraw.Draw(canvas)

    d.rectangle([0, 92, W, 372], fill=INK["panel"])
    d.line([0, 92, W, 92], fill=INK["rule"], width=2)
    d.line([0, 372, W, 372], fill=INK["rule"], width=2)

    d.text((64, 126), "A WHOLE SHOP,", font=font(70, True), fill=INK["text"])
    d.text((64, 204), "BY VOICE.", font=font(70, True), fill=INK["text"])
    d.text((64, 296), "No screen at any point.", font=font(30), fill=INK["accent"])

    y = 448
    d.text((64, y), "you", font=font(30), fill=INK["dim"])
    d.text((186, y), "Add the second one.", font=font(30), fill=INK["you"])
    d.text((186, y + 52), "Added Cotton hand towel, pair.", font=font(30),
           fill=INK["accent"])

    d.text((64, 616), "MCP over Streamable HTTP  .  built for Alexa+",
           font=font(26), fill=INK["dim"])

    OUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUT)
    print(f"{OUT}  {OUT.stat().st_size // 1024} KB  {W}x{H}")


if __name__ == "__main__":
    build()
