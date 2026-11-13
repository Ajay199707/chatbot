"""Unit tests for Character Painters and Animated Avatar Gallery."""

import os
from pathlib import Path
import pytest
from PySide6 import QtCore, QtGui, QtWidgets

import character_painters as cp
import desktop_companion as dc


def _get_qapp() -> QtWidgets.QApplication:
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_character_presets_defined():
    expected_ids = {
        "lumi",
        "ben_tennyson",
        "gwen_classic",
        "gwen_mana",
        "heatblast",
        "fourarms",
        "xlr8",
        "anime_sakura",
        "cyber_aria",
    }
    assert expected_ids.issubset(set(cp.CHARACTER_PRESETS.keys()))

    for cid, preset in cp.CHARACTER_PRESETS.items():
        assert preset.id == cid
        assert len(preset.name) > 0
        assert preset.category in ("Original Pets", "Ben 10 Universe", "Female Characters")
        assert preset.accent_color.startswith("#")
        assert len(preset.personality_prompt) > 20
        assert len(preset.description) > 10


def test_get_character_preset_fallback():
    assert cp.get_character_preset("ben_tennyson").name == "Ben Tennyson"
    assert cp.get_character_preset("gwen_mana").category == "Female Characters"
    assert cp.get_character_preset("unknown_alien").id == "lumi"
    assert cp.get_character_preset("").id == "lumi"


def test_list_character_categories():
    cats = cp.list_character_categories()
    assert cats[0] == "All"
    assert "Original Pets" in cats
    assert "Ben 10 Universe" in cats
    assert "Female Characters" in cats
    assert len(cats) == len(set(cats))


def test_paint_all_characters_all_states():
    _get_qapp()
    for cid in cp.CHARACTER_PRESETS:
        for state in ("idle", "talking", "thinking", "happy"):
            pm = QtGui.QPixmap(100, 100)
            pm.fill(QtCore.Qt.GlobalColor.transparent)
            p = QtGui.QPainter(pm)
            p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

            # Test normal eye state
            cp.paint_animated_character(
                cid,
                p,
                QtCore.QRectF(2, 2, 96, 96),
                phase=1.57,
                state=state,
                blinking=False,
                look_x=0.4,
                look_y=-0.2,
            )
            # Test blinking state
            cp.paint_animated_character(
                cid,
                p,
                QtCore.QRectF(2, 2, 96, 96),
                phase=3.14,
                state=state,
                blinking=True,
                look_x=-0.5,
                look_y=0.5,
            )
            p.end()
            assert not pm.isNull()


def test_draw_character_pixmap():
    _get_qapp()
    pm34 = cp.draw_character_pixmap(34, character_id="ben_tennyson")
    assert pm34.width() == 34 and pm34.height() == 34
    assert not pm34.isNull()

    pm64 = cp.draw_character_pixmap(64, character_id="heatblast")
    assert pm64.width() == 64 and pm64.height() == 64
    assert not pm64.isNull()


def test_character_preview_widget():
    _get_qapp()
    w = dc.CharacterPreviewWidget("gwen_classic", size=60)
    try:
        assert w._character_id == "gwen_classic"
        w._on_tick()
        assert w._phase > 0.0
        w.set_character_id("xlr8")
        assert w._character_id == "xlr8"
    finally:
        w.deleteLater()


def test_avatar_gallery_dialog_selection_and_filter():
    _get_qapp()
    dlg = dc.AvatarGalleryDialog(current_character_id="ben_tennyson")
    try:
        assert dlg._selected_id == "ben_tennyson"
        preset, sync = dlg.get_selected_preset()
        assert preset.id == "ben_tennyson"
        assert sync is True

        # Test category filtering
        dlg._filter_category("Female Characters")
        assert "gwen_mana" in dlg._cards
        assert "anime_sakura" in dlg._cards
        assert "fourarms" not in dlg._cards

        # Test card click
        dlg._on_card_clicked("anime_sakura")
        selected_p, _ = dlg.get_selected_preset()
        assert selected_p.id == "anime_sakura"

        dlg._filter_category("Ben 10 Universe")
        assert "heatblast" in dlg._cards
        assert "anime_sakura" not in dlg._cards
    finally:
        dlg.close()
        dlg.deleteLater()


def test_character_config_character_id_persistence(tmp_path):
    cfg_file = tmp_path / "character_config.json"
    cfg = dc.CharacterConfig(character_id="fourarms", character_name="Four Arms")
    cfg.save(cfg_file)

    loaded = dc.CharacterConfig.load(cfg_file)
    assert loaded.character_id == "fourarms"
    assert loaded.character_name == "Four Arms"

    # Test unknown fallback
    cfg_file.write_text('{"character_id": "alien_x_unknown"}', encoding="utf-8")
    loaded2 = dc.CharacterConfig.load(cfg_file)
    assert loaded2.character_id == "lumi"


def test_character_widget_preset_switching():
    _get_qapp()
    cfg = dc.CharacterConfig(character_id="ben_tennyson")
    w = dc.CharacterWidget(cfg)
    try:
        assert w._config.character_id == "ben_tennyson"
        pm = QtGui.QPixmap(100, 100)
        p = QtGui.QPainter(pm)
        w.paintEvent(QtGui.QPaintEvent(QtCore.QRect(0, 0, 100, 100)))
        p.end()
    finally:
        w.deleteLater()
