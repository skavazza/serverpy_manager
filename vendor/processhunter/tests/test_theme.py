import pytest
from PySide6.QtWidgets import QApplication, QWidget
from vendor.processhunter.ui.theme import (
    DARK_THEME_QSS,
    STYLE_SENTINEL_PAUSED,
    STYLE_SENTINEL_ACTIVE,
    create_dark_palette,
    apply_dark_theme,
    apply_dark_title_bar
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_theme_constants():
    assert len(DARK_THEME_QSS) > 100
    assert "#2e2e2e" in DARK_THEME_QSS or "#2f2f2f" in DARK_THEME_QSS
    assert "#404040" in DARK_THEME_QSS
    assert "#3cd070" in DARK_THEME_QSS
    assert "btn_hunt_now" in DARK_THEME_QSS
    assert "btn_toggle_sentinel" in STYLE_SENTINEL_PAUSED
    assert "btn_toggle_sentinel" in STYLE_SENTINEL_ACTIVE


def test_create_dark_palette(qapp):
    palette = create_dark_palette()
    assert palette is not None
    # Check that dark background is set
    window_color = palette.window().color()
    assert window_color.red() < 60
    assert window_color.green() < 60
    assert window_color.blue() < 60


def test_apply_dark_theme(qapp):
    apply_dark_theme(qapp)
    assert len(qapp.styleSheet()) > 0


def test_apply_dark_title_bar(qapp):
    w = QWidget()
    # Should not raise exception
    apply_dark_title_bar(w)
