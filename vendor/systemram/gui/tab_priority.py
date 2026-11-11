from typing import Any
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel
)
from PySide6.QtGui import QFont
from PySide6.QtCore import Qt

PRIORITY_DESCRIPTIONS = {
    0: "Prioridade Mais Baixa (Primeira a ser reaproveitada/descartada sob pressão de memória)",
    1: "Prioridade Baixa (Cache secundário de processos em background)",
    2: "Prioridade Baixa-Média (Páginas de processos em segundo plano)",
    3: "Prioridade Média-Baixa (Cache de arquivos e páginas pouco acessadas)",
    4: "Prioridade Média (Páginas de processos em transição)",
    5: "Prioridade Média-Alta (Páginas recentemente acessadas por processos em primeiro plano)",
    6: "Prioridade Alta (Páginas frequentemente reutilizadas)",
    7: "Prioridade Mais Alta (Cache de alto impacto e componentes críticos do sistema)",
}

class TabPriority(QWidget):
    """Aba 'Priority Summary' do RAMMap - Detalhamento das listas Standby 0 a 7."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        info_label = QLabel("Distribuição das Páginas em Standby (Prioridades 0 a 7):")
        info_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        layout.addWidget(info_label)

        self.table = QTableWidget(self)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "Prioridade", "Descrição", "Páginas", "Tamanho (MB)", "% da Standby List"
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        layout.addWidget(self.table)

    def update_data(self, priorities: list[dict[str, Any]]):
        self.table.setRowCount(len(priorities))

        for row, item in enumerate(priorities):
            p = item["priority"]
            desc = PRIORITY_DESCRIPTIONS.get(p, f"Nível de Prioridade {p}")
            pages = item["pages"]
            mb = item["mb"]
            pct = item["percent"]

            item_p = QTableWidgetItem(f"Prioridade {p}")
            item_p.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if p == 0:
                item_p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))

            item_desc = QTableWidgetItem(desc)
            item_pages = QTableWidgetItem(f"{pages:,}")
            item_pages.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            item_mb = QTableWidgetItem(f"{mb:,.1f} MB")
            item_mb.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            item_pct = QTableWidgetItem(f"{pct:.1f}%")
            item_pct.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            self.table.setItem(row, 0, item_p)
            self.table.setItem(row, 1, item_desc)
            self.table.setItem(row, 2, item_pages)
            self.table.setItem(row, 3, item_mb)
            self.table.setItem(row, 4, item_pct)
