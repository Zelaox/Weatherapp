"""Main window for weather application."""

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QTabWidget,
    QToolBar, QAction, QStatusBar, QDialog, QDateEdit, QPushButton,
    QApplication
)
from PyQt5.QtCore import QDate
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QEvent
from PyQt5.QtGui import QIcon
from gui.city_panel import CityPanel
from gui.weather_panel import WeatherPanel
from gui.stats_tab import StatsTab
from gui.averages_tab import AveragesTab
from gui.warnings_tab import WarningsTab
from gui.api_status_tab import APIStatusTab
from gui.logs_tab import LogsTab
from gui.stations_tab import StationsTab
from gui.help_dialog import HelpDialog
from gui.settings_dialog import SettingsDialog, apply_theme
# Lazy imports to avoid hanging - graph_generator and graph_modes import pandas
# which can hang during module import when combined with PyQt5
from zoneinfo import ZoneInfo
from datetime import datetime, date
import logging


class GraphGenerationWorker(QThread):
    """Worker thread for graph generation to avoid freezing UI."""
    
    finished = pyqtSignal(bool, str)  # success, message
    
    def __init__(self, db_manager, mode_class=None, export_timestamp=None, selected_date=None, output_dir="output", category=None):
        """
        Initialize worker.
        
        Args:
            db_manager: Database manager instance
            mode_class: Optional mode class for grouping
            export_timestamp: Export timestamp (must be provided, not generated here)
            selected_date: Optional date for modes that require it (e.g. DailyMode)
            output_dir: Output directory for graphs
            category: Optional category to filter parameters ('weather', 'air_quality', 'solar', 'storm')
        """
        super().__init__()
        self.db_manager = db_manager
        self.mode_class = mode_class
        self.export_timestamp = export_timestamp
        self.selected_date = selected_date
        self.output_dir = output_dir
        self.category = category
    
    def run(self):
        """Run graph generation in background thread."""
        try:
            # Lazy import to avoid hanging during module import
            from analytics.graph_generator import GraphGenerator
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
                selected_date=self.selected_date,
                category=self.category
            )
            
            # Generate national graph with same timestamp (hours=None = ALL history)
            national_graph = generator.generate_national_graph(
                hours=None,
                export_timestamp=export_timestamp,
                mode=mode_instance,
                selected_date=self.selected_date,
                category=self.category
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
        import logging
        logger = logging.getLogger("WeatherApp.gui.main_window")
        logger.debug("Initializing MainWindow")
        
        try:
            super().__init__()
            self.controller = controller
            self.setWindowTitle("Väderapplikation")
            self.setGeometry(100, 100, 1200, 800)
            logger.debug("MainWindow base class initialized, window geometry set")
            
            # Graph generation worker
            self.graph_worker = None
            logger.debug("Graph worker initialized as None")
            
            # Debounce timer for multiple simultaneous updates
            # When multiple cities update at once, wait 100ms then refresh once
            self.refresh_debounce_timer = QTimer()
            self.refresh_debounce_timer.setSingleShot(True)
            self.refresh_debounce_timer.timeout.connect(self.refresh_all)
            self.pending_refresh = False
            logger.debug("Refresh debounce timer configured")
            
            # Periodic refresh timer to ensure UI updates even if signals are missed
            # Refresh every 30 seconds to check for new data
            self.periodic_refresh_timer = QTimer()
            self.periodic_refresh_timer.timeout.connect(self.refresh_all)
            self.periodic_refresh_timer.start(30000)  # 30 seconds
            logger.debug("Periodic refresh timer started (30s interval)")
            
            logger.debug("Initializing UI components")
            self._init_ui()

            # Restore saved theme (dark / light) before the window is shown
            logger.debug("Restoring theme settings")
            dark = bool(self.controller.config.get_setting("dark_mode", False))
            apply_theme(QApplication.instance(), dark)
            logger.debug(f"Theme applied: {'dark' if dark else 'light'}")

            # Connect data_updated signal to refresh (event-driven)
            logger.debug("Connecting data_updated signal")
            self.controller.data_updated.connect(self._on_data_updated)
            self.controller.logger.info("Event-driven UI refresh enabled (updates only when new data is saved)")
            logger.info("MainWindow initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize MainWindow: {e}", exc_info=True)
            raise
    
    def _init_ui(self):
        """Initialize UI components."""
        import logging
        import time
        logger = logging.getLogger("WeatherApp.gui.main_window")
        
        start_time = time.time()
        self.controller.logger.info("Initializing GUI components...")
        logger.info(f"[{time.time():.3f}] Starting UI initialization")
        
        try:
            # Central widget
            logger.info(f"[{time.time():.3f}] Creating central widget")
            central_widget = QWidget()
            self.setCentralWidget(central_widget)
            logger.info(f"[{time.time():.3f}] Central widget created")
            
            # Main layout
            logger.info(f"[{time.time():.3f}] Setting up main layout")
            main_layout = QHBoxLayout(central_widget)
            main_layout.setSpacing(5)
            main_layout.setContentsMargins(5, 5, 5, 5)
            logger.info(f"[{time.time():.3f}] Main layout configured")
            
            # Left panel (cities)
            logger.info(f"[{time.time():.3f}] Creating city panel")
            city_panel_start = time.time()
            self.city_panel = CityPanel(self.controller)
            # Connect city selection to weather panel
            self.city_panel.city_selected.connect(self._on_city_selected)
            main_layout.addWidget(self.city_panel, 1)
            logger.info(f"[{time.time():.3f}] City panel created and connected (took {time.time() - city_panel_start:.3f}s)")
            
            # Right side (weather + tabs)
            logger.info(f"[{time.time():.3f}] Setting up right side layout")
            right_layout = QVBoxLayout()
            right_layout.setSpacing(5)
            
            # Weather panel
            logger.info(f"[{time.time():.3f}] Creating weather panel")
            weather_panel_start = time.time()
            self.weather_panel = WeatherPanel(self.controller)
            right_layout.addWidget(self.weather_panel, 1)
            logger.info(f"[{time.time():.3f}] Weather panel created (took {time.time() - weather_panel_start:.3f}s)")
            
            # Tabs
            logger.debug("Creating tab widget and tabs")
            self.tabs = QTabWidget()
            
            logger.info(f"[{time.time():.3f}] Creating standard tabs (Stats, Averages, Warnings, API Status, Logs, Stations)")
            logger.info(f"[{time.time():.3f}] Creating StatsTab...")
            stats_tab_start = time.time()
            self.stats_tab = StatsTab(self.controller)
            logger.info(f"[{time.time():.3f}] StatsTab created (took {time.time() - stats_tab_start:.3f}s)")
            logger.info(f"[{time.time():.3f}] Creating AveragesTab...")
            averages_tab_start = time.time()
            self.averages_tab = AveragesTab(self.controller)
            logger.info(f"[{time.time():.3f}] AveragesTab created (took {time.time() - averages_tab_start:.3f}s)")
            logger.info(f"[{time.time():.3f}] Creating WarningsTab...")
            warnings_tab_start = time.time()
            self.warnings_tab = WarningsTab(self.controller)
            logger.info(f"[{time.time():.3f}] WarningsTab created (took {time.time() - warnings_tab_start:.3f}s)")
            logger.info(f"[{time.time():.3f}] Creating APIStatusTab...")
            api_status_tab_start = time.time()
            self.api_status_tab = APIStatusTab(self.controller)
            logger.info(f"[{time.time():.3f}] APIStatusTab created (took {time.time() - api_status_tab_start:.3f}s)")
            logger.info(f"[{time.time():.3f}] Creating LogsTab...")
            logs_tab_start = time.time()
            self.logs_tab = LogsTab(self.controller)
            logger.info(f"[{time.time():.3f}] LogsTab created (took {time.time() - logs_tab_start:.3f}s)")
            logger.info(f"[{time.time():.3f}] Creating StationsTab...")
            stations_tab_start = time.time()
            self.stations_tab = StationsTab(self.controller)
            logger.info(f"[{time.time():.3f}] StationsTab created (took {time.time() - stations_tab_start:.3f}s)")
            logger.info(f"[{time.time():.3f}] Standard tabs created")
            
            # Panels - create placeholders initially, defer actual creation until after window is shown
            logger.info(f"[{time.time():.3f}] Creating panel placeholders (deferring actual creation)")
            from PyQt5.QtWidgets import QLabel
            from PyQt5.QtCore import Qt
            
            # Create placeholder widgets
            self.solar_panel = QLabel("Laddar solpanel...")
            self.solar_panel.setAlignment(Qt.AlignCenter)
            self.storm_panel = QLabel("Laddar åskpanel...")
            self.storm_panel.setAlignment(Qt.AlignCenter)
            self.lightning_panel = QLabel("Laddar blixtpanel...")
            self.lightning_panel.setAlignment(Qt.AlignCenter)
            
            # Track which panels have been created
            self._panels_created = {
                'solar': False,
                'storm': False,
                'lightning': False
            }
            
            logger.debug("Adding tabs to tab widget")
            self.tabs.addTab(self.solar_panel, "Sol")
            self.tabs.addTab(self.storm_panel, "Åska")
            self.tabs.addTab(self.lightning_panel, "Blixtar")
            
            self.tabs.addTab(self.stats_tab, "Statistik")
            self.tabs.addTab(self.averages_tab, "Översikt")
            self.tabs.addTab(self.warnings_tab, "Varningar")
            self.tabs.addTab(self.stations_tab, "Stationer")
            self.tabs.addTab(self.api_status_tab, "API Status")
            self.tabs.addTab(self.logs_tab, "Loggar")
            logger.debug(f"All tabs added (total: {self.tabs.count()})")
            
            right_layout.addWidget(self.tabs, 2)
            
            main_layout.addLayout(right_layout, 3)
            
            # Toolbar
            logger.debug("Creating toolbar")
            self._create_toolbar()
            logger.debug("Toolbar created")
            
            # MenuBar
            logger.debug("Creating menu bar")
            self._create_menubar()
            logger.debug("Menu bar created")
            
            # Status bar
            logger.debug("Creating status bar")
            self.status_bar = QStatusBar()
            self.setStatusBar(self.status_bar)
            self.status_bar.showMessage("Redo")
            logger.debug("Status bar created")
            
            total_time = time.time() - start_time
            logger.info(f"[{time.time():.3f}] GUI components initialized successfully (total time: {total_time:.3f}s)")
            self.controller.logger.info("GUI-komponenter initialiserade")
        except Exception as e:
            logger.error(f"Failed to initialize UI: {e}", exc_info=True)
            raise
    
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
        """Create menubar with Generate menu built dynamically from MODES and categories."""
        import logging
        logger = logging.getLogger("WeatherApp.gui.main_window")
        logger.debug("Starting menubar creation")
        
        # Lazy import to avoid hanging during module import
        logger.debug("Importing MODES...")
        try:
            from analytics.graph_modes import MODES
            logger.debug("MODES imported successfully")
        except Exception as e:
            logger.error(f"Failed to import MODES: {e}", exc_info=True)
            self.controller.logger.error(f"Failed to import MODES for menubar: {e}", exc_info=True)
            # Create empty MODES dict as fallback
            MODES = {}
            logger.warning("Using empty MODES dict as fallback")
        
        logger.debug("Getting menu bar")
        menubar = self.menuBar()
        
        # Generate menu
        generate_menu = menubar.addMenu("Generera")
        
        # Get categories from parameter_registry (dynamic, no hardcoding)
        try:
            categories = set()
            param_registry = self.controller.db.get_parameter_registry()
            for param in param_registry:
                cat = param.get('category')
                if cat:
                    categories.add(cat)
            
            # Category display names mapping (Swedish)
            category_names = {
                'weather': 'Väder',
                'air_quality': 'Luftkvalitet',
                'solar': 'Sol',
                'storm': 'Åska',
                'lightning': 'Blixtar'
            }
            
            # Add category submenus (inklusive sol, åska och blixtar)
            for category in sorted(categories):
                category_display = category_names.get(category, category.capitalize())
                category_menu = generate_menu.addMenu(category_display)
                
                # Add mode actions for this category
                for mode_name, mode_class in MODES.items():
                    action = QAction(mode_name, self)
                    action.triggered.connect(
                        lambda checked, m=mode_class, c=category: self.run_mode_category(m, c)
                    )
                    category_menu.addAction(action)
            
            # Add separator
            generate_menu.addSeparator()
        except Exception as e:
            self.controller.logger.warning(f"Kunde inte skapa kategori-menyer: {e}")
        
        # Original mode actions (all parameters, no category filter)
        for mode_name, mode_class in MODES.items():
            action = QAction(mode_name, self)
            action.triggered.connect(lambda checked, m=mode_class: self.run_mode(m))
            generate_menu.addAction(action)
        
        # Help menu
        help_menu = menubar.addMenu("Hjälp")
        help_action = QAction("Funktioner och Hjälp", self)
        help_action.triggered.connect(self._show_help_dialog)
        help_menu.addAction(help_action)

        help_menu.addSeparator()

        settings_action = QAction("Inställningar", self)
        settings_action.triggered.connect(self._show_settings_dialog)
        help_menu.addAction(settings_action)
    
    def _toggle_auto_update(self, checked: bool):
        """Toggle auto-update on/off."""
        if hasattr(self.controller, 'start_auto_update'):
            if checked:
                self.controller.start_auto_update()
            else:
                self.controller.stop_auto_update()
    
    def _manual_update(self):
        """Manual update trigger."""
        self.status_bar.showMessage("Hämtar data från API:erna...", 5000)
        self.controller.logger.info("=" * 60)
        self.controller.logger.info("MANUELL UPPDATERING STARTAD - Hämtar från API:erna")
        self.controller.logger.info("=" * 60)
        if hasattr(self.controller, 'manual_update'):
            self.controller.manual_update()
        else:
            self.controller.update_all_cities()
        self.refresh_all()
    
    def _show_help_dialog(self):
        """Show help dialog with feature dictionary."""
        dialog = HelpDialog(self)
        dialog.exec_()

    def _show_settings_dialog(self):
        """
        Open settings dialog and apply sequenced post-close side-effects.

        Sequence (matches plan):
          1. apply_theme()                — always, immediate
          2. pause_auto_update()          — if interval changed and auto-update is active
          3. stations_tab._load_map()     — if map/debug settings changed
          4. restart_auto_update(minutes) — if interval changed and was previously active
        """
        cfg = self.controller.config

        # Snapshot values before the dialog opens so we can detect changes
        old_interval    = cfg.get_setting("auto_update_interval_minutes")
        old_layer       = cfg.get_setting("map_default_layer")
        old_opacity     = cfg.get_setting("heatmap_opacity")
        old_debug       = cfg.get_setting("debug_mode")

        dialog = SettingsDialog(cfg, parent=self)
        result = dialog.exec_()

        if result != QDialog.Accepted:
            return

        # ── Step 1: Apply theme (always) ─────────────────────────────────
        dark = bool(cfg.get_setting("dark_mode", False))
        apply_theme(QApplication.instance(), dark)

        # ── Step 2: Pause auto-update if interval changed and timer is active
        new_interval = cfg.get_setting("auto_update_interval_minutes")
        interval_changed = (new_interval != old_interval)
        auto_update_is_active = self.auto_update_action.isChecked()

        if interval_changed and auto_update_is_active:
            if hasattr(self.controller, "pause_auto_update"):
                self.controller.pause_auto_update()

        # ── Step 3: Reload map if any map or debug setting changed ────────
        new_layer   = cfg.get_setting("map_default_layer")
        new_opacity = cfg.get_setting("heatmap_opacity")
        new_debug   = cfg.get_setting("debug_mode")

        map_settings_changed = (
            new_layer   != old_layer   or
            new_opacity != old_opacity or
            new_debug   != old_debug
        )
        if map_settings_changed:
            self.stations_tab._load_map()

        # ── Step 4: Restart auto-update with new interval ─────────────────
        if interval_changed and auto_update_is_active:
            if hasattr(self.controller, "restart_auto_update"):
                self.controller.restart_auto_update(int(new_interval))

    def _on_city_selected(self, city_id: int):
        """Handle city selection."""
        self.weather_panel.set_city(city_id)
        # Update panels if they have been created (not just placeholders)
        if hasattr(self, 'solar_panel') and self._panels_created.get('solar', False):
            if hasattr(self.solar_panel, 'set_city'):
                self.solar_panel.set_city(city_id)
        if hasattr(self, 'storm_panel') and self._panels_created.get('storm', False):
            if hasattr(self.storm_panel, 'set_city'):
                self.storm_panel.set_city(city_id)
        if hasattr(self, 'lightning_panel') and self._panels_created.get('lightning', False):
            if hasattr(self.lightning_panel, 'set_city'):
                self.lightning_panel.set_city(city_id)
    
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
            output_dir="output",
            category=None
        )
        self.graph_worker.finished.connect(self._on_graph_generation_finished)
        self.graph_worker.start()
    
    def run_mode_category(self, mode_class, category: str):
        """
        Run graph generation with specific mode and category.
        
        Args:
            mode_class: Mode class (e.g. DailyMode, WeeklyMode)
            category: Category name ('weather', 'air_quality', 'solar', 'storm')
        """
        # Create mode instance to check if date selection is needed
        mode_instance = mode_class()
        mode_name = mode_instance.get_name()
        
        # If mode needs date selection, show date picker
        selected_date = None
        if mode_instance.needs_date_selection():
            dialog = QDialog(self)
            dialog.setWindowTitle(f"Välj datum för {mode_name} - {category}")
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
                return
        
        # Generate global export timestamp
        CET = ZoneInfo("Europe/Stockholm")
        export_ts = datetime.now(CET)
        export_timestamp = export_ts.strftime("%Y%m%d_%H%M%S")
        
        self.status_bar.showMessage(f"Genererar {category}-grafer ({mode_name})...")
        
        # Create and start worker thread with category
        self.graph_worker = GraphGenerationWorker(
            self.controller.db,
            mode_class=mode_class,
            export_timestamp=export_timestamp,
            selected_date=selected_date,
            output_dir="output",
            category=category
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
    
    def showEvent(self, event: QEvent):
        """Override showEvent to defer panel creation until after window is shown."""
        super().showEvent(event)
        logger = logging.getLogger("WeatherApp.gui.main_window")
        logger.debug("MainWindow.showEvent() — window shown, deferring panel creation")
        # Defer panel creation to next event loop cycle (after window is fully rendered)
        QTimer.singleShot(100, self._create_panels_lazily)
    
    def _create_panels_lazily(self):
        """Create panels lazily after window is shown."""
        import time
        logger = logging.getLogger("WeatherApp.gui.main_window")
        logger.debug("MainWindow._create_panels_lazily() — starting")

        # Import panel modules
        logger.debug("Importing deferred panel modules")
        from gui.panels.solar_panel import SolarPanel
        from gui.panels.storm_panel import StormPanel
        from gui.panels.lightning_panel import LightningPanel

        # Create SolarPanel
        if not self._panels_created['solar']:
            try:
                solar_panel_start = time.time()
                solar_panel = SolarPanel(self.controller.db)
                elapsed = time.time() - solar_panel_start
                logger.debug("SolarPanel created (deferred) in %.3fs", elapsed)

                # Replace placeholder with actual panel
                tab_index = self.tabs.indexOf(self.solar_panel)
                self.tabs.removeTab(tab_index)
                self.solar_panel = solar_panel
                self.tabs.insertTab(tab_index, self.solar_panel, "Sol")
                self._panels_created['solar'] = True
            except Exception as e:
                logger.error("Failed to create SolarPanel: %s", e, exc_info=True)
                self.solar_panel.setText(f"Solar panel failed to initialize: {e}")
                logger.warning("Using placeholder for SolarPanel")

        # Create StormPanel
        if not self._panels_created['storm']:
            try:
                storm_panel_start = time.time()
                storm_panel = StormPanel(self.controller.db)
                elapsed = time.time() - storm_panel_start
                logger.debug("StormPanel created (deferred) in %.3fs", elapsed)

                # Replace placeholder with actual panel
                tab_index = self.tabs.indexOf(self.storm_panel)
                self.tabs.removeTab(tab_index)
                self.storm_panel = storm_panel
                self.tabs.insertTab(tab_index, self.storm_panel, "Åska")
                self._panels_created['storm'] = True
            except Exception as e:
                logger.error("Failed to create StormPanel: %s", e, exc_info=True)
                self.storm_panel.setText(f"Storm panel failed to initialize: {e}")
                logger.warning("Using placeholder for StormPanel")

        # Create LightningPanel
        if not self._panels_created['lightning']:
            try:
                lightning_panel_start = time.time()
                lightning_panel = LightningPanel(self.controller.db)
                elapsed = time.time() - lightning_panel_start
                logger.debug("LightningPanel created (deferred) in %.3fs", elapsed)

                # Replace placeholder with actual panel
                tab_index = self.tabs.indexOf(self.lightning_panel)
                self.tabs.removeTab(tab_index)
                self.lightning_panel = lightning_panel
                self.tabs.insertTab(tab_index, self.lightning_panel, "Blixtar")
                self._panels_created['lightning'] = True
            except Exception as e:
                logger.error("Failed to create LightningPanel: %s", e, exc_info=True)
                self.lightning_panel.setText(f"Lightning panel failed to initialize: {e}")
                logger.warning("Using placeholder for LightningPanel")

        logger.debug("MainWindow._create_panels_lazily() — complete")
    
    def refresh_all(self):
        """Refresh all UI components."""
        # Reset pending flag
        self.pending_refresh = False
        
        self.city_panel.refresh()
        self.weather_panel.refresh()
        self.stats_tab.refresh()
        self.averages_tab.refresh()
        self.warnings_tab.refresh()
        self.api_status_tab.refresh()
        self.logs_tab.refresh()
