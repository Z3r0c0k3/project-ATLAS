from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageOps

from .naming import normalize_nfc

try:
    from pillow_heif import register_heif_opener
except ImportError:
    register_heif_opener = None
else:
    register_heif_opener()

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic", ".heif"}


def render_media_pages(source: Path, output_dir: Path, max_pages: int = 100) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(normalize_nfc(str(source)).encode("utf-8")).hexdigest()[:12]
    suffix = source.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        target = output_dir / f"{digest}-001.png"
        with Image.open(source) as image:
            normalized = ImageOps.exif_transpose(image)
            if normalized.mode not in {"RGB", "RGBA"}:
                normalized = normalized.convert("RGB")
            normalized.save(target, "PNG", optimize=True)
        return [target]
    if suffix == ".pdf":
        try:
            import fitz
        except ImportError:
            return []
        rendered: list[Path] = []
        document = fitz.open(source)
        try:
            for index, page in enumerate(document):
                if index >= max_pages:
                    break
                target = output_dir / f"{digest}-{index + 1:03d}.png"
                pixmap = page.get_pixmap(matrix=fitz.Matrix(1.8, 1.8), alpha=False)
                pixmap.save(target)
                rendered.append(target)
        finally:
            document.close()
        return rendered
    return []


def image_dimensions(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size
