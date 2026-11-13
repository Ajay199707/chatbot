"""Character animation renderers for Desktop Companion.

Provides real-time animated vector characters (Lumi, Ben 10 heroes, Gwen Tennyson,
aliens, and anime companions) with blinking eyes, talking mouths, mouse cursor tracking,
and character-specific animated visual FX.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from PySide6 import QtCore, QtGui, QtWidgets


@dataclass
class CharacterPreset:
    id: str
    name: str
    category: str  # "Original Pets", "Ben 10 Universe", "Female Characters"
    accent_color: str
    personality_prompt: str
    description: str
    theme_quote: str = ""
    sprite_path: str = ""


CHARACTER_PRESETS: Dict[str, CharacterPreset] = {
    "lumi": CharacterPreset(
        id="lumi",
        name="Lumi",
        category="Original Pets",
        accent_color="#38bdf8",
        personality_prompt=(
            "You are a cheerful, affectionate, playful little desktop companion who lives on the user's screen. "
            "Keep answers helpful, clear, and warm with occasional gentle charm, without being overly verbose."
        ),
        description="Cute animated desktop spirit kitten who bounces, blinks, and chats with you.",
        theme_quote="Ready to assist you today!",
    ),
    "ben_tennyson": CharacterPreset(
        id="ben_tennyson",
        name="Ben Tennyson",
        category="Ben 10 Universe",
        accent_color="#22c55e",
        personality_prompt=(
            "You are Ben Tennyson, the 10-year-old hero with the Omnitrix from Ben 10. "
            "You are brave, confident, full of energy, witty, and always ready for action. "
            "You treat user requests like exciting hero missions. Keep responses sharp, helpful, "
            "and fun, with iconic catchphrases like 'It\\'s hero time!' when starting tasks."
        ),
        description="Omnitrix hero with green eyes, spiky hair, pulsing Omnitrix dial, and heroic banter.",
        theme_quote="It's hero time!",
    ),
    "gwen_classic": CharacterPreset(
        id="gwen_classic",
        name="Gwen Tennyson",
        category="Ben 10 Universe",
        accent_color="#38bdf8",
        personality_prompt=(
            "You are Gwen Tennyson from Ben 10 (classic era). You are exceptionally smart, resourceful, "
            "organized, and quick-witted. You provide structured, insightful answers with a clever sense "
            "of humor and practical magic/study tips. You keep things running smoothly and logically."
        ),
        description="Clever spellcaster with orange bob hair, blue cat sweater, green eyes, and magic sparkles.",
        theme_quote="Leave the thinking to me.",
    ),
    "gwen_mana": CharacterPreset(
        id="gwen_mana",
        name="Gwen (Mana Form)",
        category="Female Characters",
        accent_color="#d946ef",
        personality_prompt=(
            "You are Gwen Tennyson channeling her cosmic Anodite mana energy. You speak with calm magical wisdom, "
            "protective warmth, and mystical focus. You are deeply knowledgeable, serene, and fiercely protective. "
            "Keep answers clear, elegant, and reassuring, with touches of magical energy."
        ),
        description="Ethereal Anodite form with shimmering magenta mana aura ribbons, shields, and glowing eyes.",
        theme_quote="The energy of the universe is on our side.",
    ),
    "heatblast": CharacterPreset(
        id="heatblast",
        name="Heatblast",
        category="Ben 10 Universe",
        accent_color="#f97316",
        personality_prompt=(
            "You are Heatblast, the fiery Pyronite alien from Ben 10. You speak with a bold, crackling, "
            "warm voice. You are passionate, direct, fearless, and always bring the heat to solve complex problems. "
            "Add subtle fire/warmth metaphors and keep answers exciting and decisive."
        ),
        description="Pyronite alien with magma-rock armor, procedural flickering flame crown, and glowing lava eyes.",
        theme_quote="Let's turn up the heat!",
    ),
    "fourarms": CharacterPreset(
        id="fourarms",
        name="Four Arms",
        category="Ben 10 Universe",
        accent_color="#ef4444",
        personality_prompt=(
            "You are Four Arms, the mighty Tetramand warrior from Ben 10. You are booming, strong, loyal, "
            "and straightforward. You tackle difficult problems with brute determination and high energy. "
            "Keep answers solid, encouraging, and punchy. No task is too heavy for four arms!"
        ),
        description="Red Tetramand warrior with four expressive amber eyes and quadruple arm power flexes.",
        theme_quote="Need some extra muscle?",
    ),
    "xlr8": CharacterPreset(
        id="xlr8",
        name="XLR8",
        category="Ben 10 Universe",
        accent_color="#06b6d4",
        personality_prompt=(
            "You are XLR8, the ultra-fast Kineceleran speedster from Ben 10. You think and speak with "
            "rapid-fire efficiency, laser precision, and high-speed enthusiasm. You love quick summaries, "
            "fast turnarounds, and streamlined productivity. Fast answers, zero wasted seconds!"
        ),
        description="Sleek aerodynamic speed alien with pulsating digital visor, tail sway, and lightning speed.",
        theme_quote="Done before you can even blink!",
    ),
    "anime_sakura": CharacterPreset(
        id="anime_sakura",
        name="Sakura",
        category="Female Characters",
        accent_color="#f472b6",
        personality_prompt=(
            "You are Sakura, a cheerful, caring, sweet anime companion who lives on the desktop. "
            "You speak with gentle warmth, bright enthusiasm, and cute supportive energy. "
            "You love celebrating the user's progress and brightening up their day with helpful assistance."
        ),
        description="Pastel anime companion with twin-tails, sparkling emerald eyes, blush, and kawaii smiles.",
        theme_quote="Let's do our best today!",
    ),
    "cyber_aria": CharacterPreset(
        id="cyber_aria",
        name="Aria",
        category="Female Characters",
        accent_color="#2dd4bf",
        personality_prompt=(
            "You are Aria, an advanced futuristic cybernetic AI assistant with a sleek digital aesthetic. "
            "You are poised, articulate, hyper-competent, and subtly affectionate. You combine cutting-edge tech "
            "precision with a friendly, futuristic presence."
        ),
        description="Futuristic sci-fi companion with glowing holographic eyepiece, neon circuits, and sleek visor.",
        theme_quote="Systems online. How may I optimize your workflow?",
    ),
}


def list_character_categories() -> List[str]:
    """Return unique character categories preserving order."""
    seen: set[str] = set()
    cats: List[str] = ["All"]
    for p in CHARACTER_PRESETS.values():
        if p.category not in seen:
            seen.add(p.category)
            cats.append(p.category)
    return cats


def get_character_preset(preset_id: str) -> CharacterPreset:
    """Return the CharacterPreset for preset_id or fall back to Lumi."""
    clean_id = str(preset_id or "lumi").strip().lower()
    return CHARACTER_PRESETS.get(clean_id, CHARACTER_PRESETS["lumi"])


# ============================================================
# PROCEDURAL ANIMATED PAINTERS (30-60 FPS VECTOR RENDERING)
# ============================================================

def _paint_ground_shadow(p: QtGui.QPainter, bounds: QtCore.QRectF, shadow_scale: float = 1.0) -> None:
    cx = bounds.center().x()
    w = bounds.width()
    h = bounds.height()
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(0, 0, 0, 55))
    p.drawEllipse(QtCore.QPointF(cx, bounds.bottom() - h * 0.05), w * 0.32 * shadow_scale, h * 0.07)


def _paint_cute_pet(
    p: QtGui.QPainter,
    bounds: QtCore.QRectF,
    phase: float,
    state: str,
    blinking: bool,
    look_x: float,
    look_y: float,
) -> None:
    """Paint the built-in cute animated desktop pet (Lumi) inside `bounds`."""
    cx = bounds.center().x()
    cy = bounds.center().y()
    w = bounds.width()
    h = bounds.height()

    shadow_scale = 0.75 if state in ("talking", "happy") else 1.0
    _paint_ground_shadow(p, bounds, shadow_scale)

    bw = w * 0.68
    bh = h * 0.62
    bx = cx - bw / 2
    by = cy - bh / 2 + h * 0.04

    p.save()
    if state == "thinking":
        p.translate(cx, cy)
        p.rotate(math.sin(phase * 2.5) * 6.0)
        p.translate(-cx, -cy)

    # Cat/spirit ears
    ear_grad = QtGui.QLinearGradient(bx, by - bh * 0.25, bx, by + bh * 0.3)
    ear_grad.setColorAt(0.0, QtGui.QColor("#38bdf8"))
    ear_grad.setColorAt(1.0, QtGui.QColor("#2563eb"))
    p.setBrush(ear_grad)
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.022)))

    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(bx + bw * 0.10, by + bh * 0.26),
        QtCore.QPointF(bx + bw * 0.16, by - bh * 0.16),
        QtCore.QPointF(bx + bw * 0.39, by + bh * 0.08),
    ]))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(bx + bw * 0.90, by + bh * 0.26),
        QtCore.QPointF(bx + bw * 0.84, by - bh * 0.16),
        QtCore.QPointF(bx + bw * 0.61, by + bh * 0.08),
    ]))

    # Inner pink ears
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor("#fda4af"))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(bx + bw * 0.16, by + bh * 0.20),
        QtCore.QPointF(bx + bw * 0.19, by - bh * 0.06),
        QtCore.QPointF(bx + bw * 0.33, by + bh * 0.09),
    ]))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(bx + bw * 0.84, by + bh * 0.20),
        QtCore.QPointF(bx + bw * 0.81, by - bh * 0.06),
        QtCore.QPointF(bx + bw * 0.67, by + bh * 0.09),
    ]))

    # Main plush body
    body_grad = QtGui.QRadialGradient(cx - bw * 0.16, by + bh * 0.25, bw * 0.72)
    body_grad.setColorAt(0.0, QtGui.QColor("#7dd3fc"))
    body_grad.setColorAt(0.55, QtGui.QColor("#38bdf8"))
    body_grad.setColorAt(1.0, QtGui.QColor("#1d4ed8"))
    p.setBrush(body_grad)
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.025)))
    p.drawRoundedRect(QtCore.QRectF(bx, by, bw, bh), bw * 0.44, bh * 0.46)

    # Forehead highlight & belly
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(255, 255, 255, 70))
    p.drawEllipse(QtCore.QRectF(bx + bw * 0.22, by + bh * 0.08, bw * 0.38, bh * 0.16))

    p.setBrush(QtGui.QColor(240, 249, 255, 210))
    p.drawEllipse(QtCore.QRectF(cx - bw * 0.27, by + bh * 0.56, bw * 0.54, bh * 0.36))

    # Rosy cheeks
    p.setBrush(QtGui.QColor(251, 113, 133, 165))
    p.drawEllipse(QtCore.QPointF(cx - bw * 0.28, by + bh * 0.52), bw * 0.08, bh * 0.055)
    p.drawEllipse(QtCore.QPointF(cx + bw * 0.28, by + bh * 0.52), bw * 0.08, bh * 0.055)

    # Eyes
    eye_y = by + bh * 0.40
    eye_dx = bw * 0.19
    eye_r = bw * 0.075
    ox = look_x * bw * 0.03
    oy = look_y * bh * 0.03

    if blinking:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.024), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(QtCore.QRectF(cx - eye_dx - eye_r, eye_y - eye_r * 0.4, eye_r * 2, eye_r), 0, 180 * 16)
        p.drawArc(QtCore.QRectF(cx + eye_dx - eye_r, eye_y - eye_r * 0.4, eye_r * 2, eye_r), 0, 180 * 16)
    elif state == "happy":
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.026), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(QtCore.QRectF(cx - eye_dx - eye_r, eye_y - eye_r * 0.5, eye_r * 2, eye_r * 1.2), 15 * 16, 150 * 16)
        p.drawArc(QtCore.QRectF(cx + eye_dx - eye_r, eye_y - eye_r * 0.5, eye_r * 2, eye_r * 1.2), 15 * 16, 150 * 16)
    else:
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        for sign in (-1, 1):
            ex = cx + sign * eye_dx + ox
            ey = eye_y + oy
            p.setBrush(QtGui.QColor("#0f172a"))
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r, eye_r * 1.12)
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawEllipse(QtCore.QPointF(ex - eye_r * 0.32, ey - eye_r * 0.35), eye_r * 0.34, eye_r * 0.34)
            p.drawEllipse(QtCore.QPointF(ex + eye_r * 0.25, ey + eye_r * 0.30), eye_r * 0.16, eye_r * 0.16)

    # Mouth
    mouth_y = by + bh * 0.53
    if state == "talking":
        open_h = bh * (0.06 + 0.045 * abs(math.sin(phase * 14.0)))
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(1.8, w * 0.02)))
        p.setBrush(QtGui.QColor("#fb7185"))
        p.drawEllipse(QtCore.QPointF(cx, mouth_y + open_h * 0.25), bw * 0.065, open_h)
    else:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.022), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawArc(QtCore.QRectF(cx - bw * 0.08, mouth_y - bh * 0.03, bw * 0.08, bh * 0.08), 190 * 16, 160 * 16)
        p.drawArc(QtCore.QRectF(cx, mouth_y - bh * 0.03, bw * 0.08, bh * 0.08), 190 * 16, 160 * 16)

    # Little paws
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.022)))
    p.setBrush(QtGui.QColor("#bae6fd"))
    paw_wave = math.sin(phase * 10.0) * h * 0.035 if state in ("happy", "talking") else 0.0
    p.drawEllipse(QtCore.QPointF(bx + bw * 0.14, by + bh * 0.78 - paw_wave), bw * 0.09, bh * 0.08)
    p.drawEllipse(QtCore.QPointF(bx + bw * 0.86, by + bh * 0.78 + paw_wave), bw * 0.09, bh * 0.08)

    p.restore()

    # Thinking indicator dots above head
    if state == "thinking":
        for idx in range(3):
            bounce = math.sin(phase * 6.0 - idx * 0.9) * h * 0.025
            dx = cx - w * 0.11 + idx * w * 0.11
            dy = bounds.top() + h * 0.11 + bounce
            p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), 1.5))
            p.setBrush(QtGui.QColor("#fde047"))
            p.drawEllipse(QtCore.QPointF(dx, dy), w * 0.04, w * 0.04)


# ============================================================
# BEN TENNYSON (OMNITRIX HERO)
# ============================================================

def _paint_ben_tennyson(
    p: QtGui.QPainter,
    bounds: QtCore.QRectF,
    phase: float,
    state: str,
    blinking: bool,
    look_x: float,
    look_y: float,
) -> None:
    """Paint animated Ben Tennyson with spiky hair, green eyes, Omnitrix glow, and hero gestures."""
    cx = bounds.center().x()
    cy = bounds.center().y()
    w = bounds.width()
    h = bounds.height()

    shadow_scale = 0.8 if state in ("talking", "happy") else 1.0
    _paint_ground_shadow(p, bounds, shadow_scale)

    bw = w * 0.62
    bh = h * 0.65
    bx = cx - bw / 2
    by = cy - bh / 2 + h * 0.05

    p.save()
    if state == "thinking":
        p.translate(cx, cy)
        p.rotate(math.sin(phase * 2.5) * 4.5)
        p.translate(-cx, -cy)

    # Torso / Iconic shirt (White tee with black stripe)
    shirt_rect = QtCore.QRectF(cx - bw * 0.44, by + bh * 0.58, bw * 0.88, bh * 0.45)
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.022)))
    p.setBrush(QtGui.QColor("#f8fafc"))
    p.drawRoundedRect(shirt_rect, bw * 0.18, bw * 0.18)

    # Black stripe down the center of shirt
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor("#0f172a"))
    stripe_w = bw * 0.22
    p.drawRect(QtCore.QRectF(cx - stripe_w / 2, by + bh * 0.58, stripe_w, bh * 0.45))

    # Black collar
    p.drawEllipse(QtCore.QPointF(cx, by + bh * 0.59), bw * 0.20, bh * 0.08)

    # Neck
    p.setBrush(QtGui.QColor("#fcd34d"))  # Warm peach skin
    p.drawRect(QtCore.QRectF(cx - bw * 0.12, by + bh * 0.48, bw * 0.24, bh * 0.14))

    # Head / Face
    head_w = bw * 0.76
    head_h = bh * 0.54
    hx = cx - head_w / 2
    hy = by + bh * 0.06

    skin_grad = QtGui.QLinearGradient(cx, hy, cx, hy + head_h)
    skin_grad.setColorAt(0.0, QtGui.QColor("#fef08a"))
    skin_grad.setColorAt(1.0, QtGui.QColor("#fed7aa"))
    p.setBrush(skin_grad)
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024)))
    p.drawRoundedRect(QtCore.QRectF(hx, hy, head_w, head_h), head_w * 0.42, head_h * 0.44)

    # Spiky brown hair
    hair_color = QtGui.QColor("#5c3317")
    hair_highlight = QtGui.QColor("#78431e")
    p.setBrush(hair_color)
    p.setPen(QtGui.QPen(QtGui.QColor("#2d180a"), max(2.2, w * 0.024)))

    hair_poly = QtGui.QPolygonF([
        QtCore.QPointF(hx - bw * 0.06, hy + head_h * 0.35),
        QtCore.QPointF(hx - bw * 0.14, hy + head_h * 0.05),
        QtCore.QPointF(hx + head_w * 0.10, hy - head_h * 0.16),
        QtCore.QPointF(hx + head_w * 0.32, hy - head_h * 0.28),
        QtCore.QPointF(hx + head_w * 0.58, hy - head_h * 0.18),
        QtCore.QPointF(hx + head_w * 0.88, hy - head_h * 0.24),
        QtCore.QPointF(hx + head_w * 1.12, hy + head_h * 0.08),
        QtCore.QPointF(hx + head_w * 1.06, hy + head_h * 0.38),
        QtCore.QPointF(hx + head_w * 0.90, hy + head_h * 0.22),
        QtCore.QPointF(hx + head_w * 0.65, hy + head_h * 0.26),
        QtCore.QPointF(hx + head_w * 0.35, hy + head_h * 0.20),
        QtCore.QPointF(hx + head_w * 0.12, hy + head_h * 0.28),
    ])
    p.drawPolygon(hair_poly)

    # Hair highlight streak
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(hair_highlight)
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(hx + head_w * 0.25, hy - head_h * 0.14),
        QtCore.QPointF(hx + head_w * 0.40, hy - head_h * 0.22),
        QtCore.QPointF(hx + head_w * 0.48, hy - head_h * 0.12),
        QtCore.QPointF(hx + head_w * 0.32, hy - head_h * 0.06),
    ]))

    # Confident angled eyebrows
    p.setPen(QtGui.QPen(hair_color, max(2.0, w * 0.023), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
    eyebrow_y = hy + head_h * 0.38
    p.drawLine(QtCore.QPointF(cx - head_w * 0.32, eyebrow_y - head_h * 0.02), QtCore.QPointF(cx - head_w * 0.12, eyebrow_y + head_h * 0.02))
    p.drawLine(QtCore.QPointF(cx + head_w * 0.12, eyebrow_y + head_h * 0.02), QtCore.QPointF(cx + head_w * 0.32, eyebrow_y - head_h * 0.02))

    # Eyes (Iconic vibrant green)
    eye_y = hy + head_h * 0.52
    eye_dx = head_w * 0.24
    eye_r = head_w * 0.10
    ox = look_x * head_w * 0.03
    oy = look_y * head_h * 0.03

    if blinking:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.025), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(QtCore.QRectF(cx - eye_dx - eye_r, eye_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
        p.drawArc(QtCore.QRectF(cx + eye_dx - eye_r, eye_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
    elif state == "happy":
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.4, w * 0.028), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(QtCore.QRectF(cx - eye_dx - eye_r, eye_y - eye_r * 0.4, eye_r * 2, eye_r * 1.2), 15 * 16, 150 * 16)
        p.drawArc(QtCore.QRectF(cx + eye_dx - eye_r, eye_y - eye_r * 0.4, eye_r * 2, eye_r * 1.2), 15 * 16, 150 * 16)
    else:
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        for sign in (-1, 1):
            ex = cx + sign * eye_dx + ox
            ey = eye_y + oy
            # Sclera
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r, eye_r * 1.08)
            # Green iris
            p.setBrush(QtGui.QColor("#22c55e"))
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 0.65, eye_r * 0.72)
            # Black pupil
            p.setBrush(QtGui.QColor("#0f172a"))
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 0.36, eye_r * 0.40)
            # Catchlight
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawEllipse(QtCore.QPointF(ex - eye_r * 0.22, ey - eye_r * 0.25), eye_r * 0.22, eye_r * 0.22)

    # Mouth (confident hero smirk or talking mouth)
    mouth_y = hy + head_h * 0.78
    if state == "talking":
        open_h = head_h * (0.07 + 0.05 * abs(math.sin(phase * 14.0)))
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(1.8, w * 0.02)))
        p.setBrush(QtGui.QColor("#e11d48"))
        p.drawEllipse(QtCore.QPointF(cx + head_w * 0.04, mouth_y), head_w * 0.09, open_h)
    else:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawArc(QtCore.QRectF(cx - head_w * 0.08, mouth_y - head_h * 0.04, head_w * 0.22, head_h * 0.12), 200 * 16, 140 * 16)

    # Left wrist with OMNITRIX
    wrist_y = by + bh * 0.76 + (math.sin(phase * 4.0) * h * 0.02 if state == "happy" else 0.0)
    wrist_x = cx - bw * 0.40
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), 2.0))
    p.setBrush(QtGui.QColor("#334155"))  # Grey band
    p.drawRoundedRect(QtCore.QRectF(wrist_x - bw * 0.10, wrist_y - bh * 0.08, bw * 0.20, bh * 0.16), 4, 4)

    # Omnitrix dial base
    p.setBrush(QtGui.QColor("#0f172a"))
    p.drawEllipse(QtCore.QPointF(wrist_x, wrist_y), bw * 0.08, bw * 0.08)

    # Omnitrix pulsing neon green glow
    glow_alpha = int(140 + 100 * abs(math.sin(phase * 4.0)))
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(34, 197, 94, glow_alpha))
    p.drawEllipse(QtCore.QPointF(wrist_x, wrist_y), bw * 0.055, bw * 0.055)

    # Omnitrix hourglass core
    p.setBrush(QtGui.QColor("#0f172a"))
    core_poly = QtGui.QPolygonF([
        QtCore.QPointF(wrist_x - bw * 0.035, wrist_y - bw * 0.035),
        QtCore.QPointF(wrist_x + bw * 0.035, wrist_y + bw * 0.035),
        QtCore.QPointF(wrist_x - bw * 0.035, wrist_y + bw * 0.035),
        QtCore.QPointF(wrist_x + bw * 0.035, wrist_y - bw * 0.035),
    ])
    p.drawPolygon(core_poly)

    p.restore()

    # Thinking state: Spinning holographic green Omnitrix dial above head
    if state == "thinking":
        dial_y = bounds.top() + h * 0.12 + math.sin(phase * 5.0) * h * 0.02
        pulse = 1.0 + 0.12 * math.sin(phase * 6.0)
        dr = w * 0.08 * pulse
        p.setPen(QtGui.QPen(QtGui.QColor("#22c55e"), 1.8))
        p.setBrush(QtGui.QColor(34, 197, 94, 60))
        p.drawEllipse(QtCore.QPointF(cx, dial_y), dr, dr)
        # Hourglass silhouette inside
        p.setBrush(QtGui.QColor("#22c55e"))
        p.drawPolygon(QtGui.QPolygonF([
            QtCore.QPointF(cx - dr * 0.5, dial_y - dr * 0.5),
            QtCore.QPointF(cx + dr * 0.5, dial_y - dr * 0.5),
            QtCore.QPointF(cx - dr * 0.5, dial_y + dr * 0.5),
            QtCore.QPointF(cx + dr * 0.5, dial_y + dr * 0.5),
        ]))


# ============================================================
# GWEN TENNYSON (CLASSIC SPELLCASTER)
# ============================================================

def _paint_gwen_classic(
    p: QtGui.QPainter,
    bounds: QtCore.QRectF,
    phase: float,
    state: str,
    blinking: bool,
    look_x: float,
    look_y: float,
) -> None:
    """Paint Gwen Tennyson (classic) with bright orange bob, cat logo sweater, and magic sparkles."""
    cx = bounds.center().x()
    cy = bounds.center().y()
    w = bounds.width()
    h = bounds.height()

    shadow_scale = 0.8 if state in ("talking", "happy") else 1.0
    _paint_ground_shadow(p, bounds, shadow_scale)

    bw = w * 0.60
    bh = h * 0.64
    bx = cx - bw / 2
    by = cy - bh / 2 + h * 0.05

    p.save()
    if state == "thinking":
        p.translate(cx, cy)
        p.rotate(math.sin(phase * 2.5) * 4.0)
        p.translate(-cx, -cy)

    # Blue sweater
    sweater_rect = QtCore.QRectF(cx - bw * 0.42, by + bh * 0.58, bw * 0.84, bh * 0.45)
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.022)))
    p.setBrush(QtGui.QColor("#0284c7"))  # Vivid blue sweater
    p.drawRoundedRect(sweater_rect, bw * 0.18, bw * 0.18)

    # White collar shirt peeking out
    p.setBrush(QtGui.QColor("#f8fafc"))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(cx - bw * 0.14, by + bh * 0.58),
        QtCore.QPointF(cx, by + bh * 0.66),
        QtCore.QPointF(cx + bw * 0.14, by + bh * 0.58),
    ]))

    # Dark blue stylized cat logo on chest
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor("#0369a1"))
    cat_y = by + bh * 0.74
    p.drawEllipse(QtCore.QPointF(cx, cat_y), bw * 0.10, bh * 0.07)
    p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(cx - bw * 0.08, cat_y - bh * 0.04), QtCore.QPointF(cx - bw * 0.04, cat_y - bh * 0.09), QtCore.QPointF(cx, cat_y - bh * 0.04)]))
    p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(cx, cat_y - bh * 0.04), QtCore.QPointF(cx + bw * 0.04, cat_y - bh * 0.09), QtCore.QPointF(cx + bw * 0.08, cat_y - bh * 0.04)]))

    # Head / Face
    head_w = bw * 0.74
    head_h = bh * 0.52
    hx = cx - head_w / 2
    hy = by + bh * 0.08

    skin_grad = QtGui.QLinearGradient(cx, hy, cx, hy + head_h)
    skin_grad.setColorAt(0.0, QtGui.QColor("#fff7ed"))
    skin_grad.setColorAt(1.0, QtGui.QColor("#ffedd5"))
    p.setBrush(skin_grad)
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024)))
    p.drawRoundedRect(QtCore.QRectF(hx, hy, head_w, head_h), head_w * 0.44, head_h * 0.44)

    # Bright orange hair bob cut
    hair_color = QtGui.QColor("#f97316")
    p.setBrush(hair_color)
    p.setPen(QtGui.QPen(QtGui.QColor("#c2410c"), max(2.2, w * 0.024)))

    hair_poly = QtGui.QPolygonF([
        QtCore.QPointF(hx - bw * 0.10, hy + head_h * 0.72),
        QtCore.QPointF(hx - bw * 0.08, hy + head_h * 0.15),
        QtCore.QPointF(hx + head_w * 0.20, hy - head_h * 0.20),
        QtCore.QPointF(hx + head_w * 0.50, hy - head_h * 0.22),
        QtCore.QPointF(hx + head_w * 0.80, hy - head_h * 0.20),
        QtCore.QPointF(hx + head_w * 1.08, hy + head_h * 0.15),
        QtCore.QPointF(hx + head_w * 1.10, hy + head_h * 0.72),
        QtCore.QPointF(hx + head_w * 0.94, hy + head_h * 0.40),
        QtCore.QPointF(hx + head_w * 0.84, hy + head_h * 0.22),
        QtCore.QPointF(hx + head_w * 0.50, hy + head_h * 0.18),
        QtCore.QPointF(hx + head_w * 0.16, hy + head_h * 0.22),
        QtCore.QPointF(hx - bw * 0.04, hy + head_h * 0.45),
    ])
    p.drawPolygon(hair_poly)

    # Blue hair clip / barrette on right side
    p.setBrush(QtGui.QColor("#38bdf8"))
    p.setPen(QtGui.QPen(QtGui.QColor("#0369a1"), 1.6))
    p.drawRoundedRect(QtCore.QRectF(hx + head_w * 0.78, hy + head_h * 0.12, bw * 0.12, bh * 0.06), 3, 3)

    # Soft blush cheeks
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(251, 113, 133, 140))
    p.drawEllipse(QtCore.QPointF(cx - head_w * 0.28, hy + head_h * 0.62), head_w * 0.09, head_h * 0.06)
    p.drawEllipse(QtCore.QPointF(cx + head_w * 0.28, hy + head_h * 0.62), head_w * 0.09, head_h * 0.06)

    # Expressive green eyes
    eye_y = hy + head_h * 0.48
    eye_dx = head_w * 0.23
    eye_r = head_w * 0.095
    ox = look_x * head_w * 0.03
    oy = look_y * head_h * 0.03

    if blinking:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.025), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(QtCore.QRectF(cx - eye_dx - eye_r, eye_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
        p.drawArc(QtCore.QRectF(cx + eye_dx - eye_r, eye_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
    elif state == "happy":
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.4, w * 0.028), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(QtCore.QRectF(cx - eye_dx - eye_r, eye_y - eye_r * 0.4, eye_r * 2, eye_r * 1.2), 15 * 16, 150 * 16)
        p.drawArc(QtCore.QRectF(cx + eye_dx - eye_r, eye_y - eye_r * 0.4, eye_r * 2, eye_r * 1.2), 15 * 16, 150 * 16)
    else:
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        for sign in (-1, 1):
            ex = cx + sign * eye_dx + ox
            ey = eye_y + oy
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r, eye_r * 1.1)
            p.setBrush(QtGui.QColor("#16a34a"))  # Emerald green
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 0.68, eye_r * 0.75)
            p.setBrush(QtGui.QColor("#0f172a"))
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 0.35, eye_r * 0.40)
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawEllipse(QtCore.QPointF(ex - eye_r * 0.22, ey - eye_r * 0.25), eye_r * 0.24, eye_r * 0.24)

    # Mouth
    mouth_y = hy + head_h * 0.74
    if state == "talking":
        open_h = head_h * (0.06 + 0.045 * abs(math.sin(phase * 14.0)))
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(1.8, w * 0.02)))
        p.setBrush(QtGui.QColor("#fb7185"))
        p.drawEllipse(QtCore.QPointF(cx, mouth_y), head_w * 0.08, open_h)
    else:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.022), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawArc(QtCore.QRectF(cx - head_w * 0.07, mouth_y - head_h * 0.03, head_w * 0.14, head_h * 0.08), 200 * 16, 140 * 16)

    p.restore()

    # Magic sparkle stars when thinking or happy
    if state in ("thinking", "happy"):
        for i in range(4):
            sparkle_angle = phase * 3.0 + i * (math.pi / 2)
            dist = w * 0.32 + math.sin(phase * 4.0 + i) * w * 0.04
            sx = cx + math.cos(sparkle_angle) * dist
            sy = cy - h * 0.15 + math.sin(sparkle_angle) * (dist * 0.4)
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(56, 189, 248, 190))
            p.drawEllipse(QtCore.QPointF(sx, sy), w * 0.03, w * 0.03)


# ============================================================
# GWEN TENNYSON (MANA MAGIC / ANODITE FORM)
# ============================================================

def _paint_gwen_mana(
    p: QtGui.QPainter,
    bounds: QtCore.QRectF,
    phase: float,
    state: str,
    blinking: bool,
    look_x: float,
    look_y: float,
) -> None:
    """Paint Gwen in her cosmic Anodite mana form with swirling magenta energy ribbons."""
    cx = bounds.center().x()
    cy = bounds.center().y()
    w = bounds.width()
    h = bounds.height()

    shadow_scale = 0.7 if state in ("talking", "happy") else 0.9
    _paint_ground_shadow(p, bounds, shadow_scale)

    bw = w * 0.60
    bh = h * 0.65
    bx = cx - bw / 2
    by = cy - bh / 2 + h * 0.04

    p.save()
    if state == "thinking":
        p.translate(cx, cy)
        p.rotate(math.sin(phase * 2.2) * 5.0)
        p.translate(-cx, -cy)

    # Cosmic Anodite body glow (Deep magenta to violet)
    body_grad = QtGui.QRadialGradient(cx, by + bh * 0.45, bw * 0.65)
    body_grad.setColorAt(0.0, QtGui.QColor("#f472b6"))
    body_grad.setColorAt(0.4, QtGui.QColor("#d946ef"))
    body_grad.setColorAt(1.0, QtGui.QColor("#701a75"))
    p.setBrush(body_grad)
    p.setPen(QtGui.QPen(QtGui.QColor("#fdf4ff"), max(2.2, w * 0.024)))
    p.drawRoundedRect(QtCore.QRectF(bx + bw * 0.10, by + bh * 0.18, bw * 0.80, bh * 0.80), bw * 0.38, bh * 0.40)

    # Flowing cosmic hair tendrils
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(232, 121, 249, 180))
    for idx, offset in enumerate([-0.28, -0.10, 0.10, 0.28]):
        sway = math.sin(phase * 3.0 + idx * 1.1) * bw * 0.08
        hair_x = cx + offset * bw
        hair_y = by - bh * 0.08
        p.drawEllipse(QtCore.QPointF(hair_x + sway, hair_y), bw * 0.18, bh * 0.24)

    # Head
    head_w = bw * 0.70
    head_h = bh * 0.50
    hx = cx - head_w / 2
    hy = by + bh * 0.10
    p.setBrush(QtGui.QColor("#c026d3"))
    p.setPen(QtGui.QPen(QtGui.QColor("#fdf4ff"), max(2.0, w * 0.022)))
    p.drawRoundedRect(QtCore.QRectF(hx, hy, head_w, head_h), head_w * 0.44, head_h * 0.44)

    # Glowing mana eyes (Luminous violet-white)
    eye_y = hy + head_h * 0.46
    eye_dx = head_w * 0.23
    eye_r = head_w * 0.09
    ox = look_x * head_w * 0.03
    oy = look_y * head_h * 0.03

    if blinking:
        p.setPen(QtGui.QPen(QtGui.QColor("#fdf4ff"), max(2.4, w * 0.026), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(QtCore.QRectF(cx - eye_dx - eye_r, eye_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
        p.drawArc(QtCore.QRectF(cx + eye_dx - eye_r, eye_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
    else:
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        for sign in (-1, 1):
            ex = cx + sign * eye_dx + ox
            ey = eye_y + oy
            # Outer aura
            p.setBrush(QtGui.QColor(244, 114, 182, 160))
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 1.3, eye_r * 1.3)
            # Glowing core
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 0.75, eye_r * 0.75)

    # Mouth
    mouth_y = hy + head_h * 0.72
    if state == "talking":
        open_h = head_h * (0.06 + 0.045 * abs(math.sin(phase * 14.0)))
        p.setPen(QtGui.QPen(QtGui.QColor("#fdf4ff"), 1.8))
        p.setBrush(QtGui.QColor("#f472b6"))
        p.drawEllipse(QtCore.QPointF(cx, mouth_y), head_w * 0.075, open_h)
    else:
        p.setPen(QtGui.QPen(QtGui.QColor("#fdf4ff"), 2.0, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawArc(QtCore.QRectF(cx - head_w * 0.06, mouth_y - head_h * 0.03, head_w * 0.12, head_h * 0.08), 200 * 16, 140 * 16)

    # Swirling dynamic MANA RIBBONS (undulating sinusoidal energy rings)
    p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
    for i in range(3):
        ribbon_phase = phase * 3.5 + i * 2.1
        rx = cx + math.sin(ribbon_phase) * bw * 0.35
        ry = cy + math.cos(ribbon_phase * 0.8) * bh * 0.28
        rw = bw * (0.35 + 0.10 * math.sin(ribbon_phase))
        rh = bh * (0.16 + 0.06 * math.cos(ribbon_phase))
        p.setPen(QtGui.QPen(QtGui.QColor(244, 114, 182, 175), 2.2))
        p.drawEllipse(QtCore.QPointF(rx, ry), rw, rh)

    p.restore()

    # Hexagonal mana shield when thinking
    if state == "thinking":
        shield_r = w * 0.38
        p.setPen(QtGui.QPen(QtGui.QColor(232, 121, 249, 210), 2.0))
        p.setBrush(QtGui.QColor(232, 121, 249, 45))
        hex_points: List[QtCore.QPointF] = []
        for i in range(6):
            angle = phase * 1.5 + i * (math.pi / 3)
            hex_points.append(QtCore.QPointF(cx + math.cos(angle) * shield_r, cy + math.sin(angle) * shield_r))
        p.drawPolygon(QtGui.QPolygonF(hex_points))


# ============================================================
# HEATBLAST (PYRONITE FLAME)
# ============================================================

def _paint_heatblast(
    p: QtGui.QPainter,
    bounds: QtCore.QRectF,
    phase: float,
    state: str,
    blinking: bool,
    look_x: float,
    look_y: float,
) -> None:
    """Paint Heatblast with dark magma armor, glowing lava cracks, and flickering procedural flame crown."""
    cx = bounds.center().x()
    cy = bounds.center().y()
    w = bounds.width()
    h = bounds.height()

    shadow_scale = 0.8 if state in ("talking", "happy") else 1.0
    _paint_ground_shadow(p, bounds, shadow_scale)

    bw = w * 0.64
    bh = h * 0.64
    bx = cx - bw / 2
    by = cy - bh / 2 + h * 0.06

    p.save()
    if state == "thinking":
        p.translate(cx, cy)
        p.rotate(math.sin(phase * 2.5) * 4.0)
        p.translate(-cx, -cy)

    # Magma collar / shoulders
    collar_rect = QtCore.QRectF(cx - bw * 0.45, by + bh * 0.54, bw * 0.90, bh * 0.46)
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024)))
    p.setBrush(QtGui.QColor("#1e293b"))  # Charcoal magma rock
    p.drawRoundedRect(collar_rect, bw * 0.20, bw * 0.20)

    # Molten lava cracks on collar
    p.setPen(QtGui.QPen(QtGui.QColor("#f97316"), max(2.0, w * 0.022), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
    p.drawLine(QtCore.QPointF(cx - bw * 0.28, by + bh * 0.68), QtCore.QPointF(cx - bw * 0.12, by + bh * 0.78))
    p.drawLine(QtCore.QPointF(cx - bw * 0.12, by + bh * 0.78), QtCore.QPointF(cx, by + bh * 0.72))
    p.drawLine(QtCore.QPointF(cx, by + bh * 0.72), QtCore.QPointF(cx + bw * 0.18, by + bh * 0.82))
    p.drawLine(QtCore.QPointF(cx + bw * 0.18, by + bh * 0.82), QtCore.QPointF(cx + bw * 0.32, by + bh * 0.70))

    # Magma head shape
    head_w = bw * 0.72
    head_h = bh * 0.48
    hx = cx - head_w / 2
    hy = by + bh * 0.12

    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024)))
    p.setBrush(QtGui.QColor("#334155"))  # Charcoal rock head
    p.drawRoundedRect(QtCore.QRectF(hx, hy, head_w, head_h), head_w * 0.38, head_h * 0.40)

    # Mask plate (yellow magma core face)
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor("#f59e0b"))
    p.drawRoundedRect(QtCore.QRectF(hx + head_w * 0.12, hy + head_h * 0.18, head_w * 0.76, head_h * 0.70), head_w * 0.28, head_h * 0.28)

    # PROCEDURAL FLAME CROWN (Multi-layered flickering fire tongues)
    flame_height = bh * (0.38 + 0.10 * math.sin(phase * 8.0))
    if state == "happy":
        flame_height *= 1.35

    # 1. Outer deep red flame layer
    p.setBrush(QtGui.QColor(220, 38, 38, 220))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(hx - bw * 0.04, hy + head_h * 0.25),
        QtCore.QPointF(hx + head_w * 0.15, hy - flame_height * 0.7 + math.sin(phase * 7.0) * bh * 0.05),
        QtCore.QPointF(hx + head_w * 0.50, hy - flame_height + math.sin(phase * 9.0) * bh * 0.06),
        QtCore.QPointF(hx + head_w * 0.85, hy - flame_height * 0.75 + math.cos(phase * 8.0) * bh * 0.05),
        QtCore.QPointF(hx + head_w * 1.04, hy + head_h * 0.25),
        QtCore.QPointF(hx + head_w * 0.50, hy + head_h * 0.10),
    ]))

    # 2. Middle radiant orange flame layer
    p.setBrush(QtGui.QColor(249, 115, 22, 235))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(hx + head_w * 0.08, hy + head_h * 0.20),
        QtCore.QPointF(hx + head_w * 0.30, hy - flame_height * 0.65 + math.cos(phase * 9.0) * bh * 0.04),
        QtCore.QPointF(hx + head_w * 0.50, hy - flame_height * 0.85 + math.sin(phase * 11.0) * bh * 0.04),
        QtCore.QPointF(hx + head_w * 0.70, hy - flame_height * 0.60 + math.sin(phase * 8.5) * bh * 0.04),
        QtCore.QPointF(hx + head_w * 0.92, hy + head_h * 0.20),
    ]))

    # 3. Core hot yellow flame tongue
    p.setBrush(QtGui.QColor(254, 240, 138, 245))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(hx + head_w * 0.25, hy + head_h * 0.16),
        QtCore.QPointF(hx + head_w * 0.50, hy - flame_height * 0.55 + math.sin(phase * 12.0) * bh * 0.03),
        QtCore.QPointF(hx + head_w * 0.75, hy + head_h * 0.16),
    ]))

    # Fiery eyes (angled glowing magma slits)
    eye_y = hy + head_h * 0.44
    eye_dx = head_w * 0.22
    eye_r = head_w * 0.09
    ox = look_x * head_w * 0.03
    oy = look_y * head_h * 0.03

    if blinking:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.025), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawLine(QtCore.QPointF(cx - eye_dx - eye_r, eye_y), QtCore.QPointF(cx - eye_dx + eye_r, eye_y))
        p.drawLine(QtCore.QPointF(cx + eye_dx - eye_r, eye_y), QtCore.QPointF(cx + eye_dx + eye_r, eye_y))
    else:
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        for sign in (-1, 1):
            ex = cx + sign * eye_dx + ox
            ey = eye_y + oy
            # Fiery outer glow
            p.setBrush(QtGui.QColor("#ea580c"))
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 1.1, eye_r * 0.8)
            # Bright yellow core
            p.setBrush(QtGui.QColor("#fef08a"))
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 0.65, eye_r * 0.50)

    # Mouth (ember glow opening)
    mouth_y = hy + head_h * 0.72
    if state == "talking":
        open_h = head_h * (0.07 + 0.05 * abs(math.sin(phase * 14.0)))
        p.setPen(QtGui.QPen(QtGui.QColor("#7c2d12"), 2.0))
        p.setBrush(QtGui.QColor("#ea580c"))
        p.drawEllipse(QtCore.QPointF(cx, mouth_y), head_w * 0.09, open_h)
    else:
        p.setPen(QtGui.QPen(QtGui.QColor("#7c2d12"), 2.2, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawArc(QtCore.QRectF(cx - head_w * 0.08, mouth_y - head_h * 0.03, head_w * 0.16, head_h * 0.09), 200 * 16, 140 * 16)

    p.restore()

    # Rising ember sparks when idle/thinking
    spark_count = 5 if state == "thinking" else 3
    for idx in range(spark_count):
        spark_y = bounds.top() + h * 0.20 - ((phase * 40.0 + idx * 35.0) % (h * 0.35))
        spark_x = cx - w * 0.15 + (idx * 0.08 * w) + math.sin(phase * 4.0 + idx) * w * 0.04
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        p.setBrush(QtGui.QColor(251, 146, 60, 210))
        p.drawEllipse(QtCore.QPointF(spark_x, spark_y), w * 0.025, w * 0.025)


# ============================================================
# FOUR ARMS (TETRAMAND WARRIOR)
# ============================================================

def _paint_fourarms(
    p: QtGui.QPainter,
    bounds: QtCore.QRectF,
    phase: float,
    state: str,
    blinking: bool,
    look_x: float,
    look_y: float,
) -> None:
    """Paint Four Arms with red muscular body, 4 amber eyes, black head stripe, and quadruple arms."""
    cx = bounds.center().x()
    cy = bounds.center().y()
    w = bounds.width()
    h = bounds.height()

    shadow_scale = 0.85 if state in ("talking", "happy") else 1.1
    _paint_ground_shadow(p, bounds, shadow_scale)

    bw = w * 0.68
    bh = h * 0.65
    bx = cx - bw / 2
    by = cy - bh / 2 + h * 0.05

    p.save()
    if state == "thinking":
        p.translate(cx, cy)
        p.rotate(math.sin(phase * 2.2) * 4.0)
        p.translate(-cx, -cy)

    # 4 ARMS (Two upper arms, two lower arms)
    arm_wave = math.sin(phase * 8.0) * h * 0.04 if state in ("talking", "happy") else 0.0

    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024)))
    p.setBrush(QtGui.QColor("#dc2626"))  # Deep red skin

    # Upper left & right arms
    p.drawEllipse(QtCore.QPointF(cx - bw * 0.44, by + bh * 0.42 - arm_wave), bw * 0.14, bh * 0.16)
    p.drawEllipse(QtCore.QPointF(cx + bw * 0.44, by + bh * 0.42 + arm_wave), bw * 0.14, bh * 0.16)

    # Lower left & right arms
    p.drawEllipse(QtCore.QPointF(cx - bw * 0.42, by + bh * 0.68 + arm_wave), bw * 0.13, bh * 0.15)
    p.drawEllipse(QtCore.QPointF(cx + bw * 0.42, by + bh * 0.68 - arm_wave), bw * 0.13, bh * 0.15)

    # Gold arm cuffs
    p.setBrush(QtGui.QColor("#f59e0b"))
    p.drawRect(QtCore.QRectF(cx - bw * 0.49, by + bh * 0.48 - arm_wave, bw * 0.10, bh * 0.06))
    p.drawRect(QtCore.QRectF(cx + bw * 0.39, by + bh * 0.48 + arm_wave, bw * 0.10, bh * 0.06))

    # Muscular torso
    torso_rect = QtCore.QRectF(cx - bw * 0.38, by + bh * 0.52, bw * 0.76, bh * 0.48)
    p.setBrush(QtGui.QColor("#dc2626"))
    p.drawRoundedRect(torso_rect, bw * 0.18, bw * 0.18)

    # White and black gladiator vest
    p.setBrush(QtGui.QColor("#f8fafc"))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(cx - bw * 0.28, by + bh * 0.52),
        QtCore.QPointF(cx, by + bh * 0.75),
        QtCore.QPointF(cx + bw * 0.28, by + bh * 0.52),
    ]))
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor("#0f172a"))
    p.drawRect(QtCore.QRectF(cx - bw * 0.06, by + bh * 0.52, bw * 0.12, bh * 0.48))

    # Red head
    head_w = bw * 0.70
    head_h = bh * 0.50
    hx = cx - head_w / 2
    hy = by + bh * 0.08

    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024)))
    p.setBrush(QtGui.QColor("#dc2626"))
    p.drawRoundedRect(QtCore.QRectF(hx, hy, head_w, head_h), head_w * 0.36, head_h * 0.38)

    # Iconic black warrior stripe down center of forehead
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor("#0f172a"))
    p.drawRect(QtCore.QRectF(cx - head_w * 0.07, hy, head_w * 0.14, head_h * 0.58))

    # FOUR AMBER EYES (Upper pair and lower pair)
    eye_r = head_w * 0.075
    ox = look_x * head_w * 0.025
    oy = look_y * head_h * 0.025

    # 1. Upper eye pair
    upper_y = hy + head_h * 0.35
    upper_dx = head_w * 0.25

    # 2. Lower eye pair
    lower_y = hy + head_h * 0.52
    lower_dx = head_w * 0.21

    if blinking:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.025), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(QtCore.QRectF(cx - upper_dx - eye_r, upper_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
        p.drawArc(QtCore.QRectF(cx + upper_dx - eye_r, upper_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
        p.drawArc(QtCore.QRectF(cx - lower_dx - eye_r, lower_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
        p.drawArc(QtCore.QRectF(cx + lower_dx - eye_r, lower_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
    else:
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        for (ey_base, edx) in [(upper_y, upper_dx), (lower_y, lower_dx)]:
            for sign in (-1, 1):
                ex = cx + sign * edx + ox
                ey = ey_base + oy
                p.setBrush(QtGui.QColor("#fef3c7"))  # Sclera
                p.drawEllipse(QtCore.QPointF(ex, ey), eye_r, eye_r * 1.08)
                p.setBrush(QtGui.QColor("#f59e0b"))  # Amber iris
                p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 0.65, eye_r * 0.70)
                p.setBrush(QtGui.QColor("#0f172a"))  # Pupil
                p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 0.35, eye_r * 0.38)
                p.setBrush(QtGui.QColor("#ffffff"))
                p.drawEllipse(QtCore.QPointF(ex - eye_r * 0.20, ey - eye_r * 0.22), eye_r * 0.22, eye_r * 0.22)

    # Wide warrior mouth
    mouth_y = hy + head_h * 0.76
    if state == "talking":
        open_h = head_h * (0.07 + 0.05 * abs(math.sin(phase * 14.0)))
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.022)))
        p.setBrush(QtGui.QColor("#991b1b"))
        p.drawEllipse(QtCore.QPointF(cx, mouth_y), head_w * 0.12, open_h)
    else:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawArc(QtCore.QRectF(cx - head_w * 0.11, mouth_y - head_h * 0.04, head_w * 0.22, head_h * 0.10), 200 * 16, 140 * 16)

    p.restore()


# ============================================================
# XLR8 (KINECELERAN SPEEDSTER)
# ============================================================

def _paint_xlr8(
    p: QtGui.QPainter,
    bounds: QtCore.QRectF,
    phase: float,
    state: str,
    blinking: bool,
    look_x: float,
    look_y: float,
) -> None:
    """Paint XLR8 with sleek aerodynamic black/cyan helmet, pulsating green visor, and tail sway."""
    cx = bounds.center().x()
    cy = bounds.center().y()
    w = bounds.width()
    h = bounds.height()

    shadow_scale = 0.75 if state in ("talking", "happy") else 0.95
    _paint_ground_shadow(p, bounds, shadow_scale)

    bw = w * 0.62
    bh = h * 0.64
    bx = cx - bw / 2
    by = cy - bh / 2 + h * 0.05

    p.save()
    if state == "thinking":
        p.translate(cx, cy)
        p.rotate(math.sin(phase * 2.8) * 4.0)
        p.translate(-cx, -cy)

    # Pointed tail swishing in the back
    tail_sway = math.sin(phase * 2.5) * bw * 0.14
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024)))
    p.setBrush(QtGui.QColor("#06b6d4"))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(cx + bw * 0.20, by + bh * 0.70),
        QtCore.QPointF(cx + bw * 0.45 + tail_sway, by + bh * 0.85),
        QtCore.QPointF(cx + bw * 0.15, by + bh * 0.88),
    ]))

    # Sleek aerodynamic body / suit
    suit_rect = QtCore.QRectF(cx - bw * 0.38, by + bh * 0.54, bw * 0.76, bh * 0.46)
    p.setBrush(QtGui.QColor("#0f172a"))
    p.drawRoundedRect(suit_rect, bw * 0.18, bw * 0.18)

    # Cyan racing stripes on torso
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor("#06b6d4"))
    p.drawRect(QtCore.QRectF(cx - bw * 0.14, by + bh * 0.54, bw * 0.08, bh * 0.46))
    p.drawRect(QtCore.QRectF(cx + bw * 0.06, by + bh * 0.54, bw * 0.08, bh * 0.46))

    # Pointed aerodynamic helmet
    head_w = bw * 0.72
    head_h = bh * 0.52
    hx = cx - head_w / 2
    hy = by + bh * 0.08

    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024)))
    p.setBrush(QtGui.QColor("#0f172a"))

    helmet_poly = QtGui.QPolygonF([
        QtCore.QPointF(hx - bw * 0.06, hy + head_h * 0.40),
        QtCore.QPointF(hx + head_w * 0.50, hy - head_h * 0.28),  # Pointed rear crest
        QtCore.QPointF(hx + head_w * 1.06, hy + head_h * 0.40),
        QtCore.QPointF(hx + head_w * 0.90, hy + head_h * 0.90),
        QtCore.QPointF(hx + head_w * 0.10, hy + head_h * 0.90),
    ])
    p.drawPolygon(helmet_poly)

    # Cyan helmet cheek accents
    p.setBrush(QtGui.QColor("#06b6d4"))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(hx + head_w * 0.10, hy + head_h * 0.45),
        QtCore.QPointF(hx + head_w * 0.25, hy + head_h * 0.15),
        QtCore.QPointF(hx + head_w * 0.25, hy + head_h * 0.65),
    ]))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(hx + head_w * 0.90, hy + head_h * 0.45),
        QtCore.QPointF(hx + head_w * 0.75, hy + head_h * 0.15),
        QtCore.QPointF(hx + head_w * 0.75, hy + head_h * 0.65),
    ]))

    # PULSATING GREEN ELECTRONIC VISOR
    visor_rect = QtCore.QRectF(hx + head_w * 0.16, hy + head_h * 0.42, head_w * 0.68, head_h * 0.28)
    if blinking:
        p.setPen(QtGui.QPen(QtGui.QColor("#065f46"), 1.8))
        p.setBrush(QtGui.QColor("#0f172a"))
        p.drawRoundedRect(visor_rect, 4, 4)
    else:
        # Visor glow
        glow_val = int(180 + 75 * math.sin(phase * 4.0))
        p.setPen(QtGui.QPen(QtGui.QColor(34, 197, 94, 255), 1.6))
        p.setBrush(QtGui.QColor(34, 197, 94, glow_val))
        p.drawRoundedRect(visor_rect, 4, 4)

        # High-tech scanline sweep
        scan_x = visor_rect.left() + ((phase * 120.0) % visor_rect.width())
        p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 2.0))
        p.drawLine(QtCore.QPointF(scan_x, visor_rect.top() + 2), QtCore.QPointF(scan_x, visor_rect.bottom() - 2))

    # Sleek mouth opening
    mouth_y = hy + head_h * 0.78
    if state == "talking":
        open_h = head_h * (0.05 + 0.04 * abs(math.sin(phase * 14.0)))
        p.setPen(QtGui.QPen(QtGui.QColor("#06b6d4"), 1.8))
        p.setBrush(QtGui.QColor("#0f172a"))
        p.drawEllipse(QtCore.QPointF(cx, mouth_y), head_w * 0.08, open_h)

    p.restore()

    # Speed trails when happy or talking
    if state in ("happy", "talking"):
        for i in range(3):
            trail_y = cy - h * 0.10 + i * h * 0.12
            trail_x = cx - w * 0.38 - math.sin(phase * 5.0 + i) * w * 0.08
            p.setPen(QtGui.QPen(QtGui.QColor(6, 182, 212, 160), 2.0))
            p.drawLine(QtCore.QPointF(trail_x, trail_y), QtCore.QPointF(trail_x + w * 0.14, trail_y))


# ============================================================
# ANIME SAKURA (CHEERFUL FEMALE COMPANION)
# ============================================================

def _paint_anime_sakura(
    p: QtGui.QPainter,
    bounds: QtCore.QRectF,
    phase: float,
    state: str,
    blinking: bool,
    look_x: float,
    look_y: float,
) -> None:
    """Paint Anime Sakura with pink twin-tails, sparkling emerald eyes, blush, and cute expressions."""
    cx = bounds.center().x()
    cy = bounds.center().y()
    w = bounds.width()
    h = bounds.height()

    shadow_scale = 0.8 if state in ("talking", "happy") else 1.0
    _paint_ground_shadow(p, bounds, shadow_scale)

    bw = w * 0.60
    bh = h * 0.64
    bx = cx - bw / 2
    by = cy - bh / 2 + h * 0.05

    p.save()
    if state == "thinking":
        p.translate(cx, cy)
        p.rotate(math.sin(phase * 2.5) * 4.5)
        p.translate(-cx, -cy)

    # Twin-tails swaying behind the head
    tail_sway_l = math.sin(phase * 2.2) * bw * 0.08
    tail_sway_r = math.cos(phase * 2.2) * bw * 0.08
    p.setPen(QtGui.QPen(QtGui.QColor("#db2777"), max(2.0, w * 0.022)))
    p.setBrush(QtGui.QColor("#f472b6"))  # Pastel pink hair

    # Left twin-tail
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(cx - bw * 0.35, by + bh * 0.18),
        QtCore.QPointF(cx - bw * 0.60 + tail_sway_l, by + bh * 0.40),
        QtCore.QPointF(cx - bw * 0.52 + tail_sway_l, by + bh * 0.75),
        QtCore.QPointF(cx - bw * 0.25, by + bh * 0.35),
    ]))
    # Right twin-tail
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(cx + bw * 0.35, by + bh * 0.18),
        QtCore.QPointF(cx + bw * 0.60 + tail_sway_r, by + bh * 0.40),
        QtCore.QPointF(cx + bw * 0.52 + tail_sway_r, by + bh * 0.75),
        QtCore.QPointF(cx + bw * 0.25, by + bh * 0.35),
    ]))

    # Cute sailor collar / blouse
    blouse_rect = QtCore.QRectF(cx - bw * 0.40, by + bh * 0.58, bw * 0.80, bh * 0.44)
    p.setBrush(QtGui.QColor("#ffffff"))
    p.drawRoundedRect(blouse_rect, bw * 0.18, bw * 0.18)

    # Pink sailor tie / bow
    p.setBrush(QtGui.QColor("#ec4899"))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(cx - bw * 0.10, by + bh * 0.62),
        QtCore.QPointF(cx, by + bh * 0.72),
        QtCore.QPointF(cx + bw * 0.10, by + bh * 0.62),
    ]))

    # Head / Face
    head_w = bw * 0.74
    head_h = bh * 0.52
    hx = cx - head_w / 2
    hy = by + bh * 0.08

    skin_grad = QtGui.QLinearGradient(cx, hy, cx, hy + head_h)
    skin_grad.setColorAt(0.0, QtGui.QColor("#fff5f5"))
    skin_grad.setColorAt(1.0, QtGui.QColor("#fed7aa"))
    p.setBrush(skin_grad)
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024)))
    p.drawRoundedRect(QtCore.QRectF(hx, hy, head_w, head_h), head_w * 0.44, head_h * 0.44)

    # Front bangs (Pink anime hair)
    p.setBrush(QtGui.QColor("#f472b6"))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(hx - bw * 0.04, hy + head_h * 0.35),
        QtCore.QPointF(hx + head_w * 0.15, hy - head_h * 0.18),
        QtCore.QPointF(hx + head_w * 0.50, hy - head_h * 0.22),
        QtCore.QPointF(hx + head_w * 0.85, hy - head_h * 0.18),
        QtCore.QPointF(hx + head_w * 1.04, hy + head_h * 0.35),
        QtCore.QPointF(hx + head_w * 0.80, hy + head_h * 0.25),
        QtCore.QPointF(hx + head_w * 0.55, hy + head_h * 0.32),
        QtCore.QPointF(hx + head_w * 0.45, hy + head_h * 0.20),
        QtCore.QPointF(hx + head_w * 0.25, hy + head_h * 0.28),
    ]))

    # Rosy blush circles
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(251, 113, 133, 160))
    p.drawEllipse(QtCore.QPointF(cx - head_w * 0.28, hy + head_h * 0.62), head_w * 0.09, head_h * 0.06)
    p.drawEllipse(QtCore.QPointF(cx + head_w * 0.28, hy + head_h * 0.62), head_w * 0.09, head_h * 0.06)

    # Sparkling anime eyes
    eye_y = hy + head_h * 0.48
    eye_dx = head_w * 0.24
    eye_r = head_w * 0.10
    ox = look_x * head_w * 0.03
    oy = look_y * head_h * 0.03

    if blinking:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.025), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(QtCore.QRectF(cx - eye_dx - eye_r, eye_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
        p.drawArc(QtCore.QRectF(cx + eye_dx - eye_r, eye_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
    elif state == "happy":
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.4, w * 0.028), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(QtCore.QRectF(cx - eye_dx - eye_r, eye_y - eye_r * 0.4, eye_r * 2, eye_r * 1.2), 15 * 16, 150 * 16)
        p.drawArc(QtCore.QRectF(cx + eye_dx - eye_r, eye_y - eye_r * 0.4, eye_r * 2, eye_r * 1.2), 15 * 16, 150 * 16)
    else:
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        for sign in (-1, 1):
            ex = cx + sign * eye_dx + ox
            ey = eye_y + oy
            # Sclera
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r, eye_r * 1.15)
            # Emerald green anime iris
            p.setBrush(QtGui.QColor("#10b981"))
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 0.72, eye_r * 0.85)
            # Dark pupil
            p.setBrush(QtGui.QColor("#064e3b"))
            p.drawEllipse(QtCore.QPointF(ex, ey + eye_r * 0.1), eye_r * 0.38, eye_r * 0.45)
            # Double glossy highlights
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawEllipse(QtCore.QPointF(ex - eye_r * 0.25, ey - eye_r * 0.28), eye_r * 0.28, eye_r * 0.28)
            p.drawEllipse(QtCore.QPointF(ex + eye_r * 0.20, ey + eye_r * 0.25), eye_r * 0.15, eye_r * 0.15)

    # Mouth
    mouth_y = hy + head_h * 0.74
    if state == "talking":
        open_h = head_h * (0.06 + 0.045 * abs(math.sin(phase * 14.0)))
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(1.8, w * 0.02)))
        p.setBrush(QtGui.QColor("#fb7185"))
        p.drawEllipse(QtCore.QPointF(cx, mouth_y), head_w * 0.075, open_h)
    else:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.022), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawArc(QtCore.QRectF(cx - head_w * 0.06, mouth_y - head_h * 0.03, head_w * 0.12, head_h * 0.08), 200 * 16, 140 * 16)

    p.restore()

    # Floating hearts/stars when happy
    if state == "happy":
        for i in range(3):
            heart_phase = phase * 4.0 + i * 2.0
            hx_pos = cx - w * 0.25 + i * (w * 0.25)
            hy_pos = bounds.top() + h * 0.12 + math.sin(heart_phase) * h * 0.03
            p.setPen(QtCore.Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(244, 114, 182, 220))
            p.drawEllipse(QtCore.QPointF(hx_pos, hy_pos), w * 0.035, w * 0.035)


# ============================================================
# CYBER ARIA (FUTURISTIC AI COMPANION)
# ============================================================

def _paint_cyber_aria(
    p: QtGui.QPainter,
    bounds: QtCore.QRectF,
    phase: float,
    state: str,
    blinking: bool,
    look_x: float,
    look_y: float,
) -> None:
    """Paint Aria with futuristic teal bob, holographic visor eyepiece, and glowing cyber circuits."""
    cx = bounds.center().x()
    cy = bounds.center().y()
    w = bounds.width()
    h = bounds.height()

    shadow_scale = 0.8 if state in ("talking", "happy") else 1.0
    _paint_ground_shadow(p, bounds, shadow_scale)

    bw = w * 0.60
    bh = h * 0.64
    bx = cx - bw / 2
    by = cy - bh / 2 + h * 0.05

    p.save()
    if state == "thinking":
        p.translate(cx, cy)
        p.rotate(math.sin(phase * 2.2) * 4.0)
        p.translate(-cx, -cy)

    # Cyber jacket / suit
    jacket_rect = QtCore.QRectF(cx - bw * 0.40, by + bh * 0.58, bw * 0.80, bh * 0.44)
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.022)))
    p.setBrush(QtGui.QColor("#1e293b"))  # Dark sleek jacket
    p.drawRoundedRect(jacket_rect, bw * 0.18, bw * 0.18)

    # Neon teal trim lines
    p.setPen(QtGui.QPen(QtGui.QColor("#2dd4bf"), max(1.8, w * 0.02)))
    p.drawLine(QtCore.QPointF(cx - bw * 0.20, by + bh * 0.58), QtCore.QPointF(cx - bw * 0.10, by + bh * 0.98))
    p.drawLine(QtCore.QPointF(cx + bw * 0.20, by + bh * 0.58), QtCore.QPointF(cx + bw * 0.10, by + bh * 0.98))

    # Head / Face
    head_w = bw * 0.74
    head_h = bh * 0.52
    hx = cx - head_w / 2
    hy = by + bh * 0.08

    skin_grad = QtGui.QLinearGradient(cx, hy, cx, hy + head_h)
    skin_grad.setColorAt(0.0, QtGui.QColor("#f8fafc"))
    skin_grad.setColorAt(1.0, QtGui.QColor("#e2e8f0"))
    p.setBrush(skin_grad)
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024)))
    p.drawRoundedRect(QtCore.QRectF(hx, hy, head_w, head_h), head_w * 0.44, head_h * 0.44)

    # Cyber bob hair (Teal/Cyan)
    p.setBrush(QtGui.QColor("#0d9488"))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(hx - bw * 0.08, hy + head_h * 0.65),
        QtCore.QPointF(hx - bw * 0.06, hy + head_h * 0.15),
        QtCore.QPointF(hx + head_w * 0.20, hy - head_h * 0.18),
        QtCore.QPointF(hx + head_w * 0.50, hy - head_h * 0.20),
        QtCore.QPointF(hx + head_w * 0.80, hy - head_h * 0.18),
        QtCore.QPointF(hx + head_w * 1.06, hy + head_h * 0.15),
        QtCore.QPointF(hx + head_w * 1.08, hy + head_h * 0.65),
        QtCore.QPointF(hx + head_w * 0.90, hy + head_h * 0.30),
        QtCore.QPointF(hx + head_w * 0.50, hy + head_h * 0.20),
        QtCore.QPointF(hx + head_w * 0.10, hy + head_h * 0.30),
    ]))

    # Eyes
    eye_y = hy + head_h * 0.48
    eye_dx = head_w * 0.24
    eye_r = head_w * 0.095
    ox = look_x * head_w * 0.03
    oy = look_y * head_h * 0.03

    if blinking:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.025), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(QtCore.QRectF(cx - eye_dx - eye_r, eye_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
        p.drawArc(QtCore.QRectF(cx + eye_dx - eye_r, eye_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
    else:
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        for sign in (-1, 1):
            ex = cx + sign * eye_dx + ox
            ey = eye_y + oy
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r, eye_r * 1.1)
            p.setBrush(QtGui.QColor("#14b8a6"))  # Teal iris
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 0.68, eye_r * 0.75)
            p.setBrush(QtGui.QColor("#0f172a"))
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 0.35, eye_r * 0.40)
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawEllipse(QtCore.QPointF(ex - eye_r * 0.22, ey - eye_r * 0.25), eye_r * 0.24, eye_r * 0.24)

    # Holographic cyber eyepiece over left eye
    eyepiece_rect = QtCore.QRectF(cx - eye_dx - eye_r * 1.3, eye_y - eye_r * 1.2, eye_r * 2.6, eye_r * 2.4)
    p.setPen(QtGui.QPen(QtGui.QColor("#2dd4bf"), 1.8))
    p.setBrush(QtGui.QColor(45, 212, 191, 55))
    p.drawRoundedRect(eyepiece_rect, 4, 4)

    # Mouth
    mouth_y = hy + head_h * 0.74
    if state == "talking":
        open_h = head_h * (0.06 + 0.045 * abs(math.sin(phase * 14.0)))
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(1.8, w * 0.02)))
        p.setBrush(QtGui.QColor("#2dd4bf"))
        p.drawEllipse(QtCore.QPointF(cx, mouth_y), head_w * 0.075, open_h)
    else:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.022), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawArc(QtCore.QRectF(cx - head_w * 0.06, mouth_y - head_h * 0.03, head_w * 0.12, head_h * 0.08), 200 * 16, 140 * 16)

    p.restore()

    # Floating rotating cyber HUD ring when thinking
    if state == "thinking":
        hud_r = w * 0.32
        p.setPen(QtGui.QPen(QtGui.QColor(45, 212, 191, 190), 1.6, QtCore.Qt.PenStyle.DashLine))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawEllipse(QtCore.QPointF(cx, cy), hud_r, hud_r * 0.6)


# ============================================================
# MAIN DISPATCHER FUNCTION
# ============================================================

_PAINTER_MAP = {
    "lumi": _paint_cute_pet,
    "ben_tennyson": _paint_ben_tennyson,
    "gwen_classic": _paint_gwen_classic,
    "gwen_mana": _paint_gwen_mana,
    "heatblast": _paint_heatblast,
    "fourarms": _paint_fourarms,
    "xlr8": _paint_xlr8,
    "anime_sakura": _paint_anime_sakura,
    "cyber_aria": _paint_cyber_aria,
}


def paint_animated_character(
    character_id: str,
    p: QtGui.QPainter,
    bounds: QtCore.QRectF,
    phase: float = 0.0,
    state: str = "idle",
    blinking: bool = False,
    look_x: float = 0.0,
    look_y: float = 0.0,
) -> None:
    """Paint the specified character vector inside `bounds`."""
    cid = str(character_id or "lumi").strip().lower()
    painter = _PAINTER_MAP.get(cid, _paint_cute_pet)
    painter(p, bounds, phase, state, blinking, look_x, look_y)


def draw_character_pixmap(
    size: int = 64,
    character_id: str = "lumi",
    sprite_path: str = "",
) -> QtGui.QPixmap:
    """Create a rendered thumbnail pixmap for tray icon, header avatar, or gallery cards."""
    if sprite_path and Path(sprite_path).is_file():
        pm = QtGui.QPixmap(sprite_path)
        if not pm.isNull():
            return pm.scaled(
                size,
                size,
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )

    pm = QtGui.QPixmap(size, size)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform)
    paint_animated_character(
        character_id,
        p,
        QtCore.QRectF(3, 3, size - 6, size - 6),
        phase=0.0,
        state="idle",
        blinking=False,
        look_x=0.0,
        look_y=0.0,
    )
    p.end()
    return pm
