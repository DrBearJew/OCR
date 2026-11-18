"""Image preprocessing for the single-image PaddleOCR-VL ik CPU runtime."""

import base64
import io
import math
import warnings
from pathlib import Path

from PIL import Image

GRID = 28
MIN_PIXELS = 200_704
MAX_PIXELS = 1_003_520


def grid_size(width: int, height: int) -> tuple[int, int]:
    w, h = (max(1, round(n / GRID)) for n in (width, height))
    if w * h * GRID**2 > MAX_PIXELS:
        scale = math.sqrt(MAX_PIXELS / (width * height))
        w, h = (max(1, math.floor(n * scale / GRID)) for n in (width, height))
        # Clamping a very thin dimension to one patch cannot bypass the budget.
        if w * h * GRID**2 > MAX_PIXELS:
            if w > h:
                w = MAX_PIXELS // (h * GRID**2)
            else:
                h = MAX_PIXELS // (w * GRID**2)
    elif w * h * GRID**2 < MIN_PIXELS:
        scale = math.sqrt(MIN_PIXELS / (width * height))
        w, h = (max(1, math.ceil(n * scale / GRID)) for n in (width, height))
        if w * h * GRID**2 > MAX_PIXELS:
            if w > h:
                w = MAX_PIXELS // (h * GRID**2)
            else:
                h = MAX_PIXELS // (w * GRID**2)
    return w * GRID, h * GRID


def image_data_url(path: Path) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(path) as source:
            size = grid_size(*source.size)
            with source.convert("RGB") as rgb, rgb.resize(size, Image.Resampling.BICUBIC) as resized:
                output = io.BytesIO()
                resized.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")
