"""Generate standalone animated looping GIF and PNG avatars for each character.

Saves transparent animated .gif and .png previews into assets/avatars/
so users can inspect, share, or use them as custom sprites.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image
from PySide6 import QtCore, QtGui, QtWidgets

import character_painters


def render_character_frames(character_id: str, frame_count: int = 30, size: int = 140) -> list[Image.Image]:
    """Render a looping cycle of character animation frames using QPainter, returning PIL RGBA Images."""
    pil_frames: list[Image.Image] = []
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)

    for i in range(frame_count):
        # One full cycle of phase (0 to 2*pi)
        phase = (i / frame_count) * (2 * 3.14159)
        # Blink during frames 12-14
        blinking = (12 <= i <= 14)

        img = QtGui.QImage(size, size, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QtCore.Qt.GlobalColor.transparent)

        p = QtGui.QPainter(img)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)

        rect = QtCore.QRectF(4, 4, size - 8, size - 8)
        character_painters.paint_animated_character(
            character_id,
            p,
            rect,
            phase=phase,
            state="idle",
            blinking=blinking,
            look_x=0.0,
            look_y=0.0,
        )
        p.end()

        # Convert QImage to PIL Image
        ptr = img.bits()
        bytes_per_line = img.bytesPerLine()
        raw_bytes = bytes(ptr)
        pil_img = Image.frombuffer("RGBA", (size, size), raw_bytes, "raw", "BGRA", bytes_per_line, 1).convert("RGBA")
        pil_frames.append(pil_img)

    return pil_frames


def generate_all_avatars(output_dir: Path, size: int = 140) -> None:
    """Generate .gif animations and static .png avatars for all character presets."""
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Generating animated avatars in {output_dir}...")

    for cid in character_painters.CHARACTER_PRESETS:
        frames = render_character_frames(cid, frame_count=30, size=size)
        if not frames:
            continue

        # Save static preview PNG (first frame)
        png_path = output_dir / f"{cid}.png"
        frames[0].save(png_path)

        # Save animated GIF
        gif_path = output_dir / f"{cid}.gif"
        # Convert frames for transparent GIF export
        gif_frames = []
        for f in frames:
            # Palettize with alpha preservation
            alpha = f.split()[3]
            p_img = f.convert("RGB").convert("P", palette=Image.Palette.ADAPTIVE, colors=255)
            # Mask transparent pixels
            mask = Image.eval(alpha, lambda a: 255 if a < 128 else 0)
            p_img.paste(255, mask)
            gif_frames.append(p_img)

        gif_frames[0].save(
            gif_path,
            save_all=True,
            append_images=gif_frames[1:],
            duration=40,  # ~25 FPS
            loop=0,
            transparency=255,
            disposal=2,
        )
        print(f"  [OK] {cid}.png and {cid}.gif generated.")

    print("All avatar assets successfully generated!")


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "assets" / "avatars"
    generate_all_avatars(out)
