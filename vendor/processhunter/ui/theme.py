from __future__ import annotations
import sys
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget


DARK_THEME_QSS = """
/* ==========================================================================
   ProcessHunter - Tema Escuro Fiel ao HTTP Server Manager
   Paleta:
   - Fundo da janela: #2e2e2e
   - Painéis e cartões: #292929 (borda #404040, raio 6px)
   - Header superior: #262626 (borda #3d3d3d, raio 6px)
   - Inputs, tabelas e console: #1e1e1e (borda #444444)
   - Botões padrão: #404040 (borda #525252, texto #efefef, raio 4px)
   - Acento ativo / Play: #3cd070 (verde esmeralda vibrante)
   - Textos: #f0f0f0 (primário), #9e9e9e (secundário/descrições)
   ========================================================================== */

/* Configuração Global */
QWidget {
    background-color: #2e2e2e;
    color: #e2e2e2;
    font-family: "Segoe UI", "Segoe UI Variable Text", system-ui, -apple-system, sans-serif;
    font-size: 10pt;
    selection-background-color: #3b506b;
    selection-color: #ffffff;
}

QMainWindow, QDialog {
    background-color: #2e2e2e;
}

/* Rótulos e Títulos */
QLabel {
    color: #e0e0e0;
    background-color: transparent;
}

QLabel[heading="true"] {
    color: #ffffff;
    font-size: 10.5pt;
    font-weight: 700;
}

QLabel[subtitle="true"] {
    color: #9e9e9e;
    font-size: 9pt;
}

/* Painéis de Cartão (TargetListWidget, ProcessTableWidget, Bottom Card, Header) */
TargetListWidget, ProcessTableWidget {
    background-color: #292929;
    border: 1px solid #404040;
    border-radius: 6px;
    padding: 6px;
}

QFrame#header_card {
    background-color: #262626;
    border: 1px solid #3d3d3d;
    border-radius: 6px;
    padding: 4px;
}

QFrame#bottom_card {
    background-color: #292929;
    border: 1px solid #404040;
    border-radius: 6px;
    padding: 8px;
}

/* Divisor Splitter */
QSplitter::handle {
    background-color: #383838;
    width: 4px;
    height: 4px;
}

QSplitter::handle:hover {
    background-color: #505050;
}

/* Botões Padrão (Estilo HTTP Server Manager: START, LOGS, Copy URL, QR Code) */
QPushButton {
    background-color: #404040;
    border: 1px solid #525252;
    border-radius: 4px;
    color: #efefef;
    font-weight: 600;
    padding: 6px 14px;
    outline: none;
    min-height: 18px;
}

QPushButton:hover {
    background-color: #4d4d4d;
    border-color: #636363;
    color: #ffffff;
}

QPushButton:pressed {
    background-color: #333333;
    border-color: #404040;
}

QPushButton:disabled {
    background-color: #292929;
    border-color: #383838;
    color: #666666;
}

/* Botão de Destaque: Caçar Agora */
QPushButton#btn_hunt_now {
    background-color: #3a2828;
    border: 1px solid #7c3333;
    color: #ffb8b8;
    font-weight: bold;
    padding: 7px 16px;
    border-radius: 4px;
}

QPushButton#btn_hunt_now:hover {
    background-color: #542929;
    border-color: #a84242;
    color: #ffffff;
}

QPushButton#btn_hunt_now:pressed {
    background-color: #291818;
}

/* Campos de Entrada de Texto */
QLineEdit {
    background-color: #1e1e1e;
    border: 1px solid #484848;
    border-radius: 4px;
    color: #ffffff;
    padding: 6px 10px;
    selection-background-color: #3b506b;
}

QLineEdit:focus {
    border: 1px solid #3cd070;
    background-color: #222222;
}

QLineEdit:disabled {
    background-color: #282828;
    border-color: #383838;
    color: #666666;
}

/* Campo Numérico (SpinBox) */
QSpinBox {
    background-color: #1e1e1e;
    border: 1px solid #484848;
    border-radius: 4px;
    color: #ffffff;
    padding: 5px 8px;
}

QSpinBox:focus {
    border: 1px solid #3cd070;
}

QSpinBox::up-button, QSpinBox::down-button {
    background-color: #383838;
    border: none;
    width: 16px;
    border-radius: 2px;
}

QSpinBox::up-button:hover, QSpinBox::down-button:hover {
    background-color: #4e4e4e;
}

/* Tabelas */
QTableWidget {
    background-color: #202020;
    alternate-background-color: #252525;
    border: 1px solid #3e3e3e;
    border-radius: 4px;
    gridline-color: #323232;
    color: #e0e0e0;
    outline: none;
}

QTableWidget::item {
    padding: 5px 6px;
    border-bottom: 1px solid #282828;
}

QTableWidget::item:selected {
    background-color: #344759;
    color: #ffffff;
}

QTableWidget::item:hover {
    background-color: #2b333d;
}

/* Cabeçalho da Tabela */
QHeaderView::section {
    background-color: #333333;
    color: #d6d6d6;
    padding: 6px 8px;
    border: none;
    border-right: 1px solid #3e3e3e;
    border-bottom: 1px solid #484848;
    font-weight: bold;
}

/* Checkboxes */
QCheckBox {
    color: #dcdcdc;
    spacing: 8px;
    background-color: transparent;
}

QCheckBox:disabled {
    color: #666666;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    background-color: #1e1e1e;
    border: 1px solid #525252;
    border-radius: 3px;
}

QCheckBox::indicator:hover {
    border-color: #6a6a6a;
}

QCheckBox::indicator:checked {
    background-color: #3cd070;
    border-color: #3cd070;
}

/* Console de Logs */
QTextEdit#log_view {
    background-color: #1a1a1a;
    border: 1px solid #383838;
    border-radius: 4px;
    color: #d4d4d4;
    font-family: Consolas, monospace;
    font-size: 9.5pt;
    padding: 6px;
}

/* Menus de Contexto (Tray e UI) */
QMenu {
    background-color: #2a2a2a;
    border: 1px solid #484848;
    border-radius: 5px;
    padding: 4px;
    color: #ffffff;
}

QMenu::item {
    padding: 6px 24px 6px 16px;
    border-radius: 3px;
}

QMenu::item:selected {
    background-color: #384656;
    color: #ffffff;
}

QMenu::separator {
    height: 1px;
    background-color: #404040;
    margin: 4px 6px;
}

/* Barras de Rolagem Customizadas */
QScrollBar:vertical {
    background-color: #222222;
    width: 10px;
    margin: 0;
    border-radius: 5px;
}

QScrollBar::handle:vertical {
    background-color: #464646;
    min-height: 25px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background-color: #5a5a5a;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    background-color: #222222;
    height: 10px;
    margin: 0;
    border-radius: 5px;
}

QScrollBar::handle:horizontal {
    background-color: #464646;
    min-width: 25px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal:hover {
    background-color: #5a5a5a;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* Tooltips */
QToolTip {
    background-color: #222222;
    color: #ffffff;
    border: 1px solid #484848;
    border-radius: 4px;
    padding: 5px 8px;
}

/* Caixas de Mensagem */
QMessageBox {
    background-color: #2e2e2e;
}

QMessageBox QLabel {
    color: #f0f0f0;
}
"""

# Estilos dinâmicos do botão da Sentinela
STYLE_SENTINEL_PAUSED = """
QPushButton#btn_toggle_sentinel {
    background-color: #214d2e;
    border: 1px solid #3cd070;
    color: #eaffea;
    font-weight: bold;
    padding: 7px 16px;
    border-radius: 4px;
}
QPushButton#btn_toggle_sentinel:hover {
    background-color: #2b613a;
    border-color: #51e687;
    color: #ffffff;
}
QPushButton#btn_toggle_sentinel:pressed {
    background-color: #173720;
}
"""

STYLE_SENTINEL_ACTIVE = """
QPushButton#btn_toggle_sentinel {
    background-color: #4e3818;
    border: 1px solid #e0982d;
    color: #ffeedb;
    font-weight: bold;
    padding: 7px 16px;
    border-radius: 4px;
}
QPushButton#btn_toggle_sentinel:hover {
    background-color: #64491f;
    border-color: #fca835;
    color: #ffffff;
}
QPushButton#btn_toggle_sentinel:pressed {
    background-color: #382710;
}
"""


def create_dark_palette() -> QPalette:
    palette = QPalette()
    dark_bg = QColor(46, 46, 46)        # #2e2e2e
    panel_bg = QColor(41, 41, 41)       # #292929
    input_bg = QColor(30, 30, 30)       # #1e1e1e
    text_color = QColor(240, 240, 240)  # #f0f0f0
    dim_text = QColor(158, 158, 158)    # #9e9e9e
    btn_bg = QColor(64, 64, 64)         # #404040

    palette.setColor(QPalette.ColorRole.Window, dark_bg)
    palette.setColor(QPalette.ColorRole.WindowText, text_color)
    palette.setColor(QPalette.ColorRole.Base, input_bg)
    palette.setColor(QPalette.ColorRole.AlternateBase, panel_bg)
    palette.setColor(QPalette.ColorRole.ToolTipBase, dark_bg)
    palette.setColor(QPalette.ColorRole.ToolTipText, text_color)
    palette.setColor(QPalette.ColorRole.Text, text_color)
    palette.setColor(QPalette.ColorRole.Button, btn_bg)
    palette.setColor(QPalette.ColorRole.ButtonText, text_color)
    palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.Highlight, QColor(58, 80, 107))
    palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.white)
    palette.setColor(QPalette.ColorRole.PlaceholderText, dim_text)

    # Estados desabilitados
    disabled_text = QColor(105, 105, 105)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled_text)
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor(50, 50, 50))
    return palette


def apply_dark_theme(app: QApplication) -> None:
    """Aplica o tema escuro completo no nível da aplicação."""
    app.setStyle("Fusion")
    app.setPalette(create_dark_palette())
    app.setStyleSheet(DARK_THEME_QSS)


def apply_dark_title_bar(window: QWidget) -> None:
    """Ativa a barra de título nativa escura no Windows 10/11."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(window.winId())
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        set_window_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
        val = ctypes.c_int(1)
        res = set_window_attribute(
            hwnd,
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(val),
            ctypes.sizeof(val)
        )
        if res != 0:
            # Fallback para versões mais antigas do Windows 10
            set_window_attribute(hwnd, 19, ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass
