#!/usr/bin/env python3
"""Render the brand images of the integration from the Housecairn SVG sources.

Sources: src/housecairn/static/img/brand/ of HouseCairn/housecairn
(housecairn-icon.svg, housecairn-logo.svg, housecairn-logo-white.svg).

Usage (needs cairosvg and pillow, not part of the integration):
    python scripts/brand.py <directory with the three SVG files>

Rules: https://github.com/home-assistant/brands#image-specification
icon: square, 256 px (512 px @2x); logo: landscape, 256 px high (512 px @2x);
both trimmed to the artwork, transparent. The dark variants use the white logo.
"""

from __future__ import annotations

import io
import pathlib
import sys

import cairosvg
from PIL import Image

OUT = pathlib.Path(__file__).resolve().parent.parent / "custom_components/housecairn/brand"
RENDER = 2048  # px on the long side, then trimmed and downscaled once


def render(svg: pathlib.Path) -> Image.Image:
    data = cairosvg.svg2png(url=str(svg), output_width=RENDER)
    return Image.open(io.BytesIO(data)).convert("RGBA")


def trimmed(img: Image.Image) -> Image.Image:
    bbox = img.getchannel("A").getbbox()
    if bbox is None:
        raise ValueError("empty image")
    return img.crop(bbox)


def square(img: Image.Image) -> Image.Image:
    side = max(img.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(img, ((side - img.width) // 2, (side - img.height) // 2))
    return canvas


def save(img: Image.Image, name: str, height: int) -> None:
    width = round(img.width * height / img.height)
    out = img.resize((width, height), Image.Resampling.LANCZOS)
    out.save(OUT / name, optimize=True)
    print(f"{name}: {out.width}x{out.height}")


def main(src: pathlib.Path) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    icon = square(trimmed(render(src / "housecairn-icon.svg")))
    logo = trimmed(render(src / "housecairn-logo.svg"))
    dark_logo = trimmed(render(src / "housecairn-logo-white.svg"))
    for suffix, size in (("", 256), ("@2x", 512)):
        save(icon, f"icon{suffix}.png", size)
        save(logo, f"logo{suffix}.png", size)
        save(dark_logo, f"dark_logo{suffix}.png", size)


if __name__ == "__main__":
    main(pathlib.Path(sys.argv[1]))
