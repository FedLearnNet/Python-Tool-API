from __future__ import annotations

import random
from pathlib import Path
from typing import Optional, Tuple


def generate_random_image(
    out_path: Path,
    *,
    width: int = 512,
    height: int = 512,
    seed: Optional[int] = None,
    background: Optional[Tuple[int, int, int]] = None,
    add_shapes: bool = True,
    fmt: Optional[str] = None,  # "png" | "jpg" | "webp" | None -> inferred from suffix
) -> Path:
    """
    Generates a random image file (PNG/JPG/WEBP) for test pipelines.

    - Uses Pillow if available.
    - Fallback: writes a binary PPM (portable pixmap) if Pillow is not installed.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(seed)

    # infer format
    if fmt is None:
        suf = out_path.suffix.lower().lstrip(".")
        fmt = suf if suf else "png"
    fmt = fmt.lower()

    try:
        from PIL import Image, ImageDraw  # type: ignore

        # base random pixels or background
        if background is None:
            img = Image.new("RGB", (width, height), (rnd.randint(0, 255), rnd.randint(0, 255), rnd.randint(0, 255)))
        else:
            img = Image.new("RGB", (width, height), background)

        # add some random noise pixels (lightweight)
        px = img.load()
        for _ in range((width * height) // 25):  # ~4% pixels touched
            x = rnd.randrange(0, width)
            y = rnd.randrange(0, height)
            px[x, y] = (rnd.randint(0, 255), rnd.randint(0, 255), rnd.randint(0, 255))

        if add_shapes:
            d = ImageDraw.Draw(img)
            for _ in range(rnd.randint(8, 25)):
                x1, y1 = rnd.randrange(width), rnd.randrange(height)
                x2, y2 = rnd.randrange(width), rnd.randrange(height)
                if x2 < x1:
                    x1, x2 = x2, x1
                if y2 < y1:
                    y1, y2 = y2, y1
                color = (rnd.randint(0, 255), rnd.randint(0, 255), rnd.randint(0, 255))

                shape = rnd.choice(["rect", "ellipse", "line"])
                if shape == "rect":
                    d.rectangle([x1, y1, x2, y2], outline=color, width=rnd.randint(1, 6))
                elif shape == "ellipse":
                    d.ellipse([x1, y1, x2, y2], outline=color, width=rnd.randint(1, 6))
                else:
                    d.line([x1, y1, x2, y2], fill=color, width=rnd.randint(1, 8))

        save_kwargs = {}
        if fmt in ("jpg", "jpeg"):
            save_kwargs["quality"] = 90
            save_kwargs["subsampling"] = 0
        img.save(out_path, format=fmt.upper() if fmt != "jpg" else "JPEG", **save_kwargs)
        return out_path

    except Exception:
        # Fallback: binary PPM (P6) – always writable, but not png/jpg.
        # If user asked for png/jpg and Pillow isn't installed, we still produce an image file.
        ppm_path = out_path.with_suffix(".ppm")
        with ppm_path.open("wb") as f:
            f.write(f"P6\n{width} {height}\n255\n".encode("ascii"))
            for _ in range(width * height):
                f.write(bytes([rnd.randint(0, 255), rnd.randint(0, 255), rnd.randint(0, 255)]))
        return ppm_path