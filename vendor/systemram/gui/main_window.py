from datetime import datetime
from PySide6.QtWidgets import (
    QMainWindow, QTabWidget, QMessageBox, QLabel, QApplication
)
from PySide6.QtGui import QAction, QKeySequence, QFont, QCursor
from PySide6.QtCore import QThread, Signal, Qt

from vendor.systemram.core.privileges import is_admin, restart_as_admin
from vendor.systemram.core.memory_collector import (
    get_memory_summary, get_processes_memory_list, get_priority_breakdown
)
from vendor.systemram.core.memory_actions import (
    empty_working_sets,
    empty_system_working_set,
    empty_modified_page_list,
    empty_standby_list,
)
from vendor.systemram.gui.tab_use_counts import TabUseCounts
from vendor.systemram.gui.tab_processes import TabProcesses
from vendor.systemram.gui.tab_priority import TabPriority

class RefreshWorker(QThread):
    """Thread em segundo plano para coleta de estatísticas sem travar a interface."""
    data_ready = Signal(object, list, list)

    def run(self):
        try:
            summary = get_memory_summary()
            processes = get_processes_memory_list()
            priorities = get_priority_breakdown()
            self.data_ready.emit(summary, processes, priorities)
        except Exception:
            pass

class ActionWorker(QThread):
    """Thread em segundo plano para execução de esvaziamento sem congelar a GUI."""
    action_completed = Signal(bool, str)

    def __init__(self, action_type: str, parent=None):
        super().__init__(parent)
        self.action_type = action_type

    def run(self):
        ok = False
        msg = ""
        try:
            if self.action_type == "working_sets":
                ok, msg, _ = empty_working_sets()
            elif self.action_type == "system_cache":
                ok, msg = empty_system_working_set()
            elif self.action_type == "modified":
                ok, msg = empty_modified_page_list()
            elif self.action_type == "standby_all":
                ok, msg = empty_standby_list(priority0_only=False)
            elif self.action_type == "standby_p0":
                ok, msg = empty_standby_list(priority0_only=True)
        except Exception as e:
            ok = False
            msg = f"Erro inesperado: {str(e)}"

        self.action_completed.emit(ok, msg)

class MainWindow(QMainWindow):
    """Janela principal do PyRAMMap."""
    def __init__(self, embedded: bool = False, parent=None):
        super().__init__(parent)
        self.embedded = embedded
        if embedded:
            self.setWindowFlags(Qt.WindowType.Widget)
        self.setWindowTitle("PyRAMMap - SystemRAM")
        self.resize(950, 680)

        self.worker: RefreshWorker | None = None
        self.action_worker: ActionWorker | None = None

        self._init_ui()
        self._init_menu()
        self._init_status_bar()

        # Dispara a primeira atualização
        self.refresh_data()

    def _init_ui(self):
        self.tab_widget = QTabWidget(self)
        self.tab_use_counts = TabUseCounts(self)
        self.tab_processes = TabProcesses(self)
        self.tab_priority = TabPriority(self)

        self.tab_widget.addTab(self.tab_use_counts, "Use Counts")
        self.tab_widget.addTab(self.tab_processes, "Processes")
        self.tab_widget.addTab(self.tab_priority, "Priority Summary")

        self.setCentralWidget(self.tab_widget)

    def _init_menu(self):
        menu_bar = self.menuBar()

        # Menu File
        file_menu = menu_bar.addMenu("&File")

        self.refresh_action = QAction("&Refresh", self)
        self.refresh_action.setShortcut(QKeySequence("F5"))
        self.refresh_action.triggered.connect(self.refresh_data)
        file_menu.addAction(self.refresh_action)

        file_menu.addSeparator()

        if not is_admin():
            elevate_action = QAction("Reiniciar como Administrador (UAC)...", self)
            elevate_action.triggered.connect(
                lambda: restart_as_admin(["--open-systemram"] if self.embedded else [])
            )
            file_menu.addAction(elevate_action)
            file_menu.addSeparator()

        exit_action = QAction("E&xit", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Menu Empty
        self.empty_menu = menu_bar.addMenu("&Empty")

        act_ws = QAction("Empty &Working Sets", self)
        act_ws.triggered.connect(lambda: self._execute_empty("working_sets"))
        self.empty_menu.addAction(act_ws)

        act_sys = QAction("Empty &System Working Set", self)
        act_sys.triggered.connect(lambda: self._execute_empty("system_cache"))
        self.empty_menu.addAction(act_sys)

        act_mod = QAction("Empty &Modified Page List", self)
        act_mod.triggered.connect(lambda: self._execute_empty("modified"))
        self.empty_menu.addAction(act_mod)

        act_stb = QAction("Empty &Standby List", self)
        act_stb.triggered.connect(lambda: self._execute_empty("standby_all"))
        self.empty_menu.addAction(act_stb)

        act_stb0 = QAction("Empty &Priority 0 Standby List", self)
        act_stb0.triggered.connect(lambda: self._execute_empty("standby_p0"))
        self.empty_menu.addAction(act_stb0)

        # Menu Help
        help_menu = menu_bar.addMenu("&Help")
        about_action = QAction("&About PyRAMMap", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _init_status_bar(self):
        self.status_bar = self.statusBar()

        self.status_admin_lbl = QLabel()
        if is_admin():
            self.status_admin_lbl.setText(" [Administrador: Ativo] ")
            self.status_admin_lbl.setStyleSheet("color: #2e7d32; font-weight: bold;")
        else:
            self.status_admin_lbl.setText(" [Modo Somente Leitura - Não Elevado] ")
            self.status_admin_lbl.setStyleSheet("color: #d84315; font-weight: bold;")

        self.status_time_lbl = QLabel("Última atualização: --:--:-- ")
        self.status_time_lbl.setFont(QFont("Segoe UI", 9))

        self.status_bar.addPermanentWidget(self.status_admin_lbl)
        self.status_bar.addPermanentWidget(self.status_time_lbl)

    def refresh_data(self):
        """Dispara a coleta de dados de memória em background com proteção de concorrência."""
        if self.worker and self.worker.isRunning():
            return

        self.statusBar().showMessage("Atualizando dados de memória...")
        self.worker = RefreshWorker(self)
        self.worker.data_ready.connect(self._on_data_ready)
        self.worker.start()

    def _on_data_ready(self, summary, processes, priorities):
        self.tab_use_counts.update_data(summary)
        self.tab_processes.update_data(processes)
        self.tab_priority.update_data(priorities)

        now_str = datetime.now().strftime("%H:%M:%S")
        self.status_time_lbl.setText(f"Última atualização: {now_str} ")
        self.statusBar().showMessage(f"Pronto ({len(processes)} processos ativos analisados).", 4000)

    def _set_ui_busy(self, busy: bool):
        """Habilita ou desabilita ações de menu durante operações do kernel."""
        self.empty_menu.setEnabled(not busy)
        self.refresh_action.setEnabled(not busy)
        if busy:
            QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        else:
            QApplication.restoreOverrideCursor()

    def _execute_empty(self, action_type: str):
        """Executa a ação selecionada do menu Empty em background."""
        if not is_admin() and action_type != "working_sets":
            reply = QMessageBox.question(
                self,
                "Privilégios Administrativos Necessários",
                "As operações de esvaziamento das listas de memória física do Windows "
                "requerem permissões de Administrador (elevação UAC).\n\n"
                "Deseja reiniciar o PyRAMMap agora como Administrador?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )
            if reply == QMessageBox.StandardButton.Yes:
                restart_as_admin()
            return

        if self.action_worker and self.action_worker.isRunning():
            return

        self._set_ui_busy(True)
        self.statusBar().showMessage("Executando operação de esvaziamento no kernel...")

        self.action_worker = ActionWorker(action_type, self)
        self.action_worker.action_completed.connect(self._on_action_completed)
        self.action_worker.start()

    def _on_action_completed(self, ok: bool, msg: str):
        self._set_ui_busy(False)
        if ok:
            QMessageBox.information(self, "Ação Concluída", msg)
        else:
            QMessageBox.warning(self, "Aviso", msg)

        # Atualiza a interface para refletir a nova alocação de memória
        self.refresh_data()

    def _show_about(self):
        admin_txt = "Sim" if is_admin() else "Não (Execute como Admin para operações de limpeza)"
        info = (
            "<h2>PyRAMMap 1.0</h2>"
            "<p>Recriação em Python puro e PySide6 da ferramenta <b>Sysinternals RAMMap</b>.</p>"
            "<p>Permite visualizar o mapa de páginas físicas da memória RAM do Windows "
            "e executar ações de esvaziamento de Working Sets, Cache de Arquivos e Standby List.</p>"
            f"<p><b>Status de Administrador:</b> {admin_txt}</p>"
            "<p>Tecnologias: Python 3.13, ctypes (ntdll/kernel32/psapi), PySide6, psutil.</p>"
        )
        QMessageBox.about(self, "Sobre o PyRAMMap", info)
