from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QLineEdit
)
from PySide6.QtCore import Qt
from vendor.systemram.core.memory_collector import ProcessMemoryInfo

class NumericTableWidgetItem(QTableWidgetItem):
    """Item de tabela customizado para ordenação numérica correta por valor bruto."""
    def __init__(self, display_text: str, sort_value: float):
        super().__init__(display_text)
        self.sort_value = sort_value

    def __lt__(self, other):
        if isinstance(other, NumericTableWidgetItem):
            return self.sort_value < other.sort_value
        return super().__lt__(other)

class TabProcesses(QWidget):
    """Aba 'Processes' do RAMMap - Listagem e consumo de processos ativos."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.all_processes: list[ProcessMemoryInfo] = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # Barra de Pesquisa e Filtro
        filter_layout = QHBoxLayout()
        filter_label = QLabel("Pesquisar Processo:")
        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText("Filtrar por nome ou PID...")
        self.search_edit.textChanged.connect(self._apply_filter)

        self.count_label = QLabel("0 processos listados")

        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.search_edit)
        filter_layout.addWidget(self.count_label)
        layout.addLayout(filter_layout)

        # Tabela de Processos
        self.table = QTableWidget(self)
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Processo", "PID", "Working Set (Total)", "Private Bytes",
            "Commit (VMS)", "Paged Pool", "Non-Paged Pool"
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)

        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSortingEnabled(True)

        layout.addWidget(self.table)

    def update_data(self, processes: list[ProcessMemoryInfo]):
        self.all_processes = processes
        self._apply_filter()

    def _apply_filter(self):
        query = self.search_edit.text().strip().lower()
        filtered = [
            p for p in self.all_processes
            if not query or query in p.name.lower() or query in str(p.pid)
        ]

        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(filtered))

        for row, p in enumerate(filtered):
            name_item = QTableWidgetItem(p.name)
            pid_item = NumericTableWidgetItem(str(p.pid), p.pid)
            pid_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            ws_item = NumericTableWidgetItem(f"{p.working_set / (1024*1024):,.1f} MB", p.working_set)
            ws_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            priv_item = NumericTableWidgetItem(f"{p.private_bytes / (1024*1024):,.1f} MB", p.private_bytes)
            priv_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            commit_item = NumericTableWidgetItem(f"{p.commit_bytes / (1024*1024):,.1f} MB", p.commit_bytes)
            commit_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            paged_item = NumericTableWidgetItem(f"{p.paged_pool / 1024:,.0f} KB", p.paged_pool)
            paged_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            nonpaged_item = NumericTableWidgetItem(f"{p.nonpaged_pool / 1024:,.0f} KB", p.nonpaged_pool)
            nonpaged_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, pid_item)
            self.table.setItem(row, 2, ws_item)
            self.table.setItem(row, 3, priv_item)
            self.table.setItem(row, 4, commit_item)
            self.table.setItem(row, 5, paged_item)
            self.table.setItem(row, 6, nonpaged_item)

        self.table.setSortingEnabled(True)
        self.count_label.setText(f"{len(filtered)} processos listados")
