"""Compact icon toolbar backed by the existing menu actions."""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QToolBar


_ICONS = {
    'start': ('#7ddc96', '<path d="m8 5 11 7-11 7Z"/>'),
    'stop': ('#f28b82', '<rect x="6" y="6" width="12" height="12" rx="1"/>'),
    'logs': ('#dce5f0', '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>'),
    'open': ('#dce5f0', '<path d="M14 3h7v7M21 3l-9 9M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"/>'),
    'copy': ('#dce5f0', '<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h3"/>'),
    'qr': ('#dce5f0', '<path d="M3 3h6v6H3ZM15 3h6v6h-6ZM3 15h6v6H3ZM15 15h3v3h3v3h-6ZM12 3v3M12 10v3h-2M3 12h3M15 12h6M12 18v3M21 12v3"/>'),
    'about': ('#dce5f0', '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>'),
}


def _icon(key):
    color, shapes = _ICONS[key]
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
           f'fill="none" stroke="{color}" stroke-width="1.7" '
           f'stroke-linecap="round" stroke-linejoin="round">{shapes}</svg>')
    renderer = QSvgRenderer(svg.encode('utf-8'))
    pixmap = QPixmap(48, 48)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


def create_action_toolbar(window, actions):
    toolbar = QToolBar(window)
    toolbar.setObjectName('action_toolbar')
    toolbar.setMovable(False)
    toolbar.setFloatable(False)
    toolbar.setContextMenuPolicy(Qt.PreventContextMenu)
    toolbar.setIconSize(QSize(22, 22))
    toolbar.setToolButtonStyle(Qt.ToolButtonIconOnly)
    toolbar.setStyleSheet('QToolBar { spacing: 4px; padding: 3px 8px; border: 0; '
                         'border-bottom: 1px solid #484848; } '
                         'QToolButton { min-width: 36px; min-height: 36px; border-radius: 4px; } '
                         'QToolButton:hover { background: #454545; }')
    for key in ('start', 'stop', None, 'logs', None, 'copy', 'open', 'qr', None, 'about'):
        if key is None:
            toolbar.addSeparator()
            continue
        action = actions[key]
        action.setIcon(_icon(key))
        toolbar.addAction(action)
        button = toolbar.widgetForAction(action)
        button.setFocusPolicy(Qt.StrongFocus)
        button.setAccessibleName(action.text())
        action.changed.connect(lambda button=button, action=action: button.setAccessibleName(action.text()))
    window.addToolBar(Qt.TopToolBarArea, toolbar)
    return toolbar
