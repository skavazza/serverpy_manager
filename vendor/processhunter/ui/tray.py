from __future__ import annotations
from typing import List
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PySide6.QtWidgets import QSystemTrayIcon, QMenu
from vendor.processhunter.core.hunter import KillResult


def create_tray_pixmap(is_active: bool = False) -> QPixmap:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Base circle / target symbol
    bg_color = QColor(33, 150, 243) if not is_active else QColor(46, 125, 50)
    painter.setBrush(bg_color)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(4, 4, 56, 56)

    # Crosshair / Icon
    painter.setPen(QColor(255, 255, 255))
    font = QFont("Segoe UI", 24, QFont.Weight.Bold)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "🎯")

    painter.end()
    return pixmap


class HunterTrayIcon(QSystemTrayIcon):
    restore_requested = Signal()
    hunt_now_requested = Signal()
    toggle_sentinel_requested = Signal()
    exit_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setIcon(QIcon(create_tray_pixmap(is_active=False)))
        self.setToolTip("ProcessHunter - Monitor de Processos")
        self._init_menu()
        self.activated.connect(self._on_activated)

    def _init_menu(self) -> None:
        menu = QMenu()

        self.action_restore = menu.addAction("🖥️ Abrir ProcessHunter")
        self.action_restore.triggered.connect(self.restore_requested.emit)

        menu.addSeparator()

        self.action_hunt_now = menu.addAction("⚡ Caçar Agora")
        self.action_hunt_now.triggered.connect(self.hunt_now_requested.emit)

        self.action_toggle_sentinel = menu.addAction("🛡️ Iniciar Sentinela")
        self.action_toggle_sentinel.triggered.connect(self.toggle_sentinel_requested.emit)

        menu.addSeparator()

        self.action_exit = menu.addAction("❌ Sair do ProcessHunter")
        self.action_exit.triggered.connect(self.exit_requested.emit)

        self.setContextMenu(menu)

    def update_status(self, is_sentinel_active: bool) -> None:
        self.setIcon(QIcon(create_tray_pixmap(is_active=is_sentinel_active)))
        if is_sentinel_active:
            self.setToolTip("ProcessHunter - Sentinela ATIVA")
            self.action_toggle_sentinel.setText("⏸️ Pausar Sentinela")
        else:
            self.setToolTip("ProcessHunter - Sentinela PAUSADA")
            self.action_toggle_sentinel.setText("🛡️ Iniciar Sentinela")

    def notify_kill(self, results: List[KillResult]) -> None:
        successes = [r for r in results if r.success]
        if not successes:
            return

        summary = ", ".join(f"'{r.name}' (PID: {r.pid})" for r in successes[:3])
        if len(successes) > 3:
            summary += f" e mais {len(successes) - 3}..."

        self.showMessage(
            "ProcessHunter - Alvos Encerrados",
            f"Processo(s) encerrado(s): {summary}",
            QSystemTrayIcon.MessageIcon.Information,
            3000
        )

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick
        ):
            self.restore_requested.emit()
