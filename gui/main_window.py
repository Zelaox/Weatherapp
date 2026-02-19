"""Main window for weather application."""

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QTabWidget,
    QToolBar, QAction, QStatusBar, QDialog, QDateEdit, QPushButton
)
from PyQt5.QtCore import QDate
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QIcon
from gui.city_panel import CityPanel
from gui.weather_panel import WeatherPanel
from gui.history_tab import HistoryTab
from gui.stats_tab import StatsTab
from gui.averages_tab import AveragesTab
from gui.warnings_tab import WarningsTab
from gui.api_status_tab import APIStatusTab
from gui.logs_tab import LogsTab
from gui.stations_tab import StationsTab
from gui.help_dialog import HelpDialog
from analytics.graph_generator import GraphGenerator
from analytics.graph_modes import MODES, BaseMode
from zoneinfo import ZoneInfo
from datetime import datetime, date


class GraphGenerationWorker(QThread):
    """Worker thread for graph generation to avoid freezing UI."""
    
    finished = pyqtSignal(bool, str)  # success, message
    
    def __init__(self, db_manager, mode_class=None, export_timestamp=None, selected_date=None, output_dir="output"):
        """
        Initialize worker.
        
        Args:
            db_manager: Database manager instance
            mode_class: Optional mode class for grouping
            export_timestamp: Export timestamp (must be provided, not generated here)
            selected_date: Optional date for modes that require it (e.g. DailyMode)
            output_dir: Output directory for graphs
        """
        super().__init__()
        self.db_manager = db_manager
        self.mode_class = mode_class
        self.export_timestamp = export_timestamp
        self.selected_date = selected_date
        self.output_dir = output_dir
    
    def run(self):
        """Run graph generation in background thread."""
        try:
            generator = GraphGenerator(self.db_manager, self.output_dir)
            
            # Create mode instance if mode_class provided
            mode_instance = None
            if self.mode_class is not None:
                mode_instance = self.mode_class()
            
            # Generate all city graphs (hours=None = ALL history)
            # Returns (filepaths, export_timestamp) - use same timestamp for national graph
            city_graphs, export_timestamp = generator.generate_all_city_graphs(
                hours=None,
                export_timestamp=self.export_timestamp,
                mode=mode_instance,
                selected_date=self.selected_date
            )
            
            # Generate national graph with same timestamp (hours=None = ALL history)
            national_graph = generator.generate_national_graph(
                hours=None,
                export_timestamp=export_timestamp,
                mode=mode_instance,
                selected_date=self.selected_date
            )
            
            # Count generated graphs
            num_graphs = len(city_graphs)
            if national_graph:
                num_graphs += 1
            
            if num_graphs > 0:
                message = f"Genererade {num_graphs} grafer"
                self.finished.emit(True, message)
            else:
                message = "Inga grafer genererade (ingen data tillgänglig)"
                self.finished.emit(False, message)
        except Exception as e:
            error_msg = f"Fel vid grafgenerering: {e}"
            self.finished.emit(False, error_msg)


class MainWindow(QMainWindow):
    """Main application window."""
    
    def __init__(self, controller):
        """
        Initialize main window.
        
        Args:
            controller: Weather controller instance
        """
        super().__init__()
        self.controller = controller
        self.setWindowTitle("Väderapplikation")
        self.setGeometry(100, 100, 1200, 800)
        
        # Graph generation worker
        self.graph_worker = None
        
        # Debounce timer for multiple simultaneous updates
        # When multiple cities update at once, wait 100ms then refresh once
        self.refresh_debounce_timer = QTimer()
        self.refresh_debounce_timer.setSingleShot(True)
        self.refresh_debounce_timer.timeout.connect(self.refresh_all)
        self.pending_refresh = False
        
        self._init_ui()
        
        # Connect data_updated signal to refresh (event-driven)
        self.controller.data_updated.connect(self._on_data_updated)
        self.controller.logger.info("Event-driven UI refresh aktiverad (uppdateras endast vid ny data)")
    
    def _init_ui(self):
        """Initialize UI components."""
        self.controller.logger.info("Initialiserar GUI-komponenter...")
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(5)
        main_layout.setContentsMargins(5, 5, 5, 5)
        
        # Left panel (cities)
        self.city_panel = CityPanel(self.controller)
        # Connect city selection to weather panel
        self.city_panel.city_selected.connect(self._on_city_selected)
        main_layout.addWidget(self.city_panel, 1)
        
        # Right side (weather + tabs)
        right_layout = QVBoxLayout()
        right_layout.setSpacing(5)
        
        # Weather panel
        self.weather_panel = WeatherPanel(self.controller)
        right_layout.addWidget(self.weather_panel, 1)
        
        # Tabs
        self.tabs = QTabWidget()
        self.history_tab = HistoryTab(self.controller)
        self.stats_tab = StatsTab(self.controller)
        self.averages_tab = AveragesTab(self.controller)
        self.warnings_tab = WarningsTab(self.controller)
        self.api_status_tab = APIStatusTab(self.controller)
        self.logs_tab = LogsTab(self.controller)
        self.stations_tab = StationsTab(self.controller)
        
        self.tabs.addTab(self.history_tab, "Historik")
        self.tabs.addTab(self.stats_tab, "Statistik")
        self.tabs.addTab(self.averages_tab, "Översikt")
        self.tabs.addTab(self.warnings_tab, "Varningar")
        self.tabs.addTab(self.stations_tab, "Stationer")
        self.tabs.addTab(self.api_status_tab, "API Status")
        self.tabs.addTab(self.logs_tab, "Loggar")
        
        right_layout.addWidget(self.tabs, 2)
        
        main_layout.addLayout(right_layout, 3)
        
        # Toolbar
        self._create_toolbar()
        
        # MenuBar
        self._create_menubar()
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Redo")
        self.controller.logger.info("GUI-komponenter initialiserade")
    
    def _create_toolbar(self):
        """Create toolbar with actions."""
        toolbar = QToolBar("Huvudverktygsfält")
        self.addToolBar(toolbar)
        
        # Update button
        update_action = QAction("Hämta nu", self)
        update_action.setShortcut("F5")
        update_action.triggered.connect(self._manual_update)
        toolbar.addAction(update_action)
        
        toolbar.addSeparator()
        
        # Auto-update toggle (off by default)
        self.auto_update_action = QAction("Auto-uppdatering", self)
        self.auto_update_action.setCheckable(True)
        self.auto_update_action.setChecked(False)  # Off by default
        self.auto_update_action.triggered.connect(self._toggle_auto_update)
        toolbar.addAction(self.auto_update_action)
    
    def _create_menubar(self):
        """Create menubar with Generate menu built dynamically from MODES."""
        menubar = self.menuBar()
        
        # Generate menu
        generate_menu = menubar.addMenu("Generera")
        
        # Dynamisk byggnad från MODES dictionary
        for mode_name, mode_class in MODES.items():
            action = QAction(mode_name, self)
            action.triggered.connect(lambda checked, m=mode_class: self.run_mode(m))
            generate_menu.addAction(action)
        
        # Help menu
        help_menu = menubar.addMenu("Hjälp")
        help_action = QAction("Funktioner och Hjälp", self)
        help_action.triggered.connect(self._show_help_dialog)
        help_menu.addAction(help_action)
    
    def _toggle_auto_update(self, checked: bool):
        """Toggle auto-update on/off."""
        if hasattr(self.controller, 'start_auto_update'):
            if checked:
                self.controller.start_auto_update()
            else:
                self.controller.stop_auto_update()
    
    def _manual_update(self):
        """Manual update trigger."""
        if hasattr(self.controller, 'manual_update'):
            self.controller.manual_update()
        else:
            self.controller.update_all_cities()
        self.refresh_all()
    
    def _show_help_dialog(self):
        """Show help dialog with feature dictionary."""
        dialog = HelpDialog(self)
        dialog.exec_()
    
    def _on_city_selected(self, city_id: int):
        """Handle city selection."""
        self.weather_panel.set_city(city_id)
    
    def update_status(self, message: str):
        """Update status bar message."""
        self.status_bar.showMessage(message)
    
    def run_mode(self, mode_class):
        """
        Run graph generation with specific mode.
        
        Args:
            mode_class: Mode class (e.g. DailyMode, WeeklyMode)
        """
        # Create mode instance to check if date selection is needed
        mode_instance = mode_class()
        mode_name = mode_instance.get_name()
        
        # If mode needs date selection, show date picker
        selected_date = None
        if mode_instance.needs_date_selection():
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Välj datum för {mode_name}")
            dialog.setModal(True)
            
            layout = QVBoxLayout(dialog)
            
            date_edit = QDateEdit(dialog)
            date_edit.setCalendarPopup(True)
            date_edit.setDate(QDate.currentDate())
            layout.addWidget(date_edit)
            
            button_layout = QHBoxLayout()
            ok_button = QPushButton("OK", dialog)
            cancel_button = QPushButton("Avbryt", dialog)
            button_layout.addWidget(ok_button)
            button_layout.addWidget(cancel_button)
            layout.addLayout(button_layout)
            
            ok_button.clicked.connect(dialog.accept)
            cancel_button.clicked.connect(dialog.reject)
            
            if dialog.exec_() == QDialog.Accepted:
                selected_date = date_edit.date().toPyDate()
            else:
                # User cancelled - return early, do NOT start worker
                return
        
        # Generate global export timestamp FÖRE worker startar (EN gång)
        CET = ZoneInfo("Europe/Stockholm")
        export_ts = datetime.now(CET)
        export_timestamp = export_ts.strftime("%Y%m%d_%H%M%S")
        
        self.status_bar.showMessage(f"Genererar grafer ({mode_name})...")
        
        # Create and start worker thread
        self.graph_worker = GraphGenerationWorker(
            self.controller.db,
            mode_class=mode_class,
            export_timestamp=export_timestamp,
            selected_date=selected_date,
            output_dir="output"
        )
        self.graph_worker.finished.connect(self._on_graph_generation_finished)
        self.graph_worker.start()
    
    def _on_graph_generation_finished(self, success: bool, message: str):
        """Handle graph generation completion."""
        # Update status bar
        if success:
            self.status_bar.showMessage(message, 5000)
            self.controller.logger.info(message)
        else:
            self.status_bar.showMessage(message, 5000)
            self.controller.logger.warning(message)
        
        # Clean up worker
        if self.graph_worker:
            self.graph_worker.quit()
            self.graph_worker.wait()
            self.graph_worker = None
    
    def _on_data_updated(self, city_id: int, data_id: int):
        """
        Handle data_updated signal with debouncing.
        
        Args:
            city_id: City ID that was updated
            data_id: Data ID that was inserted
        """
        # Mark that we have a pending refresh
        self.pending_refresh = True
        
        # If timer is not running, start it (100ms debounce)
        if not self.refresh_debounce_timer.isActive():
            self.refresh_debounce_timer.start(100)
            self.controller.logger.debug(f"Data uppdaterad för stad {city_id} (data_id: {data_id}), schemalägger UI-refresh")
    
    def refresh_all(self):
        """Refresh all UI components."""
        # Reset pending flag
        self.pending_refresh = False
        
        self.city_panel.refresh()
        self.weather_panel.refresh()
        self.history_tab.refresh()
        self.stats_tab.refresh()
        self.averages_tab.refresh()
        self.warnings_tab.refresh()
        self.api_status_tab.refresh()
        self.logs_tab.refresh()
