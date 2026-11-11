from __future__ import annotations
from typing import List, Dict
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLabel, QAbstractItemView
)
from vendor.processhunter.core.config import TargetItem


class TargetListWidget(QWidget):
    target_added = Signal(str)
    target_removed = Signal(str)
    target_toggled = Signal(str, bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._targets: List[TargetItem] = []
        self._running_counts: Dict[str, int] = {}
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title_label = QLabel("Alvos do Hunter (Processos a Encerrar)")
        title_label.setProperty("heading", "true")
        layout.addWidget(title_label)

        subtitle_label = QLabel("Processos monitorados para encerramento automático.")
        subtitle_label.setProperty("subtitle", "true")
        layout.addWidget(subtitle_label)

        # Add target input row
        input_layout = QHBoxLayout()
        self.input_target = QLineEdit()
        self.input_target.setPlaceholderText("Digite o nome do executável (ex: spotify.exe)...")
        self.input_target.returnPressed.connect(self._on_add_clicked)
        input_layout.addWidget(self.input_target)

        self.btn_add = QPushButton("➕ Adicionar")
        self.btn_add.clicked.connect(self._on_add_clicked)
        input_layout.addWidget(self.btn_add)
        layout.addLayout(input_layout)

        # Target Table
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Ativo", "Processo Alvo", "Ações"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self.table)

        self.summary_label = QLabel("0 alvos configurados")
        self.summary_label.setProperty("subtitle", "true")
        layout.addWidget(self.summary_label)

    def set_targets(self, targets: List[TargetItem]) -> None:
        self._targets = targets
        self.table.blockSignals(True)
        self.table.setRowCount(len(targets))

        for row, t in enumerate(targets):
            # Checkbox item
            check_item = QTableWidgetItem()
            check_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            check_item.setCheckState(Qt.CheckState.Checked if t.enabled else Qt.CheckState.Unchecked)
            check_item.setData(Qt.ItemDataRole.UserRole, t.name)
            self.table.setItem(row, 0, check_item)

            # Name item
            name_text = t.name
            count = self._running_counts.get(t.name.lower(), 0)
            if count > 0:
                name_text += f" ({count} ativo{'s' if count > 1 else ''})"

            name_item = QTableWidgetItem(name_text)
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            self.table.setItem(row, 1, name_item)

            # Delete button
            btn_del = QPushButton("🗑️")
            btn_del.setToolTip("Remover alvo")
            btn_del.setFixedWidth(36)
            btn_del.setStyleSheet("""
                QPushButton {
                    background-color: #383838;
                    border: 1px solid #4a4a4a;
                    border-radius: 3px;
                    padding: 2px 4px;
                }
                QPushButton:hover {
                    background-color: #552828;
                    border-color: #883a3a;
                }
            """)
            # Capture current target name
            target_name = t.name
            btn_del.clicked.connect(lambda checked=False, name=target_name: self.target_removed.emit(name))
            self.table.setCellWidget(row, 2, btn_del)

        self.table.blockSignals(False)
        active_count = sum(1 for t in targets if t.enabled)
        self.summary_label.setText(f"{len(targets)} alvos ({active_count} ativos)")

    def update_running_counts(self, counts: Dict[str, int]) -> None:
        self._running_counts = counts
        self.set_targets(self._targets)

    def _on_add_clicked(self) -> None:
        text = self.input_target.text().strip()
        if text:
            self.target_added.emit(text)
            self.input_target.clear()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() == 0:
            target_name = item.data(Qt.ItemDataRole.UserRole)
            if target_name:
                is_checked = item.checkState() == Qt.CheckState.Checked
                self.target_toggled.emit(target_name, is_checked)
