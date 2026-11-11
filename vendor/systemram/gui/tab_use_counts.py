from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QLabel, QFrame
)
from PySide6.QtGui import QPainter, QColor, QFont
from PySide6.QtCore import Qt
from vendor.systemram.core.memory_collector import MemorySummary

class MemoryDistributionBar(QFrame):
    """Barra gráfica colorida de distribuição da memória física (estilo RAMMap)."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(34)
        self.setFrameStyle(QFrame.Shape.Box | QFrame.Shadow.Sunken)
        self.in_use_pct = 0.0
        self.standby_pct = 0.0
        self.modified_pct = 0.0
        self.free_pct = 0.0

    def set_percentages(self, in_use: float, standby: float, modified: float, free: float):
        self.in_use_pct = max(0.0, in_use)
        self.standby_pct = max(0.0, standby)
        self.modified_pct = max(0.0, modified)
        self.free_pct = max(0.0, free)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        rect = self.contentsRect()
        total_w = rect.width()

        w_in_use = int((self.in_use_pct / 100.0) * total_w)
        w_standby = int((self.standby_pct / 100.0) * total_w)
        w_modified = int((self.modified_pct / 100.0) * total_w)
        w_free = total_w - (w_in_use + w_standby + w_modified)

        x = rect.x()
        y = rect.y()
        h = rect.height()

        # In-use (Azul suave)
        if w_in_use > 0:
            painter.fillRect(x, y, w_in_use, h, QColor("#2b78e4"))
            x += w_in_use

        # Standby (Verde suave)
        if w_standby > 0:
            painter.fillRect(x, y, w_standby, h, QColor("#34a853"))
            x += w_standby

        # Modified (Laranja suave)
        if w_modified > 0:
            painter.fillRect(x, y, w_modified, h, QColor("#fbbc05"))
            x += w_modified

        # Free / Zeroed (Cinza claro)
        if w_free > 0:
            painter.fillRect(x, y, w_free, h, QColor("#e0e0e0"))

class TabUseCounts(QWidget):
    """Aba 'Use Counts' do RAMMap - Categorias de uso de memória física."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # Legenda e Barra de Distribuição
        bar_header = QLabel("Distribuição da Memória Física:")
        bar_header.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        layout.addWidget(bar_header)

        self.dist_bar = MemoryDistributionBar(self)
        layout.addWidget(self.dist_bar)

        legend_layout = QHBoxLayout()
        legend_layout.addWidget(self._create_legend_item("#2b78e4", "Em Uso (Ativa)"))
        legend_layout.addWidget(self._create_legend_item("#34a853", "Standby (Cache)"))
        legend_layout.addWidget(self._create_legend_item("#fbbc05", "Modificada"))
        legend_layout.addWidget(self._create_legend_item("#e0e0e0", "Livre / Zerada"))
        legend_layout.addStretch()
        layout.addLayout(legend_layout)

        # Tabela Detalhada
        self.table = QTableWidget(self)
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels([
            "Tipo de Uso", "Tamanho (MB)", "Tamanho (GB)", "% do Total"
        ])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        layout.addWidget(self.table)

    def _create_legend_item(self, hex_color: str, text: str) -> QWidget:
        container = QWidget(self)
        h = QHBoxLayout(container)
        h.setContentsMargins(0, 0, 10, 0)

        badge = QLabel()
        badge.setFixedSize(14, 14)
        badge.setStyleSheet(f"background-color: {hex_color}; border: 1px solid #888; border-radius: 2px;")
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 9))

        h.addWidget(badge)
        h.addWidget(lbl)
        return container

    def update_data(self, summary: MemorySummary):
        total_b = summary.total_bytes if summary.total_bytes > 0 else 1

        rows_data = [
            ("Memória em Uso (Processos e Kernel)", summary.in_use_bytes),
            ("Standby List (Cache de Memória)", summary.standby_bytes),
            ("Modified Page List (Modificada)", summary.modified_bytes),
            ("Free List (Páginas Livres)", summary.free_bytes),
            ("Zero Page List (Páginas Zeradas)", summary.zeroed_bytes),
            ("System File Cache", summary.system_cache_bytes),
            ("Paged Pool (Pool Paginável)", summary.paged_pool_bytes),
            ("Non-Paged Pool (Pool Não-Paginável)", summary.nonpaged_pool_bytes),
            ("TOTAL DE MEMÓRIA FÍSICA", summary.total_bytes),
        ]

        self.table.setRowCount(len(rows_data))
        for row, (label, size_bytes) in enumerate(rows_data):
            size_mb = size_bytes / (1024 * 1024)
            size_gb = size_bytes / (1024 * 1024 * 1024)
            pct = (size_bytes / total_b) * 100

            item_label = QTableWidgetItem(label)
            if row == len(rows_data) - 1:
                item_label.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))

            item_mb = QTableWidgetItem(f"{size_mb:,.1f} MB")
            item_mb.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            item_gb = QTableWidgetItem(f"{size_gb:,.2f} GB")
            item_gb.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            item_pct = QTableWidgetItem(f"{pct:.1f}%")
            item_pct.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

            self.table.setItem(row, 0, item_label)
            self.table.setItem(row, 1, item_mb)
            self.table.setItem(row, 2, item_gb)
            self.table.setItem(row, 3, item_pct)

        # Atualiza a barra de distribuição
        in_use_pct = (summary.in_use_bytes / total_b) * 100
        standby_pct = (summary.standby_bytes / total_b) * 100
        modified_pct = (summary.modified_bytes / total_b) * 100
        free_pct = ((summary.free_bytes + summary.zeroed_bytes) / total_b) * 100
        self.dist_bar.set_percentages(in_use_pct, standby_pct, modified_pct, free_pct)
