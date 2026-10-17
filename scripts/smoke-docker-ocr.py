#!/usr/bin/env python3
"""Run inside the backend image with --network none to prove bundled real OCR."""
from pathlib import Path
import tempfile

from PIL import Image, ImageDraw, ImageFont

from app.config import Settings
from app.services.ocr_glm import PPOCRv6Provider

with tempfile.TemporaryDirectory() as directory:
    image = Image.new("RGB", (1000, 220), "white")
    ImageDraw.Draw(image).text((40, 60), "DOC OCR TEST 123", fill="black", font=ImageFont.load_default(size=60))
    path = Path(directory) / "smoke.png"
    image.save(path)
    result = PPOCRv6Provider(Settings(ocr_provider="ppocrv6")).extract_text(str(path))
    assert "".join(result.text.upper().split()) == "DOCOCRTEST123", repr(result.text)
    assert result.raw_response["provider"] == "ppocrv6"
    print("PASS: network-disabled real PP-OCRv6:", result.text)
