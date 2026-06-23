#!/usr/bin/env python3
"""Generate raster logo.png and favicon.ico from the simplified logo."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "static"

NAV_BG = (57, 75, 88, 255)  # #394B58 — Canvas global nav tone
WHITE = (255, 255, 255, 255)


def draw_logo(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = max(2, size // 8)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=NAV_BG)

    def sx(x: float) -> int:
        return round(x * size / 64)

    def sy(y: float) -> int:
        return round(y * size / 64)

    draw.polygon(
        [(sx(32), sy(14)), (sx(54), sy(25)), (sx(32), sy(36)), (sx(10), sy(25))],
        fill=WHITE,
    )
    draw.rectangle((sx(18), sy(28), sx(46), sy(36)), fill=WHITE)
    return img


def main() -> None:
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    draw_logo(64).save(STATIC_DIR / "logo.png")

    favicon_sizes = [(16, 16), (32, 32), (48, 48)]
    favicon_images = [draw_logo(s) for s, _ in favicon_sizes]
    favicon_images[0].save(
        STATIC_DIR / "favicon.ico",
        format="ICO",
        sizes=favicon_sizes,
        append_images=favicon_images[1:],
    )
    print(f"Wrote {STATIC_DIR / 'logo.png'} and {STATIC_DIR / 'favicon.ico'}")


if __name__ == "__main__":
    main()
