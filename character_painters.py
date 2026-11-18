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

def _paint_ground_shadow(
    p: QtGui.QPainter,
    bounds: QtCore.QRectF,
    shadow_scale: float = 1.0,
    look_x: float = 0.0,
    look_y: float = 0.0,
) -> None:
    """Paint a soft feathered 3D volumetric ground contact shadow with perspective skew."""
    cx = bounds.center().x()
    w = bounds.width()
    h = bounds.height()

    # 3D perspective skew: ground shadow shifts slightly with character lean and gaze
    shadow_cx = cx - look_x * w * 0.035
    shadow_cy = bounds.bottom() - h * 0.048 - look_y * h * 0.012
    rx = w * 0.35 * shadow_scale
    ry = h * 0.078 * shadow_scale

    p.save()
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    shadow_grad = QtGui.QRadialGradient(shadow_cx, shadow_cy, rx)
    shadow_grad.setColorAt(0.0, QtGui.QColor(15, 23, 42, 110))
    shadow_grad.setColorAt(0.40, QtGui.QColor(15, 23, 42, 65))
    shadow_grad.setColorAt(0.75, QtGui.QColor(15, 23, 42, 20))
    shadow_grad.setColorAt(1.0, QtGui.QColor(15, 23, 42, 0))
    p.setBrush(shadow_grad)
    p.drawEllipse(QtCore.QPointF(shadow_cx, shadow_cy), rx, ry)
    p.restore()


def _paint_cute_pet(
    p: QtGui.QPainter,
    bounds: QtCore.QRectF,
    phase: float,
    state: str,
    blinking: bool,
    look_x: float,
    look_y: float,
) -> None:
    """Paint the built-in cute desktop pet (Lumi) with 2.5D volumetric shading and multi-plane parallax depth."""
    cx = bounds.center().x()
    cy = bounds.center().y()
    w = bounds.width()
    h = bounds.height()

    shadow_scale = 0.75 if state in ("talking", "happy") else 1.0
    _paint_ground_shadow(p, bounds, shadow_scale, look_x, look_y)

    bw = w * 0.68
    bh = h * 0.62
    bx = cx - bw / 2
    by = cy - bh / 2 + h * 0.04

    # Parallax plane offsets
    # Back plane (z = -0.4): moves opposite gaze
    bg_ox = -look_x * bw * 0.045
    bg_oy = -look_y * bh * 0.035
    # Front plane (z = +0.65): moves towards gaze
    fg_ox = look_x * bw * 0.065
    fg_oy = look_y * bh * 0.048

    p.save()
    if state == "thinking":
        p.translate(cx, cy)
        p.rotate(math.sin(phase * 2.5) * 6.0)
        p.translate(-cx, -cy)
    else:
        # Subtle 3D perspective roll towards cursor
        p.translate(cx, cy)
        p.rotate(look_x * 3.5)
        p.translate(-cx, -cy)

    # 1. Back Layer (Ears in depth plane z = -0.4)
    ear_grad = QtGui.QLinearGradient(bx + bg_ox, by + bg_oy - bh * 0.25, bx + bg_ox, by + bg_oy + bh * 0.3)
    ear_grad.setColorAt(0.0, QtGui.QColor("#7dd3fc"))
    ear_grad.setColorAt(0.4, QtGui.QColor("#38bdf8"))
    ear_grad.setColorAt(1.0, QtGui.QColor("#1d4ed8"))
    p.setBrush(ear_grad)
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.022)))

    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(bx + bg_ox + bw * 0.10, by + bg_oy + bh * 0.26),
        QtCore.QPointF(bx + bg_ox + bw * 0.16, by + bg_oy - bh * 0.16),
        QtCore.QPointF(bx + bg_ox + bw * 0.39, by + bg_oy + bh * 0.08),
    ]))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(bx + bg_ox + bw * 0.90, by + bg_oy + bh * 0.26),
        QtCore.QPointF(bx + bg_ox + bw * 0.84, by + bg_oy - bh * 0.16),
        QtCore.QPointF(bx + bg_ox + bw * 0.61, by + bg_oy + bh * 0.08),
    ]))

    # Inner recessed ears with soft pink depth gradient
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    inner_ear_grad = QtGui.QLinearGradient(bx + bg_ox, by + bg_oy - bh * 0.08, bx + bg_ox, by + bg_oy + bh * 0.22)
    inner_ear_grad.setColorAt(0.0, QtGui.QColor("#f43f5e"))
    inner_ear_grad.setColorAt(1.0, QtGui.QColor("#fda4af"))
    p.setBrush(inner_ear_grad)
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(bx + bg_ox + bw * 0.16, by + bg_oy + bh * 0.20),
        QtCore.QPointF(bx + bg_ox + bw * 0.19, by + bg_oy - bh * 0.06),
        QtCore.QPointF(bx + bg_ox + bw * 0.33, by + bg_oy + bh * 0.09),
    ]))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(bx + bg_ox + bw * 0.84, by + bg_oy + bh * 0.20),
        QtCore.QPointF(bx + bg_ox + bw * 0.81, by + bg_oy - bh * 0.06),
        QtCore.QPointF(bx + bg_ox + bw * 0.67, by + bg_oy + bh * 0.09),
    ]))

    # 2. Mid Layer: Volumetric 3D Spherical Body
    light_cx = cx - bw * 0.18 + look_x * bw * 0.05
    light_cy = by + bh * 0.22 + look_y * bh * 0.05
    body_grad = QtGui.QRadialGradient(light_cx, light_cy, bw * 0.78)
    body_grad.setColorAt(0.0, QtGui.QColor("#bae6fd"))  # Specular apex
    body_grad.setColorAt(0.32, QtGui.QColor("#7dd3fc"))
    body_grad.setColorAt(0.68, QtGui.QColor("#38bdf8"))
    body_grad.setColorAt(0.90, QtGui.QColor("#2563eb"))
    body_grad.setColorAt(1.0, QtGui.QColor("#1e3a8a"))  # Deep ambient occlusion edge
    p.setBrush(body_grad)
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.025)))
    p.drawRoundedRect(QtCore.QRectF(bx, by, bw, bh), bw * 0.44, bh * 0.46)

    # 3D Specular Vinyl Gloss Glint (upper-left curved sheen)
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    glint_grad = QtGui.QLinearGradient(bx + bw * 0.18, by + bh * 0.06, bx + bw * 0.38, by + bh * 0.22)
    glint_grad.setColorAt(0.0, QtGui.QColor(255, 255, 255, 175))
    glint_grad.setColorAt(0.55, QtGui.QColor(255, 255, 255, 75))
    glint_grad.setColorAt(1.0, QtGui.QColor(255, 255, 255, 0))
    p.setBrush(glint_grad)
    p.drawEllipse(QtCore.QRectF(bx + bw * 0.20, by + bh * 0.07, bw * 0.34, bh * 0.15))

    # 3D Desktop Rim Bounce Light (subtle lower rim reflection)
    rim_grad = QtGui.QLinearGradient(cx, by + bh * 0.85, cx, by + bh)
    rim_grad.setColorAt(0.0, QtGui.QColor(186, 230, 253, 0))
    rim_grad.setColorAt(1.0, QtGui.QColor(186, 230, 253, 70))
    p.setBrush(rim_grad)
    p.drawRoundedRect(QtCore.QRectF(bx + bw * 0.12, by + bh * 0.70, bw * 0.76, bh * 0.28), bw * 0.38, bh * 0.38)

    # 3. Mid-Front Layer: 3D Belly Pillow (with parallax offset)
    belly_cx = cx + fg_ox * 0.45
    belly_cy = by + bh * 0.58 + fg_oy * 0.35
    belly_w = bw * 0.54
    belly_h = bh * 0.36
    belly_grad = QtGui.QRadialGradient(belly_cx - belly_w * 0.15, belly_cy - belly_h * 0.15, belly_w * 0.55)
    belly_grad.setColorAt(0.0, QtGui.QColor("#ffffff"))
    belly_grad.setColorAt(0.70, QtGui.QColor(240, 249, 255, 235))
    belly_grad.setColorAt(1.0, QtGui.QColor(219, 234, 254, 210))
    p.setBrush(belly_grad)
    p.drawEllipse(QtCore.QRectF(belly_cx - belly_w / 2, belly_cy - belly_h / 2, belly_w, belly_h))

    # Rosy Cheeks (on front facial parallax plane)
    cheek_y = by + bh * 0.52 + fg_oy
    for sign in (-1, 1):
        cheek_x = cx + sign * (bw * 0.28) + fg_ox
        chk_grad = QtGui.QRadialGradient(cheek_x, cheek_y, bw * 0.08)
        chk_grad.setColorAt(0.0, QtGui.QColor(251, 113, 133, 190))
        chk_grad.setColorAt(0.7, QtGui.QColor(251, 113, 133, 90))
        chk_grad.setColorAt(1.0, QtGui.QColor(251, 113, 133, 0))
        p.setBrush(chk_grad)
        p.drawEllipse(QtCore.QPointF(cheek_x, cheek_y), bw * 0.08, bh * 0.055)

    # 4. Foreground Layer: 3D Eyes & Glass Depth (z = +0.65)
    eye_y = by + bh * 0.40 + fg_oy
    eye_dx = bw * 0.19
    eye_r = bw * 0.076

    if blinking:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(QtCore.QRectF(cx - eye_dx + fg_ox - eye_r, eye_y - eye_r * 0.4, eye_r * 2, eye_r), 0, 180 * 16)
        p.drawArc(QtCore.QRectF(cx + eye_dx + fg_ox - eye_r, eye_y - eye_r * 0.4, eye_r * 2, eye_r), 0, 180 * 16)
    elif state == "happy":
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.4, w * 0.026), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(QtCore.QRectF(cx - eye_dx + fg_ox - eye_r, eye_y - eye_r * 0.5, eye_r * 2, eye_r * 1.2), 15 * 16, 150 * 16)
        p.drawArc(QtCore.QRectF(cx + eye_dx + fg_ox - eye_r, eye_y - eye_r * 0.5, eye_r * 2, eye_r * 1.2), 15 * 16, 150 * 16)
    else:
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        for sign in (-1, 1):
            ex = cx + sign * eye_dx + fg_ox
            ey = eye_y

            # 3D Eye socket & deep glossy pupil
            socket_grad = QtGui.QRadialGradient(ex, ey + eye_r * 0.2, eye_r * 1.1)
            socket_grad.setColorAt(0.0, QtGui.QColor("#1e293b"))
            socket_grad.setColorAt(1.0, QtGui.QColor("#0f172a"))
            p.setBrush(socket_grad)
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r, eye_r * 1.14)

            # Vivid 3D iris crescent at lower half
            iris_grad = QtGui.QLinearGradient(ex, ey, ex, ey + eye_r * 1.1)
            iris_grad.setColorAt(0.0, QtGui.QColor("#0284c7"))
            iris_grad.setColorAt(1.0, QtGui.QColor("#38bdf8"))
            p.setBrush(iris_grad)
            p.drawEllipse(QtCore.QRectF(ex - eye_r * 0.72, ey, eye_r * 1.44, eye_r * 0.95))

            # Deep dark pupil core
            p.setBrush(QtGui.QColor("#020617"))
            p.drawEllipse(QtCore.QPointF(ex, ey + eye_r * 0.15), eye_r * 0.44, eye_r * 0.50)

            # Stationary 3D corneal catchlight (anchored to top-left light source!)
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawEllipse(QtCore.QPointF(ex - eye_r * 0.32, ey - eye_r * 0.32), eye_r * 0.32, eye_r * 0.32)
            # Secondary micro gloss
            p.setBrush(QtGui.QColor(255, 255, 255, 190))
            p.drawEllipse(QtCore.QPointF(ex + eye_r * 0.26, ey + eye_r * 0.28), eye_r * 0.16, eye_r * 0.16)

    # Mouth (front facial plane with fg_ox, fg_oy)
    mouth_y = by + bh * 0.53 + fg_oy
    mouth_x = cx + fg_ox
    if state == "talking":
        open_h = bh * (0.06 + 0.045 * abs(math.sin(phase * 14.0)))
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(1.8, w * 0.02)))
        p.setBrush(QtGui.QColor("#fb7185"))
        p.drawEllipse(QtCore.QPointF(mouth_x, mouth_y + open_h * 0.25), bw * 0.065, open_h)
    else:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.022), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawArc(QtCore.QRectF(mouth_x - bw * 0.08, mouth_y - bh * 0.03, bw * 0.08, bh * 0.08), 190 * 16, 160 * 16)
        p.drawArc(QtCore.QRectF(mouth_x, mouth_y - bh * 0.03, bw * 0.08, bh * 0.08), 190 * 16, 160 * 16)

    # 3D Paws with volumetric drop shadow
    paw_wave = math.sin(phase * 10.0) * h * 0.035 if state in ("happy", "talking") else 0.0
    paw_y_l = by + bh * 0.78 - paw_wave
    paw_y_r = by + bh * 0.78 + paw_wave
    paw_x_l = bx + bw * 0.14
    paw_x_r = bx + bw * 0.86

    # Paw shadows
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(15, 23, 42, 60))
    p.drawEllipse(QtCore.QPointF(paw_x_l, paw_y_l + bh * 0.03), bw * 0.09, bh * 0.05)
    p.drawEllipse(QtCore.QPointF(paw_x_r, paw_y_r + bh * 0.03), bw * 0.09, bh * 0.05)

    # Volumetric paws
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.022)))
    for px_pos, py_pos in [(paw_x_l, paw_y_l), (paw_x_r, paw_y_r)]:
        paw_grad = QtGui.QRadialGradient(px_pos - bw * 0.03, py_pos - bh * 0.03, bw * 0.09)
        paw_grad.setColorAt(0.0, QtGui.QColor("#e0f2fe"))
        paw_grad.setColorAt(1.0, QtGui.QColor("#bae6fd"))
        p.setBrush(paw_grad)
        p.drawEllipse(QtCore.QPointF(px_pos, py_pos), bw * 0.09, bh * 0.08)

    p.restore()

    # Thinking indicator dots above head with 3D bounce
    if state == "thinking":
        for idx in range(3):
            bounce = math.sin(phase * 6.0 - idx * 0.9) * h * 0.025
            dx = cx - w * 0.11 + idx * w * 0.11
            dy = bounds.top() + h * 0.11 + bounce
            dot_grad = QtGui.QRadialGradient(dx - w * 0.01, dy - w * 0.01, w * 0.04)
            dot_grad.setColorAt(0.0, QtGui.QColor("#ffffff"))
            dot_grad.setColorAt(0.6, QtGui.QColor("#fde047"))
            dot_grad.setColorAt(1.0, QtGui.QColor("#ca8a04"))
            p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), 1.5))
            p.setBrush(dot_grad)
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
    """Paint Ben Tennyson with 2.5D multi-plane parallax, spiky hair, green eyes, and 3D Omnitrix."""
    cx = bounds.center().x()
    cy = bounds.center().y()
    w = bounds.width()
    h = bounds.height()

    shadow_scale = 0.8 if state in ("talking", "happy") else 1.0
    _paint_ground_shadow(p, bounds, shadow_scale, look_x, look_y)

    bw = w * 0.62
    bh = h * 0.65
    bx = cx - bw / 2
    by = cy - bh / 2 + h * 0.05

    # Parallax plane offsets
    bg_ox = -look_x * bw * 0.045
    bg_oy = -look_y * bh * 0.035
    fg_ox = look_x * bw * 0.065
    fg_oy = look_y * bh * 0.048

    p.save()
    if state == "thinking":
        p.translate(cx, cy)
        p.rotate(math.sin(phase * 2.5) * 4.5)
        p.translate(-cx, -cy)
    else:
        # Subtle 3D perspective lean
        p.translate(cx, cy)
        p.rotate(look_x * 3.0)
        p.translate(-cx, -cy)

    # 1. Back Layer: Rear Spiky Hair (Depth plane z = -0.45)
    hair_color = QtGui.QColor("#5c3317")
    hair_dark = QtGui.QColor("#3b2010")
    hair_highlight = QtGui.QColor("#854d0e")

    p.setPen(QtGui.QPen(QtGui.QColor("#2d180a"), max(2.2, w * 0.024)))
    back_hair_grad = QtGui.QLinearGradient(cx + bg_ox, by + bg_oy - bh * 0.3, cx + bg_ox, by + bg_oy + bh * 0.4)
    back_hair_grad.setColorAt(0.0, hair_highlight)
    back_hair_grad.setColorAt(0.5, hair_color)
    back_hair_grad.setColorAt(1.0, hair_dark)
    p.setBrush(back_hair_grad)

    head_w = bw * 0.76
    head_h = bh * 0.54
    hx = cx - head_w / 2
    hy = by + bh * 0.06

    hair_poly = QtGui.QPolygonF([
        QtCore.QPointF(hx + bg_ox - bw * 0.08, hy + bg_oy + head_h * 0.35),
        QtCore.QPointF(hx + bg_ox - bw * 0.16, hy + bg_oy + head_h * 0.05),
        QtCore.QPointF(hx + bg_ox + head_w * 0.10, hy + bg_oy - head_h * 0.18),
        QtCore.QPointF(hx + bg_ox + head_w * 0.32, hy + bg_oy - head_h * 0.30),
        QtCore.QPointF(hx + bg_ox + head_w * 0.58, hy + bg_oy - head_h * 0.20),
        QtCore.QPointF(hx + bg_ox + head_w * 0.88, hy + bg_oy - head_h * 0.26),
        QtCore.QPointF(hx + bg_ox + head_w * 1.14, hy + bg_oy + head_h * 0.08),
        QtCore.QPointF(hx + bg_ox + head_w * 1.08, hy + bg_oy + head_h * 0.38),
        QtCore.QPointF(hx + bg_ox + head_w * 0.90, hy + bg_oy + head_h * 0.22),
        QtCore.QPointF(hx + bg_ox + head_w * 0.65, hy + bg_oy + head_h * 0.26),
        QtCore.QPointF(hx + bg_ox + head_w * 0.35, hy + bg_oy + head_h * 0.20),
        QtCore.QPointF(hx + bg_ox + head_w * 0.12, hy + bg_oy + head_h * 0.28),
    ])
    p.drawPolygon(hair_poly)

    # 2. Mid Layer: Torso & Volumetric Shirt (z = 0.0)
    shirt_rect = QtCore.QRectF(cx - bw * 0.44, by + bh * 0.58, bw * 0.88, bh * 0.45)
    shirt_grad = QtGui.QLinearGradient(cx - bw * 0.44, by, cx + bw * 0.44, by)
    shirt_grad.setColorAt(0.0, QtGui.QColor("#e2e8f0"))
    shirt_grad.setColorAt(0.25, QtGui.QColor("#ffffff"))
    shirt_grad.setColorAt(0.75, QtGui.QColor("#f8fafc"))
    shirt_grad.setColorAt(1.0, QtGui.QColor("#cbd5e1"))
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.022)))
    p.setBrush(shirt_grad)
    p.drawRoundedRect(shirt_rect, bw * 0.18, bw * 0.18)

    # Black stripe with 3D perspective curvature
    stripe_cx = cx + look_x * bw * 0.035
    stripe_w = bw * 0.22
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor("#0f172a"))
    p.drawRect(QtCore.QRectF(stripe_cx - stripe_w / 2, by + bh * 0.58, stripe_w, bh * 0.45))

    # Black collar with depth
    p.drawEllipse(QtCore.QPointF(cx, by + bh * 0.59), bw * 0.20, bh * 0.08)

    # Neck with warm chin shadow
    neck_grad = QtGui.QLinearGradient(cx, by + bh * 0.48, cx, by + bh * 0.62)
    neck_grad.setColorAt(0.0, QtGui.QColor("#fb923c"))  # Chin drop shadow
    neck_grad.setColorAt(0.7, QtGui.QColor("#fed7aa"))
    p.setBrush(neck_grad)
    p.drawRect(QtCore.QRectF(cx - bw * 0.12, by + bh * 0.48, bw * 0.24, bh * 0.14))

    # 3. Head / Face (Depth plane z = +0.2)
    head_light_x = cx - head_w * 0.18 + look_x * head_w * 0.05
    head_light_y = hy + head_h * 0.22 + look_y * head_h * 0.05
    skin_grad = QtGui.QRadialGradient(head_light_x, head_light_y, head_w * 0.76)
    skin_grad.setColorAt(0.0, QtGui.QColor("#fef9c3"))
    skin_grad.setColorAt(0.45, QtGui.QColor("#fde047"))
    skin_grad.setColorAt(0.70, QtGui.QColor("#fed7aa"))
    skin_grad.setColorAt(1.0, QtGui.QColor("#fba973"))  # Jawline shadow
    p.setBrush(skin_grad)
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024)))
    p.drawRoundedRect(QtCore.QRectF(hx, hy, head_w, head_h), head_w * 0.42, head_h * 0.44)

    # 4. Front Spiky Hair Bangs & Specular Streak (Depth plane z = +0.45)
    bang_ox = fg_ox * 0.50
    bang_oy = fg_oy * 0.40
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(hair_highlight)
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(hx + bang_ox + head_w * 0.25, hy + bang_oy - head_h * 0.14),
        QtCore.QPointF(hx + bang_ox + head_w * 0.42, hy + bang_oy - head_h * 0.22),
        QtCore.QPointF(hx + bang_ox + head_w * 0.50, hy + bang_oy - head_h * 0.12),
        QtCore.QPointF(hx + bang_ox + head_w * 0.32, hy + bang_oy - head_h * 0.06),
    ]))

    # 5. Foreground Layer: Angled Eyebrows & 3D Hero Green Eyes (z = +0.65)
    p.setPen(QtGui.QPen(hair_color, max(2.0, w * 0.023), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
    eyebrow_y = hy + head_h * 0.38 + fg_oy
    brow_l_start = QtCore.QPointF(cx - head_w * 0.32 + fg_ox, eyebrow_y - head_h * 0.02)
    brow_l_end = QtCore.QPointF(cx - head_w * 0.12 + fg_ox, eyebrow_y + head_h * 0.02)
    brow_r_start = QtCore.QPointF(cx + head_w * 0.12 + fg_ox, eyebrow_y + head_h * 0.02)
    brow_r_end = QtCore.QPointF(cx + head_w * 0.32 + fg_ox, eyebrow_y - head_h * 0.02)
    p.drawLine(brow_l_start, brow_l_end)
    p.drawLine(brow_r_start, brow_r_end)

    eye_y = hy + head_h * 0.52 + fg_oy
    eye_dx = head_w * 0.24
    eye_r = head_w * 0.10

    if blinking:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.025), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(QtCore.QRectF(cx - eye_dx + fg_ox - eye_r, eye_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
        p.drawArc(QtCore.QRectF(cx + eye_dx + fg_ox - eye_r, eye_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
    elif state == "happy":
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.4, w * 0.028), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(QtCore.QRectF(cx - eye_dx + fg_ox - eye_r, eye_y - eye_r * 0.4, eye_r * 2, eye_r * 1.2), 15 * 16, 150 * 16)
        p.drawArc(QtCore.QRectF(cx + eye_dx + fg_ox - eye_r, eye_y - eye_r * 0.4, eye_r * 2, eye_r * 1.2), 15 * 16, 150 * 16)
    else:
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        for sign in (-1, 1):
            ex = cx + sign * eye_dx + fg_ox
            ey = eye_y

            # Sclera with soft top ambient shadow
            sclera_grad = QtGui.QLinearGradient(ex, ey - eye_r, ex, ey + eye_r)
            sclera_grad.setColorAt(0.0, QtGui.QColor("#e2e8f0"))
            sclera_grad.setColorAt(0.3, QtGui.QColor("#ffffff"))
            p.setBrush(sclera_grad)
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r, eye_r * 1.08)

            # 3D Emerald green iris
            iris_grad = QtGui.QRadialGradient(ex, ey + eye_r * 0.15, eye_r * 0.72)
            iris_grad.setColorAt(0.0, QtGui.QColor("#86efac"))  # Bright neon lime center
            iris_grad.setColorAt(0.55, QtGui.QColor("#22c55e"))
            iris_grad.setColorAt(1.0, QtGui.QColor("#15803d"))  # Deep emerald rim
            p.setBrush(iris_grad)
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 0.65, eye_r * 0.72)

            # Black pupil
            p.setBrush(QtGui.QColor("#0f172a"))
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 0.36, eye_r * 0.40)

            # Stationary 3D glass corneal catchlight
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawEllipse(QtCore.QPointF(ex - eye_r * 0.22, ey - eye_r * 0.25), eye_r * 0.24, eye_r * 0.24)

    # 6. Hero Smirk Mouth (z = +0.65)
    mouth_y = hy + head_h * 0.78 + fg_oy
    mouth_x = cx + fg_ox
    if state == "talking":
        open_h = head_h * (0.07 + 0.05 * abs(math.sin(phase * 14.0)))
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(1.8, w * 0.02)))
        p.setBrush(QtGui.QColor("#e11d48"))
        p.drawEllipse(QtCore.QPointF(mouth_x + head_w * 0.04, mouth_y), head_w * 0.09, open_h)
    else:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawArc(QtCore.QRectF(mouth_x - head_w * 0.08, mouth_y - head_h * 0.04, head_w * 0.22, head_h * 0.12), 200 * 16, 140 * 16)

    # 7. Left wrist with 3D VOLUMETRIC OMNITRIX
    wrist_y = by + bh * 0.76 + (math.sin(phase * 4.0) * h * 0.02 if state == "happy" else 0.0)
    wrist_x = cx - bw * 0.40
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), 2.0))
    # Metallic cylindrical band
    band_grad = QtGui.QLinearGradient(wrist_x - bw * 0.10, wrist_y, wrist_x + bw * 0.10, wrist_y)
    band_grad.setColorAt(0.0, QtGui.QColor("#1e293b"))
    band_grad.setColorAt(0.4, QtGui.QColor("#475569"))
    band_grad.setColorAt(1.0, QtGui.QColor("#0f172a"))
    p.setBrush(band_grad)
    p.drawRoundedRect(QtCore.QRectF(wrist_x - bw * 0.10, wrist_y - bh * 0.08, bw * 0.20, bh * 0.16), 4, 4)

    # 3D Beveled dial base
    dial_grad = QtGui.QRadialGradient(wrist_x - bw * 0.02, wrist_y - bw * 0.02, bw * 0.08)
    dial_grad.setColorAt(0.0, QtGui.QColor("#475569"))
    dial_grad.setColorAt(0.65, QtGui.QColor("#1e293b"))
    dial_grad.setColorAt(1.0, QtGui.QColor("#020617"))
    p.setBrush(dial_grad)
    p.drawEllipse(QtCore.QPointF(wrist_x, wrist_y), bw * 0.08, bw * 0.08)

    # Omnitrix 3D recessed neon green lens
    glow_alpha = int(160 + 95 * abs(math.sin(phase * 4.0)))
    lens_grad = QtGui.QRadialGradient(wrist_x, wrist_y, bw * 0.055)
    lens_grad.setColorAt(0.0, QtGui.QColor(134, 239, 172, glow_alpha))
    lens_grad.setColorAt(0.7, QtGui.QColor(34, 197, 94, glow_alpha))
    lens_grad.setColorAt(1.0, QtGui.QColor(21, 128, 61, glow_alpha))
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(lens_grad)
    p.drawEllipse(QtCore.QPointF(wrist_x, wrist_y), bw * 0.055, bw * 0.055)

    # Omnitrix hourglass core with 3D drop shadow
    p.setBrush(QtGui.QColor("#020617"))
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
        p.setBrush(QtGui.QColor("#22c55e"))
        p.drawPolygon(QtGui.QPolygonF([
            QtCore.QPointF(cx - dr * 0.5, dial_y - dr * 0.5),
            QtCore.QPointF(cx + dr * 0.5, dial_y - dr * 0.5),
            QtCore.QPointF(cx - dr * 0.5, dial_y + dr * 0.5),
            QtCore.QPointF(cx + dr * 0.5, dial_y + dr * 0.5),
        ]))

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
    """Paint Gwen Tennyson (classic) with 2.5D multi-plane parallax, orange bob, sweater, and magic sparkles."""
    cx = bounds.center().x()
    cy = bounds.center().y()
    w = bounds.width()
    h = bounds.height()

    shadow_scale = 0.8 if state in ("talking", "happy") else 1.0
    _paint_ground_shadow(p, bounds, shadow_scale, look_x, look_y)

    bw = w * 0.60
    bh = h * 0.64
    bx = cx - bw / 2
    by = cy - bh / 2 + h * 0.05

    # Parallax plane offsets
    bg_ox = -look_x * bw * 0.045
    bg_oy = -look_y * bh * 0.035
    fg_ox = look_x * bw * 0.065
    fg_oy = look_y * bh * 0.048

    p.save()
    if state == "thinking":
        p.translate(cx, cy)
        p.rotate(math.sin(phase * 2.5) * 4.0)
        p.translate(-cx, -cy)
    else:
        p.translate(cx, cy)
        p.rotate(look_x * 2.8)
        p.translate(-cx, -cy)

    head_w = bw * 0.74
    head_h = bh * 0.52
    hx = cx - head_w / 2
    hy = by + bh * 0.08

    # 1. Back Layer: Rear Orange Bob Hair (Depth plane z = -0.45)
    p.setBrush(QtGui.QColor("#c2410c"))
    p.setPen(QtGui.QPen(QtGui.QColor("#9a3412"), max(2.2, w * 0.024)))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(hx + bg_ox - bw * 0.12, hy + bg_oy + head_h * 0.76),
        QtCore.QPointF(hx + bg_ox - bw * 0.10, hy + bg_oy + head_h * 0.15),
        QtCore.QPointF(hx + bg_ox + head_w * 0.20, hy + bg_oy - head_h * 0.22),
        QtCore.QPointF(hx + bg_ox + head_w * 0.80, hy + bg_oy - head_h * 0.22),
        QtCore.QPointF(hx + bg_ox + head_w * 1.10, hy + bg_oy + head_h * 0.15),
        QtCore.QPointF(hx + bg_ox + head_w * 1.12, hy + bg_oy + head_h * 0.76),
    ]))

    # 2. Mid Layer: Torso & Volumetric Knit Sweater (z = 0.0)
    sweater_rect = QtCore.QRectF(cx - bw * 0.42, by + bh * 0.58, bw * 0.84, bh * 0.45)
    sweater_grad = QtGui.QLinearGradient(cx - bw * 0.42, by, cx + bw * 0.42, by)
    sweater_grad.setColorAt(0.0, QtGui.QColor("#0369a1"))
    sweater_grad.setColorAt(0.3, QtGui.QColor("#0284c7"))
    sweater_grad.setColorAt(0.7, QtGui.QColor("#38bdf8"))
    sweater_grad.setColorAt(1.0, QtGui.QColor("#0284c7"))
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.022)))
    p.setBrush(sweater_grad)
    p.drawRoundedRect(sweater_rect, bw * 0.18, bw * 0.18)

    # White collar shirt peeking out with depth
    p.setBrush(QtGui.QColor("#f8fafc"))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(cx - bw * 0.14, by + bh * 0.58),
        QtCore.QPointF(cx, by + bh * 0.66),
        QtCore.QPointF(cx + bw * 0.14, by + bh * 0.58),
    ]))

    # Stylized cat logo on chest
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor("#075985"))
    cat_y = by + bh * 0.74
    p.drawEllipse(QtCore.QPointF(cx + look_x * bw * 0.02, cat_y), bw * 0.10, bh * 0.07)
    p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(cx + look_x * bw * 0.02 - bw * 0.08, cat_y - bh * 0.04), QtCore.QPointF(cx + look_x * bw * 0.02 - bw * 0.04, cat_y - bh * 0.09), QtCore.QPointF(cx + look_x * bw * 0.02, cat_y - bh * 0.04)]))
    p.drawPolygon(QtGui.QPolygonF([QtCore.QPointF(cx + look_x * bw * 0.02, cat_y - bh * 0.04), QtCore.QPointF(cx + look_x * bw * 0.02 + bw * 0.04, cat_y - bh * 0.09), QtCore.QPointF(cx + look_x * bw * 0.02 + bw * 0.08, cat_y - bh * 0.04)]))

    # 3. Head / Face (Depth plane z = +0.2)
    head_light_x = cx - head_w * 0.18 + look_x * head_w * 0.05
    head_light_y = hy + head_h * 0.22 + look_y * head_h * 0.05
    skin_grad = QtGui.QRadialGradient(head_light_x, head_light_y, head_w * 0.76)
    skin_grad.setColorAt(0.0, QtGui.QColor("#fff7ed"))
    skin_grad.setColorAt(0.55, QtGui.QColor("#ffedd5"))
    skin_grad.setColorAt(1.0, QtGui.QColor("#fed7aa"))
    p.setBrush(skin_grad)
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024)))
    p.drawRoundedRect(QtCore.QRectF(hx, hy, head_w, head_h), head_w * 0.44, head_h * 0.44)

    # 4. Front Orange Bangs & Hair (Depth plane z = +0.45)
    bang_ox = fg_ox * 0.50
    bang_oy = fg_oy * 0.40
    hair_grad = QtGui.QLinearGradient(cx, hy, cx, hy + head_h)
    hair_grad.setColorAt(0.0, QtGui.QColor("#fb923c"))
    hair_grad.setColorAt(0.5, QtGui.QColor("#f97316"))
    hair_grad.setColorAt(1.0, QtGui.QColor("#ea580c"))
    p.setBrush(hair_grad)
    p.setPen(QtGui.QPen(QtGui.QColor("#c2410c"), max(2.2, w * 0.024)))

    hair_poly = QtGui.QPolygonF([
        QtCore.QPointF(hx + bang_ox - bw * 0.10, hy + bang_oy + head_h * 0.72),
        QtCore.QPointF(hx + bang_ox - bw * 0.08, hy + bang_oy + head_h * 0.15),
        QtCore.QPointF(hx + bang_ox + head_w * 0.20, hy + bang_oy - head_h * 0.20),
        QtCore.QPointF(hx + bang_ox + head_w * 0.50, hy + bang_oy - head_h * 0.22),
        QtCore.QPointF(hx + bang_ox + head_w * 0.80, hy + bang_oy - head_h * 0.20),
        QtCore.QPointF(hx + bang_ox + head_w * 1.08, hy + bang_oy + head_h * 0.15),
        QtCore.QPointF(hx + bang_ox + head_w * 1.10, hy + bang_oy + head_h * 0.72),
        QtCore.QPointF(hx + bang_ox + head_w * 0.94, hy + bang_oy + head_h * 0.40),
        QtCore.QPointF(hx + bang_ox + head_w * 0.84, hy + bang_oy + head_h * 0.22),
        QtCore.QPointF(hx + bang_ox + head_w * 0.50, hy + bang_oy + head_h * 0.18),
        QtCore.QPointF(hx + bang_ox + head_w * 0.16, hy + bang_oy + head_h * 0.22),
        QtCore.QPointF(hx + bang_ox - bw * 0.04, hy + bang_oy + head_h * 0.45),
    ])
    p.drawPolygon(hair_poly)

    # 3D Glossy Blue Hair Clip
    p.setBrush(QtGui.QColor("#38bdf8"))
    p.setPen(QtGui.QPen(QtGui.QColor("#0369a1"), 1.6))
    p.drawRoundedRect(QtCore.QRectF(hx + bang_ox + head_w * 0.78, hy + bang_oy + head_h * 0.12, bw * 0.12, bh * 0.06), 3, 3)

    # 5. Foreground: Soft Blush & 3D Emerald Eyes (z = +0.65)
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    for sign in (-1, 1):
        cheek_x = cx + sign * (head_w * 0.28) + fg_ox
        cheek_y = hy + head_h * 0.62 + fg_oy
        chk_grad = QtGui.QRadialGradient(cheek_x, cheek_y, head_w * 0.09)
        chk_grad.setColorAt(0.0, QtGui.QColor(251, 113, 133, 160))
        chk_grad.setColorAt(1.0, QtGui.QColor(251, 113, 133, 0))
        p.setBrush(chk_grad)
        p.drawEllipse(QtCore.QPointF(cheek_x, cheek_y), head_w * 0.09, head_h * 0.06)

    eye_y = hy + head_h * 0.48 + fg_oy
    eye_dx = head_w * 0.23
    eye_r = head_w * 0.095

    if blinking:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.025), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(QtCore.QRectF(cx - eye_dx + fg_ox - eye_r, eye_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
        p.drawArc(QtCore.QRectF(cx + eye_dx + fg_ox - eye_r, eye_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
    elif state == "happy":
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.4, w * 0.028), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(QtCore.QRectF(cx - eye_dx + fg_ox - eye_r, eye_y - eye_r * 0.4, eye_r * 2, eye_r * 1.2), 15 * 16, 150 * 16)
        p.drawArc(QtCore.QRectF(cx + eye_dx + fg_ox - eye_r, eye_y - eye_r * 0.4, eye_r * 2, eye_r * 1.2), 15 * 16, 150 * 16)
    else:
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        for sign in (-1, 1):
            ex = cx + sign * eye_dx + fg_ox
            ey = eye_y
            # Sclera
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r, eye_r * 1.1)
            # 3D Emerald iris
            iris_grad = QtGui.QRadialGradient(ex, ey + eye_r * 0.1, eye_r * 0.72)
            iris_grad.setColorAt(0.0, QtGui.QColor("#4ade80"))
            iris_grad.setColorAt(0.55, QtGui.QColor("#16a34a"))
            iris_grad.setColorAt(1.0, QtGui.QColor("#14532d"))
            p.setBrush(iris_grad)
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 0.68, eye_r * 0.75)
            # Pupil
            p.setBrush(QtGui.QColor("#0f172a"))
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 0.35, eye_r * 0.40)
            # Double glass catchlights
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawEllipse(QtCore.QPointF(ex - eye_r * 0.22, ey - eye_r * 0.25), eye_r * 0.24, eye_r * 0.24)
            p.drawEllipse(QtCore.QPointF(ex + eye_r * 0.20, ey + eye_r * 0.20), eye_r * 0.12, eye_r * 0.12)

    # Mouth
    mouth_y = hy + head_h * 0.74 + fg_oy
    mouth_x = cx + fg_ox
    if state == "talking":
        open_h = head_h * (0.06 + 0.045 * abs(math.sin(phase * 14.0)))
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(1.8, w * 0.02)))
        p.setBrush(QtGui.QColor("#fb7185"))
        p.drawEllipse(QtCore.QPointF(mouth_x, mouth_y), head_w * 0.08, open_h)
    else:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.022), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawArc(QtCore.QRectF(mouth_x - head_w * 0.07, mouth_y - head_h * 0.03, head_w * 0.14, head_h * 0.08), 200 * 16, 140 * 16)

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
    """Paint Gwen in her cosmic Anodite mana form with 3D volumetric energy body and orbiting mana orbs."""
    cx = bounds.center().x()
    cy = bounds.center().y()
    w = bounds.width()
    h = bounds.height()

    shadow_scale = 0.7 if state in ("talking", "happy") else 0.9
    _paint_ground_shadow(p, bounds, shadow_scale, look_x, look_y)

    bw = w * 0.60
    bh = h * 0.65
    bx = cx - bw / 2
    by = cy - bh / 2 + h * 0.04

    # Parallax plane offsets
    bg_ox = -look_x * bw * 0.045
    bg_oy = -look_y * bh * 0.035
    fg_ox = look_x * bw * 0.065
    fg_oy = look_y * bh * 0.048

    p.save()
    if state == "thinking":
        p.translate(cx, cy)
        p.rotate(math.sin(phase * 2.2) * 5.0)
        p.translate(-cx, -cy)
    else:
        p.translate(cx, cy)
        p.rotate(look_x * 2.5)
        p.translate(-cx, -cy)

    # 1. Back Layer: Cosmic Hair Tendrils (Depth plane z = -0.45)
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(232, 121, 249, 180))
    for idx, offset in enumerate([-0.28, -0.10, 0.10, 0.28]):
        sway = math.sin(phase * 3.0 + idx * 1.1) * bw * 0.08
        hair_x = cx + bg_ox + offset * bw
        hair_y = by + bg_oy - bh * 0.08
        p.drawEllipse(QtCore.QPointF(hair_x + sway, hair_y), bw * 0.18, bh * 0.24)

    # 2. Mid Layer: Volumetric 3D Anodite Body (z = 0.0)
    body_light_x = cx - bw * 0.15 + look_x * bw * 0.05
    body_light_y = by + bh * 0.40 + look_y * bh * 0.05
    body_grad = QtGui.QRadialGradient(body_light_x, body_light_y, bw * 0.70)
    body_grad.setColorAt(0.0, QtGui.QColor("#f472b6"))
    body_grad.setColorAt(0.40, QtGui.QColor("#d946ef"))
    body_grad.setColorAt(0.75, QtGui.QColor("#a21caf"))
    body_grad.setColorAt(1.0, QtGui.QColor("#701a75"))
    p.setBrush(body_grad)
    p.setPen(QtGui.QPen(QtGui.QColor("#fdf4ff"), max(2.2, w * 0.024)))
    p.drawRoundedRect(QtCore.QRectF(bx + bw * 0.10, by + bh * 0.18, bw * 0.80, bh * 0.80), bw * 0.38, bh * 0.40)

    # 3. Head (Depth plane z = +0.2)
    head_w = bw * 0.70
    head_h = bh * 0.50
    hx = cx - head_w / 2
    hy = by + bh * 0.10
    head_grad = QtGui.QRadialGradient(cx + fg_ox * 0.4, hy + head_h * 0.3, head_w * 0.65)
    head_grad.setColorAt(0.0, QtGui.QColor("#f0abfc"))
    head_grad.setColorAt(0.55, QtGui.QColor("#c026d3"))
    head_grad.setColorAt(1.0, QtGui.QColor("#86198f"))
    p.setBrush(head_grad)
    p.setPen(QtGui.QPen(QtGui.QColor("#fdf4ff"), max(2.0, w * 0.022)))
    p.drawRoundedRect(QtCore.QRectF(hx, hy, head_w, head_h), head_w * 0.44, head_h * 0.44)

    # 4. Foreground: Glowing 3D Mana Eyes (z = +0.65)
    eye_y = hy + head_h * 0.46 + fg_oy
    eye_dx = head_w * 0.23
    eye_r = head_w * 0.09

    if blinking:
        p.setPen(QtGui.QPen(QtGui.QColor("#fdf4ff"), max(2.4, w * 0.026), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(QtCore.QRectF(cx - eye_dx + fg_ox - eye_r, eye_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
        p.drawArc(QtCore.QRectF(cx + eye_dx + fg_ox - eye_r, eye_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
    else:
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        for sign in (-1, 1):
            ex = cx + sign * eye_dx + fg_ox
            ey = eye_y
            # 3D Outer energy bloom
            bloom_grad = QtGui.QRadialGradient(ex, ey, eye_r * 1.35)
            bloom_grad.setColorAt(0.0, QtGui.QColor(244, 114, 182, 220))
            bloom_grad.setColorAt(0.6, QtGui.QColor(217, 70, 239, 120))
            bloom_grad.setColorAt(1.0, QtGui.QColor(168, 85, 247, 0))
            p.setBrush(bloom_grad)
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 1.35, eye_r * 1.35)

            # Luminous white core
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 0.72, eye_r * 0.72)

    # Mouth
    mouth_y = hy + head_h * 0.72 + fg_oy
    mouth_x = cx + fg_ox
    if state == "talking":
        open_h = head_h * (0.06 + 0.045 * abs(math.sin(phase * 14.0)))
        p.setPen(QtGui.QPen(QtGui.QColor("#fdf4ff"), 1.8))
        p.setBrush(QtGui.QColor("#f472b6"))
        p.drawEllipse(QtCore.QPointF(mouth_x, mouth_y), head_w * 0.075, open_h)
    else:
        p.setPen(QtGui.QPen(QtGui.QColor("#fdf4ff"), 2.0, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawArc(QtCore.QRectF(mouth_x - head_w * 0.06, mouth_y - head_h * 0.03, head_w * 0.12, head_h * 0.08), 200 * 16, 140 * 16)

    # 5. True 3D Orbiting Mana Orbs (calculated with depth perspective Z)
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    for i in range(3):
        orb_angle = phase * 2.6 + i * 2.09
        orb_x = cx + math.sin(orb_angle) * bw * 0.44
        orb_y = cy + math.cos(orb_angle * 0.85) * bh * 0.28
        orb_z = math.cos(orb_angle)  # -1 is behind, +1 is in front
        orb_rad = bw * (0.075 + 0.025 * orb_z)

        orb_grad = QtGui.QRadialGradient(orb_x - orb_rad * 0.25, orb_y - orb_rad * 0.25, orb_rad)
        orb_grad.setColorAt(0.0, QtGui.QColor("#ffffff"))
        orb_grad.setColorAt(0.4, QtGui.QColor(244, 114, 182, 230))
        orb_grad.setColorAt(0.8, QtGui.QColor(217, 70, 239, 180))
        orb_grad.setColorAt(1.0, QtGui.QColor(112, 26, 117, 0))
        p.setBrush(orb_grad)
        p.drawEllipse(QtCore.QPointF(orb_x, orb_y), orb_rad, orb_rad)

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
    """Paint Heatblast with 2.5D multi-plane parallax, dark magma rock armor, glowing cracks, and 3D flame crown."""
    cx = bounds.center().x()
    cy = bounds.center().y()
    w = bounds.width()
    h = bounds.height()

    shadow_scale = 0.8 if state in ("talking", "happy") else 1.0
    _paint_ground_shadow(p, bounds, shadow_scale, look_x, look_y)

    bw = w * 0.64
    bh = h * 0.64
    bx = cx - bw / 2
    by = cy - bh / 2 + h * 0.06

    # Parallax plane offsets
    bg_ox = -look_x * bw * 0.045
    bg_oy = -look_y * bh * 0.035
    fg_ox = look_x * bw * 0.065
    fg_oy = look_y * bh * 0.048

    p.save()
    if state == "thinking":
        p.translate(cx, cy)
        p.rotate(math.sin(phase * 2.5) * 4.0)
        p.translate(-cx, -cy)
    else:
        p.translate(cx, cy)
        p.rotate(look_x * 2.5)
        p.translate(-cx, -cy)

    head_w = bw * 0.72
    head_h = bh * 0.48
    hx = cx - head_w / 2
    hy = by + bh * 0.12

    # 1. Back Layer: Rear Flame Tongue (Depth plane z = -0.45)
    flame_height = bh * (0.38 + 0.10 * math.sin(phase * 8.0))
    if state == "happy":
        flame_height *= 1.35

    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(185, 28, 28, 210))  # Deep back flame
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(hx + bg_ox - bw * 0.06, hy + bg_oy + head_h * 0.25),
        QtCore.QPointF(hx + bg_ox + head_w * 0.15, hy + bg_oy - flame_height * 0.75 + math.sin(phase * 7.0) * bh * 0.05),
        QtCore.QPointF(hx + bg_ox + head_w * 0.50, hy + bg_oy - flame_height * 1.05 + math.sin(phase * 9.0) * bh * 0.06),
        QtCore.QPointF(hx + bg_ox + head_w * 0.85, hy + bg_oy - flame_height * 0.80 + math.cos(phase * 8.0) * bh * 0.05),
        QtCore.QPointF(hx + bg_ox + head_w * 1.06, hy + bg_oy + head_h * 0.25),
    ]))

    # 2. Mid Layer: Volumetric Magma Collar / Shoulders (z = 0.0)
    collar_rect = QtCore.QRectF(cx - bw * 0.45, by + bh * 0.54, bw * 0.90, bh * 0.46)
    collar_grad = QtGui.QLinearGradient(cx - bw * 0.45, by, cx + bw * 0.45, by)
    collar_grad.setColorAt(0.0, QtGui.QColor("#0f172a"))
    collar_grad.setColorAt(0.25, QtGui.QColor("#334155"))
    collar_grad.setColorAt(0.70, QtGui.QColor("#1e293b"))
    collar_grad.setColorAt(1.0, QtGui.QColor("#0f172a"))
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024)))
    p.setBrush(collar_grad)
    p.drawRoundedRect(collar_rect, bw * 0.20, bw * 0.20)

    # Glowing molten lava cracks on collar with heat bloom
    p.setPen(QtGui.QPen(QtGui.QColor("#ea580c"), max(3.2, w * 0.030), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
    crack_pts = [
        (cx - bw * 0.28, by + bh * 0.68),
        (cx - bw * 0.12, by + bh * 0.78),
        (cx, by + bh * 0.72),
        (cx + bw * 0.18, by + bh * 0.82),
        (cx + bw * 0.32, by + bh * 0.70),
    ]
    for i in range(len(crack_pts) - 1):
        p.drawLine(QtCore.QPointF(*crack_pts[i]), QtCore.QPointF(*crack_pts[i + 1]))

    p.setPen(QtGui.QPen(QtGui.QColor("#fef08a"), max(1.8, w * 0.018), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
    for i in range(len(crack_pts) - 1):
        p.drawLine(QtCore.QPointF(*crack_pts[i]), QtCore.QPointF(*crack_pts[i + 1]))

    # 3. Head: Volumetric Magma Rock Shape (Depth plane z = +0.2)
    head_grad = QtGui.QRadialGradient(cx - head_w * 0.15 + look_x * head_w * 0.05, hy + head_h * 0.25, head_w * 0.75)
    head_grad.setColorAt(0.0, QtGui.QColor("#475569"))
    head_grad.setColorAt(0.60, QtGui.QColor("#1e293b"))
    head_grad.setColorAt(1.0, QtGui.QColor("#0f172a"))
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024)))
    p.setBrush(head_grad)
    p.drawRoundedRect(QtCore.QRectF(hx, hy, head_w, head_h), head_w * 0.38, head_h * 0.40)

    # Mask plate (volumetric yellow magma core face)
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    mask_grad = QtGui.QRadialGradient(cx + fg_ox * 0.3, hy + head_h * 0.4 + fg_oy * 0.3, head_w * 0.45)
    mask_grad.setColorAt(0.0, QtGui.QColor("#fef08a"))
    mask_grad.setColorAt(0.60, QtGui.QColor("#f59e0b"))
    mask_grad.setColorAt(1.0, QtGui.QColor("#d97706"))
    p.setBrush(mask_grad)
    p.drawRoundedRect(QtCore.QRectF(hx + head_w * 0.12, hy + head_h * 0.18, head_w * 0.76, head_h * 0.70), head_w * 0.28, head_h * 0.28)

    # 4. Front Flame Crown (Middle radiant orange & Core yellow)
    p.setBrush(QtGui.QColor(249, 115, 22, 240))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(hx + head_w * 0.08, hy + head_h * 0.20),
        QtCore.QPointF(hx + head_w * 0.30, hy - flame_height * 0.65 + math.cos(phase * 9.0) * bh * 0.04),
        QtCore.QPointF(hx + head_w * 0.50, hy - flame_height * 0.85 + math.sin(phase * 11.0) * bh * 0.04),
        QtCore.QPointF(hx + head_w * 0.70, hy - flame_height * 0.60 + math.sin(phase * 8.5) * bh * 0.04),
        QtCore.QPointF(hx + head_w * 0.92, hy + head_h * 0.20),
    ]))

    p.setBrush(QtGui.QColor(254, 240, 138, 250))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(hx + head_w * 0.25, hy + head_h * 0.16),
        QtCore.QPointF(hx + head_w * 0.50, hy - flame_height * 0.55 + math.sin(phase * 12.0) * bh * 0.03),
        QtCore.QPointF(hx + head_w * 0.75, hy + head_h * 0.16),
    ]))

    # 5. Foreground: Glowing Magma Slit Eyes (z = +0.65)
    eye_y = hy + head_h * 0.44 + fg_oy
    eye_dx = head_w * 0.22
    eye_r = head_w * 0.09

    if blinking:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.025), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawLine(QtCore.QPointF(cx - eye_dx + fg_ox - eye_r, eye_y), QtCore.QPointF(cx - eye_dx + fg_ox + eye_r, eye_y))
        p.drawLine(QtCore.QPointF(cx + eye_dx + fg_ox - eye_r, eye_y), QtCore.QPointF(cx + eye_dx + fg_ox + eye_r, eye_y))
    else:
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        for sign in (-1, 1):
            ex = cx + sign * eye_dx + fg_ox
            ey = eye_y
            # Outer heat glow
            p.setBrush(QtGui.QColor("#ea580c"))
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 1.15, eye_r * 0.85)
            # Bright yellow core
            p.setBrush(QtGui.QColor("#fef08a"))
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 0.65, eye_r * 0.50)

    # Mouth
    mouth_y = hy + head_h * 0.72 + fg_oy
    mouth_x = cx + fg_ox
    if state == "talking":
        open_h = head_h * (0.07 + 0.05 * abs(math.sin(phase * 14.0)))
        p.setPen(QtGui.QPen(QtGui.QColor("#7c2d12"), 2.0))
        p.setBrush(QtGui.QColor("#ea580c"))
        p.drawEllipse(QtCore.QPointF(mouth_x, mouth_y), head_w * 0.09, open_h)
    else:
        p.setPen(QtGui.QPen(QtGui.QColor("#7c2d12"), 2.2, QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawArc(QtCore.QRectF(mouth_x - head_w * 0.08, mouth_y - head_h * 0.03, head_w * 0.16, head_h * 0.09), 200 * 16, 140 * 16)

    p.restore()

    # Rising ember sparks with 3D depth
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
    """Paint Four Arms with 2.5D multi-plane parallax, 4 amber eyes, muscular red body, and quadruple arms."""
    cx = bounds.center().x()
    cy = bounds.center().y()
    w = bounds.width()
    h = bounds.height()

    shadow_scale = 0.85 if state in ("talking", "happy") else 1.1
    _paint_ground_shadow(p, bounds, shadow_scale, look_x, look_y)

    bw = w * 0.68
    bh = h * 0.65
    bx = cx - bw / 2
    by = cy - bh / 2 + h * 0.05

    # Parallax plane offsets
    bg_ox = -look_x * bw * 0.045
    bg_oy = -look_y * bh * 0.035
    fg_ox = look_x * bw * 0.065
    fg_oy = look_y * bh * 0.048

    p.save()
    if state == "thinking":
        p.translate(cx, cy)
        p.rotate(math.sin(phase * 2.2) * 4.0)
        p.translate(-cx, -cy)
    else:
        p.translate(cx, cy)
        p.rotate(look_x * 2.8)
        p.translate(-cx, -cy)

    # 1. Back Layer: Upper Quad Arms (Depth plane z = -0.35)
    arm_wave = math.sin(phase * 8.0) * h * 0.04 if state in ("talking", "happy") else 0.0

    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024)))
    upper_arm_grad = QtGui.QLinearGradient(cx - bw * 0.55, by, cx + bw * 0.55, by)
    upper_arm_grad.setColorAt(0.0, QtGui.QColor("#b91c1c"))
    upper_arm_grad.setColorAt(0.5, QtGui.QColor("#dc2626"))
    upper_arm_grad.setColorAt(1.0, QtGui.QColor("#991b1b"))
    p.setBrush(upper_arm_grad)

    p.drawEllipse(QtCore.QPointF(cx + bg_ox - bw * 0.44, by + bg_oy + bh * 0.42 - arm_wave), bw * 0.14, bh * 0.16)
    p.drawEllipse(QtCore.QPointF(cx + bg_ox + bw * 0.44, by + bg_oy + bh * 0.42 + arm_wave), bw * 0.14, bh * 0.16)

    # Gold arm cuffs with 3D metallic gleam
    cuff_grad = QtGui.QLinearGradient(cx - bw * 0.50, by, cx - bw * 0.38, by)
    cuff_grad.setColorAt(0.0, QtGui.QColor("#fef08a"))
    cuff_grad.setColorAt(0.5, QtGui.QColor("#f59e0b"))
    cuff_grad.setColorAt(1.0, QtGui.QColor("#92400e"))
    p.setBrush(cuff_grad)
    p.drawRect(QtCore.QRectF(cx + bg_ox - bw * 0.49, by + bg_oy + bh * 0.48 - arm_wave, bw * 0.10, bh * 0.06))
    p.drawRect(QtCore.QRectF(cx + bg_ox + bw * 0.39, by + bg_oy + bh * 0.48 + arm_wave, bw * 0.10, bh * 0.06))

    # 2. Mid Layer: Muscular Torso & Lower Arms (z = 0.0)
    torso_rect = QtCore.QRectF(cx - bw * 0.38, by + bh * 0.52, bw * 0.76, bh * 0.48)
    torso_grad = QtGui.QRadialGradient(cx - bw * 0.15, by + bh * 0.65, bw * 0.55)
    torso_grad.setColorAt(0.0, QtGui.QColor("#ef4444"))
    torso_grad.setColorAt(0.70, QtGui.QColor("#dc2626"))
    torso_grad.setColorAt(1.0, QtGui.QColor("#991b1b"))
    p.setBrush(torso_grad)
    p.drawRoundedRect(torso_rect, bw * 0.18, bw * 0.18)

    # Lower front arms
    p.drawEllipse(QtCore.QPointF(cx - bw * 0.42, by + bh * 0.68 + arm_wave), bw * 0.13, bh * 0.15)
    p.drawEllipse(QtCore.QPointF(cx + bw * 0.42, by + bh * 0.68 - arm_wave), bw * 0.13, bh * 0.15)

    # Gladiator vest with 3D depth
    p.setBrush(QtGui.QColor("#f8fafc"))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(cx - bw * 0.28, by + bh * 0.52),
        QtCore.QPointF(cx, by + bh * 0.75),
        QtCore.QPointF(cx + bw * 0.28, by + bh * 0.52),
    ]))
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor("#0f172a"))
    p.drawRect(QtCore.QRectF(cx - bw * 0.06, by + bh * 0.52, bw * 0.12, bh * 0.48))

    # 3. Head (Depth plane z = +0.2)
    head_w = bw * 0.70
    head_h = bh * 0.50
    hx = cx - head_w / 2
    hy = by + bh * 0.08

    head_grad = QtGui.QRadialGradient(cx - head_w * 0.15 + look_x * head_w * 0.05, hy + head_h * 0.25, head_w * 0.75)
    head_grad.setColorAt(0.0, QtGui.QColor("#ef4444"))
    head_grad.setColorAt(0.65, QtGui.QColor("#dc2626"))
    head_grad.setColorAt(1.0, QtGui.QColor("#991b1b"))
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024)))
    p.setBrush(head_grad)
    p.drawRoundedRect(QtCore.QRectF(hx, hy, head_w, head_h), head_w * 0.36, head_h * 0.38)

    # Iconic black warrior stripe down center of forehead
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor("#0f172a"))
    p.drawRect(QtCore.QRectF(cx - head_w * 0.07 + look_x * head_w * 0.02, hy, head_w * 0.14, head_h * 0.58))

    # 4. Foreground: FOUR AMBER EYES (z = +0.65)
    eye_r = head_w * 0.075
    upper_y = hy + head_h * 0.35 + fg_oy
    upper_dx = head_w * 0.25
    lower_y = hy + head_h * 0.52 + fg_oy
    lower_dx = head_w * 0.21

    if blinking:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.025), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(QtCore.QRectF(cx - upper_dx + fg_ox - eye_r, upper_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
        p.drawArc(QtCore.QRectF(cx + upper_dx + fg_ox - eye_r, upper_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
        p.drawArc(QtCore.QRectF(cx - lower_dx + fg_ox - eye_r, lower_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
        p.drawArc(QtCore.QRectF(cx + lower_dx + fg_ox - eye_r, lower_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
    else:
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        for (ey_base, edx) in [(upper_y, upper_dx), (lower_y, lower_dx)]:
            for sign in (-1, 1):
                ex = cx + sign * edx + fg_ox
                ey = ey_base
                p.setBrush(QtGui.QColor("#fef3c7"))  # Sclera
                p.drawEllipse(QtCore.QPointF(ex, ey), eye_r, eye_r * 1.08)
                # 3D Amber iris
                iris_grad = QtGui.QRadialGradient(ex, ey, eye_r * 0.70)
                iris_grad.setColorAt(0.0, QtGui.QColor("#fde047"))
                iris_grad.setColorAt(0.55, QtGui.QColor("#f59e0b"))
                iris_grad.setColorAt(1.0, QtGui.QColor("#b45309"))
                p.setBrush(iris_grad)
                p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 0.65, eye_r * 0.70)
                # Pupil
                p.setBrush(QtGui.QColor("#0f172a"))
                p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 0.35, eye_r * 0.38)
                # Catchlight
                p.setBrush(QtGui.QColor("#ffffff"))
                p.drawEllipse(QtCore.QPointF(ex - eye_r * 0.20, ey - eye_r * 0.22), eye_r * 0.22, eye_r * 0.22)

    # Wide warrior mouth
    mouth_y = hy + head_h * 0.76 + fg_oy
    mouth_x = cx + fg_ox
    if state == "talking":
        open_h = head_h * (0.07 + 0.05 * abs(math.sin(phase * 14.0)))
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.022)))
        p.setBrush(QtGui.QColor("#991b1b"))
        p.drawEllipse(QtCore.QPointF(mouth_x, mouth_y), head_w * 0.12, open_h)
    else:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawArc(QtCore.QRectF(mouth_x - head_w * 0.11, mouth_y - head_h * 0.04, head_w * 0.22, head_h * 0.10), 200 * 16, 140 * 16)

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
    """Paint XLR8 with 2.5D multi-plane parallax, aerodynamic helmet, and pulsating green 3D visor."""
    cx = bounds.center().x()
    cy = bounds.center().y()
    w = bounds.width()
    h = bounds.height()

    shadow_scale = 0.75 if state in ("talking", "happy") else 0.95
    _paint_ground_shadow(p, bounds, shadow_scale, look_x, look_y)

    bw = w * 0.62
    bh = h * 0.64
    bx = cx - bw / 2
    by = cy - bh / 2 + h * 0.05

    # Parallax plane offsets
    bg_ox = -look_x * bw * 0.045
    bg_oy = -look_y * bh * 0.035
    fg_ox = look_x * bw * 0.065
    fg_oy = look_y * bh * 0.048

    p.save()
    if state == "thinking":
        p.translate(cx, cy)
        p.rotate(math.sin(phase * 2.8) * 4.0)
        p.translate(-cx, -cy)
    else:
        p.translate(cx, cy)
        p.rotate(look_x * 3.0)
        p.translate(-cx, -cy)

    # 1. Back Layer: Pointed tail swishing with momentum (Depth plane z = -0.45)
    tail_sway = math.sin(phase * 2.5) * bw * 0.14
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024)))
    tail_grad = QtGui.QLinearGradient(cx, by + bh * 0.70, cx + bw * 0.45, by + bh * 0.85)
    tail_grad.setColorAt(0.0, QtGui.QColor("#0891b2"))
    tail_grad.setColorAt(1.0, QtGui.QColor("#06b6d4"))
    p.setBrush(tail_grad)
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(cx + bg_ox + bw * 0.20, by + bg_oy + bh * 0.70),
        QtCore.QPointF(cx + bg_ox + bw * 0.45 + tail_sway, by + bg_oy + bh * 0.85),
        QtCore.QPointF(cx + bg_ox + bw * 0.15, by + bg_oy + bh * 0.88),
    ]))

    # 2. Mid Layer: Sleek Aerodynamic Suit (z = 0.0)
    suit_rect = QtCore.QRectF(cx - bw * 0.38, by + bh * 0.54, bw * 0.76, bh * 0.46)
    suit_grad = QtGui.QLinearGradient(cx - bw * 0.38, by, cx + bw * 0.38, by)
    suit_grad.setColorAt(0.0, QtGui.QColor("#020617"))
    suit_grad.setColorAt(0.35, QtGui.QColor("#1e293b"))
    suit_grad.setColorAt(0.70, QtGui.QColor("#0f172a"))
    suit_grad.setColorAt(1.0, QtGui.QColor("#020617"))
    p.setBrush(suit_grad)
    p.drawRoundedRect(suit_rect, bw * 0.18, bw * 0.18)

    # Cyan racing stripes on torso with perspective skew
    stripe_cx = cx + look_x * bw * 0.03
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor("#06b6d4"))
    p.drawRect(QtCore.QRectF(stripe_cx - bw * 0.14, by + bh * 0.54, bw * 0.08, bh * 0.46))
    p.drawRect(QtCore.QRectF(stripe_cx + bw * 0.06, by + bh * 0.54, bw * 0.08, bh * 0.46))

    # 3. Head: Aerodynamic Helmet with Automotive Specular Gloss (Depth plane z = +0.2)
    head_w = bw * 0.72
    head_h = bh * 0.52
    hx = cx - head_w / 2
    hy = by + bh * 0.08

    helmet_poly = QtGui.QPolygonF([
        QtCore.QPointF(hx - bw * 0.06, hy + head_h * 0.40),
        QtCore.QPointF(hx + head_w * 0.50, hy - head_h * 0.28),
        QtCore.QPointF(hx + head_w * 1.06, hy + head_h * 0.40),
        QtCore.QPointF(hx + head_w * 0.90, hy + head_h * 0.90),
        QtCore.QPointF(hx + head_w * 0.10, hy + head_h * 0.90),
    ])
    helmet_grad = QtGui.QRadialGradient(cx - head_w * 0.15, hy + head_h * 0.25, head_w * 0.75)
    helmet_grad.setColorAt(0.0, QtGui.QColor("#334155"))
    helmet_grad.setColorAt(0.60, QtGui.QColor("#0f172a"))
    helmet_grad.setColorAt(1.0, QtGui.QColor("#020617"))
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024)))
    p.setBrush(helmet_grad)
    p.drawPolygon(helmet_poly)

    # Specular gloss gleam across aerodynamic crest
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    p.setBrush(QtGui.QColor(255, 255, 255, 85))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(hx + head_w * 0.40, hy - head_h * 0.24),
        QtCore.QPointF(hx + head_w * 0.50, hy - head_h * 0.27),
        QtCore.QPointF(hx + head_w * 0.56, hy + head_h * 0.15),
        QtCore.QPointF(hx + head_w * 0.46, hy + head_h * 0.15),
    ]))

    # Cyan cheek accents
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

    # 4. Foreground: 3D PULSATING GREEN VISOR (z = +0.65)
    visor_rect = QtCore.QRectF(hx + head_w * 0.16 + fg_ox, hy + head_h * 0.42 + fg_oy, head_w * 0.68, head_h * 0.28)
    if blinking:
        p.setPen(QtGui.QPen(QtGui.QColor("#065f46"), 1.8))
        p.setBrush(QtGui.QColor("#0f172a"))
        p.drawRoundedRect(visor_rect, 4, 4)
    else:
        glow_val = int(180 + 75 * math.sin(phase * 4.0))
        visor_grad = QtGui.QLinearGradient(visor_rect.left(), visor_rect.top(), visor_rect.left(), visor_rect.bottom())
        visor_grad.setColorAt(0.0, QtGui.QColor(134, 239, 172, glow_val))
        visor_grad.setColorAt(0.5, QtGui.QColor(34, 197, 94, glow_val))
        visor_grad.setColorAt(1.0, QtGui.QColor(21, 128, 61, glow_val))
        p.setPen(QtGui.QPen(QtGui.QColor(34, 197, 94, 255), 1.6))
        p.setBrush(visor_grad)
        p.drawRoundedRect(visor_rect, 4, 4)

        # High-tech scanline sweep
        scan_x = visor_rect.left() + ((phase * 120.0) % visor_rect.width())
        p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 2.0))
        p.drawLine(QtCore.QPointF(scan_x, visor_rect.top() + 2), QtCore.QPointF(scan_x, visor_rect.bottom() - 2))

    # Sleek mouth opening
    mouth_y = hy + head_h * 0.78 + fg_oy
    mouth_x = cx + fg_ox
    if state == "talking":
        open_h = head_h * (0.05 + 0.04 * abs(math.sin(phase * 14.0)))
        p.setPen(QtGui.QPen(QtGui.QColor("#06b6d4"), 1.8))
        p.setBrush(QtGui.QColor("#0f172a"))
        p.drawEllipse(QtCore.QPointF(mouth_x, mouth_y), head_w * 0.08, open_h)

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
    """Paint Anime Sakura with 2.5D multi-plane parallax, pink twin-tails, blush, and 3D anime eyes."""
    cx = bounds.center().x()
    cy = bounds.center().y()
    w = bounds.width()
    h = bounds.height()

    shadow_scale = 0.8 if state in ("talking", "happy") else 1.0
    _paint_ground_shadow(p, bounds, shadow_scale, look_x, look_y)

    bw = w * 0.60
    bh = h * 0.64
    bx = cx - bw / 2
    by = cy - bh / 2 + h * 0.05

    # Parallax plane offsets
    bg_ox = -look_x * bw * 0.045
    bg_oy = -look_y * bh * 0.035
    fg_ox = look_x * bw * 0.065
    fg_oy = look_y * bh * 0.048

    p.save()
    if state == "thinking":
        p.translate(cx, cy)
        p.rotate(math.sin(phase * 2.5) * 4.5)
        p.translate(-cx, -cy)
    else:
        p.translate(cx, cy)
        p.rotate(look_x * 2.8)
        p.translate(-cx, -cy)

    head_w = bw * 0.74
    head_h = bh * 0.52
    hx = cx - head_w / 2
    hy = by + bh * 0.08

    # 1. Back Layer: Volumetric Pastel Pink Twin-Tails (Depth plane z = -0.45)
    tail_sway_l = math.sin(phase * 2.2) * bw * 0.08
    tail_sway_r = math.cos(phase * 2.2) * bw * 0.08
    p.setPen(QtGui.QPen(QtGui.QColor("#db2777"), max(2.0, w * 0.022)))
    tail_grad_l = QtGui.QLinearGradient(cx - bw * 0.5, by, cx - bw * 0.5, by + bh * 0.75)
    tail_grad_l.setColorAt(0.0, QtGui.QColor("#f472b6"))
    tail_grad_l.setColorAt(1.0, QtGui.QColor("#db2777"))
    p.setBrush(tail_grad_l)

    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(cx + bg_ox - bw * 0.35, by + bg_oy + bh * 0.18),
        QtCore.QPointF(cx + bg_ox - bw * 0.60 + tail_sway_l, by + bg_oy + bh * 0.40),
        QtCore.QPointF(cx + bg_ox - bw * 0.52 + tail_sway_l, by + bg_oy + bh * 0.75),
        QtCore.QPointF(cx + bg_ox - bw * 0.25, by + bg_oy + bh * 0.35),
    ]))

    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(cx + bg_ox + bw * 0.35, by + bg_oy + bh * 0.18),
        QtCore.QPointF(cx + bg_ox + bw * 0.60 + tail_sway_r, by + bg_oy + bh * 0.40),
        QtCore.QPointF(cx + bg_ox + bw * 0.52 + tail_sway_r, by + bg_oy + bh * 0.75),
        QtCore.QPointF(cx + bg_ox + bw * 0.25, by + bg_oy + bh * 0.35),
    ]))

    # 2. Mid Layer: Volumetric Sailor Blouse & Bow (z = 0.0)
    blouse_rect = QtCore.QRectF(cx - bw * 0.40, by + bh * 0.58, bw * 0.80, bh * 0.44)
    blouse_grad = QtGui.QLinearGradient(cx - bw * 0.40, by, cx + bw * 0.40, by)
    blouse_grad.setColorAt(0.0, QtGui.QColor("#f1f5f9"))
    blouse_grad.setColorAt(0.3, QtGui.QColor("#ffffff"))
    blouse_grad.setColorAt(0.7, QtGui.QColor("#ffffff"))
    blouse_grad.setColorAt(1.0, QtGui.QColor("#e2e8f0"))
    p.setBrush(blouse_grad)
    p.drawRoundedRect(blouse_rect, bw * 0.18, bw * 0.18)

    # Pink sailor tie / bow with depth
    p.setBrush(QtGui.QColor("#ec4899"))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(cx - bw * 0.10, by + bh * 0.62),
        QtCore.QPointF(cx, by + bh * 0.72),
        QtCore.QPointF(cx + bw * 0.10, by + bh * 0.62),
    ]))

    # 3. Head (Depth plane z = +0.2)
    head_light_x = cx - head_w * 0.18 + look_x * head_w * 0.05
    head_light_y = hy + head_h * 0.22 + look_y * head_h * 0.05
    skin_grad = QtGui.QRadialGradient(head_light_x, head_light_y, head_w * 0.76)
    skin_grad.setColorAt(0.0, QtGui.QColor("#fff5f5"))
    skin_grad.setColorAt(0.60, QtGui.QColor("#fce7f3"))
    skin_grad.setColorAt(1.0, QtGui.QColor("#fed7aa"))
    p.setBrush(skin_grad)
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024)))
    p.drawRoundedRect(QtCore.QRectF(hx, hy, head_w, head_h), head_w * 0.44, head_h * 0.44)

    # 4. Front Pink Bangs (Depth plane z = +0.45)
    bang_ox = fg_ox * 0.50
    bang_oy = fg_oy * 0.40
    p.setBrush(QtGui.QColor("#f472b6"))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(hx + bang_ox - bw * 0.04, hy + bang_oy + head_h * 0.35),
        QtCore.QPointF(hx + bang_ox + head_w * 0.15, hy + bang_oy - head_h * 0.18),
        QtCore.QPointF(hx + bang_ox + head_w * 0.50, hy + bang_oy - head_h * 0.22),
        QtCore.QPointF(hx + bang_ox + head_w * 0.85, hy + bang_oy - head_h * 0.18),
        QtCore.QPointF(hx + bang_ox + head_w * 1.04, hy + bang_oy + head_h * 0.35),
        QtCore.QPointF(hx + bang_ox + head_w * 0.80, hy + bang_oy + head_h * 0.25),
        QtCore.QPointF(hx + bang_ox + head_w * 0.55, hy + bang_oy + head_h * 0.32),
        QtCore.QPointF(hx + bang_ox + head_w * 0.45, hy + bang_oy + head_h * 0.20),
        QtCore.QPointF(hx + bang_ox + head_w * 0.25, hy + bang_oy + head_h * 0.28),
    ]))

    # 5. Foreground: Rosy Blush & 3D Anime Eyes (z = +0.65)
    p.setPen(QtCore.Qt.PenStyle.NoPen)
    for sign in (-1, 1):
        cheek_x = cx + sign * (head_w * 0.28) + fg_ox
        cheek_y = hy + head_h * 0.62 + fg_oy
        chk_grad = QtGui.QRadialGradient(cheek_x, cheek_y, head_w * 0.09)
        chk_grad.setColorAt(0.0, QtGui.QColor(251, 113, 133, 175))
        chk_grad.setColorAt(1.0, QtGui.QColor(251, 113, 133, 0))
        p.setBrush(chk_grad)
        p.drawEllipse(QtCore.QPointF(cheek_x, cheek_y), head_w * 0.09, head_h * 0.06)

    eye_y = hy + head_h * 0.48 + fg_oy
    eye_dx = head_w * 0.24
    eye_r = head_w * 0.10

    if blinking:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.025), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(QtCore.QRectF(cx - eye_dx + fg_ox - eye_r, eye_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
        p.drawArc(QtCore.QRectF(cx + eye_dx + fg_ox - eye_r, eye_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
    elif state == "happy":
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.4, w * 0.028), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(QtCore.QRectF(cx - eye_dx + fg_ox - eye_r, eye_y - eye_r * 0.4, eye_r * 2, eye_r * 1.2), 15 * 16, 150 * 16)
        p.drawArc(QtCore.QRectF(cx + eye_dx + fg_ox - eye_r, eye_y - eye_r * 0.4, eye_r * 2, eye_r * 1.2), 15 * 16, 150 * 16)
    else:
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        for sign in (-1, 1):
            ex = cx + sign * eye_dx + fg_ox
            ey = eye_y
            # Sclera
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r, eye_r * 1.15)
            # 3D Emerald green anime iris
            iris_grad = QtGui.QRadialGradient(ex, ey + eye_r * 0.12, eye_r * 0.85)
            iris_grad.setColorAt(0.0, QtGui.QColor("#34d399"))
            iris_grad.setColorAt(0.55, QtGui.QColor("#10b981"))
            iris_grad.setColorAt(1.0, QtGui.QColor("#065f46"))
            p.setBrush(iris_grad)
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 0.72, eye_r * 0.85)
            # Pupil
            p.setBrush(QtGui.QColor("#022c22"))
            p.drawEllipse(QtCore.QPointF(ex, ey + eye_r * 0.1), eye_r * 0.38, eye_r * 0.45)
            # Double glossy glass highlights
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawEllipse(QtCore.QPointF(ex - eye_r * 0.25, ey - eye_r * 0.28), eye_r * 0.28, eye_r * 0.28)
            p.drawEllipse(QtCore.QPointF(ex + eye_r * 0.20, ey + eye_r * 0.25), eye_r * 0.15, eye_r * 0.15)

    # Mouth
    mouth_y = hy + head_h * 0.74 + fg_oy
    mouth_x = cx + fg_ox
    if state == "talking":
        open_h = head_h * (0.06 + 0.045 * abs(math.sin(phase * 14.0)))
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(1.8, w * 0.02)))
        p.setBrush(QtGui.QColor("#fb7185"))
        p.drawEllipse(QtCore.QPointF(mouth_x, mouth_y), head_w * 0.075, open_h)
    else:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.022), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawArc(QtCore.QRectF(mouth_x - head_w * 0.06, mouth_y - head_h * 0.03, head_w * 0.12, head_h * 0.08), 200 * 16, 140 * 16)

    p.restore()

    # Floating hearts when happy
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
    """Paint Aria with 2.5D multi-plane parallax, 3D holographic eyepiece, and glowing cyber circuits."""
    cx = bounds.center().x()
    cy = bounds.center().y()
    w = bounds.width()
    h = bounds.height()

    shadow_scale = 0.8 if state in ("talking", "happy") else 1.0
    _paint_ground_shadow(p, bounds, shadow_scale, look_x, look_y)

    bw = w * 0.60
    bh = h * 0.64
    bx = cx - bw / 2
    by = cy - bh / 2 + h * 0.05

    # Parallax plane offsets
    bg_ox = -look_x * bw * 0.045
    bg_oy = -look_y * bh * 0.035
    fg_ox = look_x * bw * 0.065
    fg_oy = look_y * bh * 0.048

    p.save()
    if state == "thinking":
        p.translate(cx, cy)
        p.rotate(math.sin(phase * 2.2) * 4.0)
        p.translate(-cx, -cy)
    else:
        p.translate(cx, cy)
        p.rotate(look_x * 2.8)
        p.translate(-cx, -cy)

    head_w = bw * 0.74
    head_h = bh * 0.52
    hx = cx - head_w / 2
    hy = by + bh * 0.08

    # 1. Back Layer: Cyber Bob Rear Hair (Depth plane z = -0.45)
    p.setBrush(QtGui.QColor("#0f766e"))
    p.setPen(QtGui.QPen(QtGui.QColor("#115e59"), max(2.0, w * 0.022)))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(hx + bg_ox - bw * 0.10, hy + bg_oy + head_h * 0.68),
        QtCore.QPointF(hx + bg_ox - bw * 0.08, hy + bg_oy + head_h * 0.15),
        QtCore.QPointF(hx + bg_ox + head_w * 0.20, hy + bg_oy - head_h * 0.20),
        QtCore.QPointF(hx + bg_ox + head_w * 0.80, hy + bg_oy - head_h * 0.20),
        QtCore.QPointF(hx + bg_ox + head_w * 1.08, hy + bg_oy + head_h * 0.15),
        QtCore.QPointF(hx + bg_ox + head_w * 1.10, hy + bg_oy + head_h * 0.68),
    ]))

    # 2. Mid Layer: Volumetric Cyber Jacket (z = 0.0)
    jacket_rect = QtCore.QRectF(cx - bw * 0.40, by + bh * 0.58, bw * 0.80, bh * 0.44)
    jacket_grad = QtGui.QLinearGradient(cx - bw * 0.40, by, cx + bw * 0.40, by)
    jacket_grad.setColorAt(0.0, QtGui.QColor("#0f172a"))
    jacket_grad.setColorAt(0.35, QtGui.QColor("#334155"))
    jacket_grad.setColorAt(0.70, QtGui.QColor("#1e293b"))
    jacket_grad.setColorAt(1.0, QtGui.QColor("#0f172a"))
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.022)))
    p.setBrush(jacket_grad)
    p.drawRoundedRect(jacket_rect, bw * 0.18, bw * 0.18)

    # Neon teal trim lines with 3D perspective
    stripe_cx = cx + look_x * bw * 0.03
    p.setPen(QtGui.QPen(QtGui.QColor("#2dd4bf"), max(1.8, w * 0.02)))
    p.drawLine(QtCore.QPointF(stripe_cx - bw * 0.20, by + bh * 0.58), QtCore.QPointF(stripe_cx - bw * 0.10, by + bh * 0.98))
    p.drawLine(QtCore.QPointF(stripe_cx + bw * 0.20, by + bh * 0.58), QtCore.QPointF(stripe_cx + bw * 0.10, by + bh * 0.98))

    # 3. Head: Pale Porcelain Cyber Skin (Depth plane z = +0.2)
    head_light_x = cx - head_w * 0.18 + look_x * head_w * 0.05
    head_light_y = hy + head_h * 0.22 + look_y * head_h * 0.05
    skin_grad = QtGui.QRadialGradient(head_light_x, head_light_y, head_w * 0.76)
    skin_grad.setColorAt(0.0, QtGui.QColor("#ffffff"))
    skin_grad.setColorAt(0.60, QtGui.QColor("#f1f5f9"))
    skin_grad.setColorAt(1.0, QtGui.QColor("#cbd5e1"))
    p.setBrush(skin_grad)
    p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.024)))
    p.drawRoundedRect(QtCore.QRectF(hx, hy, head_w, head_h), head_w * 0.44, head_h * 0.44)

    # 4. Front Cyber Bob Bangs (Depth plane z = +0.45)
    bang_ox = fg_ox * 0.50
    bang_oy = fg_oy * 0.40
    hair_grad = QtGui.QLinearGradient(cx, hy, cx, hy + head_h)
    hair_grad.setColorAt(0.0, QtGui.QColor("#14b8a6"))
    hair_grad.setColorAt(1.0, QtGui.QColor("#0d9488"))
    p.setBrush(hair_grad)
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(hx + bang_ox - bw * 0.08, hy + bang_oy + head_h * 0.65),
        QtCore.QPointF(hx + bang_ox - bw * 0.06, hy + bang_oy + head_h * 0.15),
        QtCore.QPointF(hx + bang_ox + head_w * 0.20, hy + bang_oy - head_h * 0.18),
        QtCore.QPointF(hx + bang_ox + head_w * 0.50, hy + bang_oy - head_h * 0.20),
        QtCore.QPointF(hx + bang_ox + head_w * 0.80, hy + bang_oy - head_h * 0.18),
        QtCore.QPointF(hx + bang_ox + head_w * 1.06, hy + bang_oy + head_h * 0.15),
        QtCore.QPointF(hx + bang_ox + head_w * 1.08, hy + bang_oy + head_h * 0.65),
        QtCore.QPointF(hx + bang_ox + head_w * 0.90, hy + bang_oy + head_h * 0.30),
        QtCore.QPointF(hx + bang_ox + head_w * 0.50, hy + bang_oy + head_h * 0.20),
        QtCore.QPointF(hx + bang_ox + head_w * 0.10, hy + bang_oy + head_h * 0.30),
    ]))

    # 5. Foreground: 3D Teal Eyes (z = +0.65)
    eye_y = hy + head_h * 0.48 + fg_oy
    eye_dx = head_w * 0.24
    eye_r = head_w * 0.095

    if blinking:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.2, w * 0.025), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.drawArc(QtCore.QRectF(cx - eye_dx + fg_ox - eye_r, eye_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
        p.drawArc(QtCore.QRectF(cx + eye_dx + fg_ox - eye_r, eye_y - eye_r * 0.3, eye_r * 2, eye_r), 0, 180 * 16)
    else:
        p.setPen(QtCore.Qt.PenStyle.NoPen)
        for sign in (-1, 1):
            ex = cx + sign * eye_dx + fg_ox
            ey = eye_y
            # Sclera
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r, eye_r * 1.1)
            # 3D Teal iris
            iris_grad = QtGui.QRadialGradient(ex, ey + eye_r * 0.1, eye_r * 0.72)
            iris_grad.setColorAt(0.0, QtGui.QColor("#5eead4"))
            iris_grad.setColorAt(0.55, QtGui.QColor("#14b8a6"))
            iris_grad.setColorAt(1.0, QtGui.QColor("#0f766e"))
            p.setBrush(iris_grad)
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 0.68, eye_r * 0.75)
            # Pupil
            p.setBrush(QtGui.QColor("#0f172a"))
            p.drawEllipse(QtCore.QPointF(ex, ey), eye_r * 0.35, eye_r * 0.40)
            # Glass catchlight
            p.setBrush(QtGui.QColor("#ffffff"))
            p.drawEllipse(QtCore.QPointF(ex - eye_r * 0.22, ey - eye_r * 0.25), eye_r * 0.24, eye_r * 0.24)

    # 6. Floating 3D Holographic Eyepiece over left eye (Depth plane z = +0.70)
    eyepiece_x = cx - eye_dx + fg_ox * 1.1
    eyepiece_y = eye_y + fg_oy * 1.1
    eyepiece_rect = QtCore.QRectF(eyepiece_x - eye_r * 1.3, eyepiece_y - eye_r * 1.2, eye_r * 2.6, eye_r * 2.4)
    p.setPen(QtGui.QPen(QtGui.QColor("#2dd4bf"), 1.8))
    p.setBrush(QtGui.QColor(45, 212, 191, 55))
    p.drawRoundedRect(eyepiece_rect, 4, 4)
    # Eyepiece crosshair target
    p.drawLine(QtCore.QPointF(eyepiece_x - eye_r * 0.5, eyepiece_y), QtCore.QPointF(eyepiece_x + eye_r * 0.5, eyepiece_y))
    p.drawLine(QtCore.QPointF(eyepiece_x, eyepiece_y - eye_r * 0.5), QtCore.QPointF(eyepiece_x, eyepiece_y + eye_r * 0.5))

    # Mouth
    mouth_y = hy + head_h * 0.74 + fg_oy
    mouth_x = cx + fg_ox
    if state == "talking":
        open_h = head_h * (0.06 + 0.045 * abs(math.sin(phase * 14.0)))
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(1.8, w * 0.02)))
        p.setBrush(QtGui.QColor("#2dd4bf"))
        p.drawEllipse(QtCore.QPointF(mouth_x, mouth_y), head_w * 0.075, open_h)
    else:
        p.setPen(QtGui.QPen(QtGui.QColor("#0f172a"), max(2.0, w * 0.022), QtCore.Qt.PenStyle.SolidLine, QtCore.Qt.PenCapStyle.RoundCap))
        p.setBrush(QtCore.Qt.BrushStyle.NoBrush)
        p.drawArc(QtCore.QRectF(mouth_x - head_w * 0.06, mouth_y - head_h * 0.03, head_w * 0.12, head_h * 0.08), 200 * 16, 140 * 16)

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
