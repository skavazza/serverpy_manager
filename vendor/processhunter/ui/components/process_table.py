from __future__ import annotations
from typing import List
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLabel, QAbstractItemView
)
from vendor.processhunter.core.hunter import ProcessInfo


class ProcessTableWidget(QWidget):
    add_target_requested = Signal(str)
    refresh_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._processes: List[ProcessInfo] = []
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        title_label = QLabel("Processos em Execução no Windows")
        title_label.setProperty("heading", "true")
        layout.addWidget(title_label)

        subtitle_label = QLabel("Selecione ou clique duas vezes para adicionar à lista de alvos.")
        subtitle_label.setProperty("subtitle", "true")
        layout.addWidget(subtitle_label)

        # Filter bar
        filter_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Filtrar processos em execução...")
        self.search_input.textChanged.connect(self._filter_table)
        filter_layout.addWidget(self.search_input)

        self.btn_refresh = QPushButton("🔄 Atualizar")
        self.btn_refresh.clicked.connect(self.refresh_requested.emit)
        filter_layout.addWidget(self.btn_refresh)
        layout.addLayout(filter_layout)

        # Process Table
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["PID", "Nome do Processo", "Memória (MB)"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.doubleClicked.connect(self._on_row_double_clicked)
        layout.addWidget(self.table)

        # Action bar
        action_layout = QHBoxLayout()
        self.status_count_label = QLabel("Total: 0 processos")
        self.status_count_label.setProperty("subtitle", "true")
        action_layout.addWidget(self.status_count_label)
        action_layout.addStretch()

        self.btn_add_to_targets = QPushButton("🎯 Adicionar aos Alvos")
        self.btn_add_to_targets.clicked.connect(self._on_add_clicked)
        action_layout.addWidget(self.btn_add_to_targets)

        layout.addLayout(action_layout)

    def set_processes(self, processes: List[ProcessInfo]) -> None:
        self._processes = processes
        self.table.setRowCount(len(processes))

        for row, p in enumerate(processes):
            item_pid = QTableWidgetItem(str(p.pid))
            item_pid.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_name = QTableWidgetItem(p.name)
            item_mem = QTableWidgetItem(f"{p.memory_mb:.1f} MB")
            item_mem.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            self.table.setItem(row, 0, item_pid)
            self.table.setItem(row, 1, item_name)
            self.table.setItem(row, 2, item_mem)

        self.status_count_label.setText(f"Total: {len(processes)} processos")
        self._filter_table(self.search_input.text())

    def _filter_table(self, query: str) -> None:
        q = query.strip().lower()
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 1)
            pid_item = self.table.item(row, 0)
            name = name_item.text().lower() if name_item else ""
            pid = pid_item.text().lower() if pid_item else ""

            match = (q in name) or (q in pid) if q else True
            self.table.setRowHidden(row, not match)

    def _on_row_double_clicked(self) -> None:
        self._on_add_clicked()

    def _on_add_clicked(self) -> None:
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            name_item = self.table.item(selected_row, 1)
            if name_item:
                self.add_target_requested.emit(name_item.text())
