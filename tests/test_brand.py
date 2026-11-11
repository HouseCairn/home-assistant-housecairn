"""The brand images must stay: Home Assistant 2026.3+ reads them from the integration."""

from __future__ import annotations

import pathlib

import pytest
from PIL import Image

BRAND = pathlib.Path(__file__).parent.parent / "custom_components" / "housecairn" / "brand"

# name: (width, height) for icons; logos are landscape, height only.
ICONS = {"icon.png": 256, "icon@2x.png": 512}
LOGOS = {
    "logo.png": 256,
    "logo@2x.png": 512,
    "dark_logo.png": 256,
    "dark_logo@2x.png": 512,
}


@pytest.mark.parametrize(("name", "side"), ICONS.items())
def test_icon(name: str, side: int) -> None:
    with Image.open(BRAND / name) as img:
        assert img.format == "PNG"
        assert img.mode == "RGBA"
        assert img.size == (side, side)
        assert img.getpixel((0, 0))[3] == 0


@pytest.mark.parametrize(("name", "height"), LOGOS.items())
def test_logo(name: str, height: int) -> None:
    with Image.open(BRAND / name) as img:
        assert img.format == "PNG"
        assert img.mode == "RGBA"
        assert img.height == height
        assert img.width > img.height
        assert img.getpixel((img.width - 1, img.height - 1))[3] == 0


def test_no_unexpected_files() -> None:
    assert {p.name for p in BRAND.iterdir()} == set(ICONS) | set(LOGOS)
