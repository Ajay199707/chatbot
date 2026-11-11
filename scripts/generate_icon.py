"""Generate a multi-resolution Windows .ico icon for the Desktop AI Companion."""

from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path
import sys

from PIL import Image
from PySide6 import QtCore, QtWidgets

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import desktop_companion as dc  # noqa: E402


ICON_SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]


def generate_app_icon(output_path: Path, sprite_path: str = "") -> Path:
    """Render Lumi (or a custom sprite) into a crisp multi-size Windows .ico file."""
    app = QtWidgets.QApplication.instance()
    if app is None:
        # Use offscreen platform when running headless if none set
        app = QtWidgets.QApplication([])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pixmap = dc.draw_pet_pixmap(256, sprite_path=sprite_path)

    byte_array = QtCore.QByteArray()
    buf = QtCore.QBuffer(byte_array)
    buf.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buf, "PNG")
    buf.close()

    img = Image.open(BytesIO(bytes(byte_array.data()))).convert("RGBA")
    img.save(output_path, format="ICO", sizes=ICON_SIZES)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate app_icon.ico for Desktop Companion .exe")
    parser.add_argument(
        "--output",
        default=str(ROOT_DIR / "assets" / "app_icon.ico"),
        help="Destination .ico path",
    )
    parser.add_argument("--sprite", default="", help="Optional custom image/sprite path")
    args = parser.parse_args()

    out = generate_app_icon(Path(args.output), sprite_path=args.sprite)
    print(f"Generated icon: {out} ({out.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
