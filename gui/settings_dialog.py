"""Settings dialog and theme application for the weather application."""

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QCheckBox, QComboBox, QSlider, QSpinBox,
    QLineEdit, QDialogButtonBox, QFormLayout, QGroupBox,
    QApplication
)
from PyQt5.QtCore import Qt


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

_DARK_QSS = """
QMainWindow, QDialog, QWidget {
    background-color: #1e1e1e;
    color: #e0e0e0;
}
QTabWidget::pane {
    border: 1px solid #444;
    background-color: #1e1e1e;
}
QTabBar::tab {
    background-color: #2d2d2d;
    color: #e0e0e0;
    padding: 6px 14px;
    border: 1px solid #444;
    border-bottom: none;
}
QTabBar::tab:selected {
    background-color: #3c6de8;
    color: #ffffff;
}
QTabBar::tab:hover:!selected {
    background-color: #3a3a3a;
}
QLineEdit, QSpinBox, QComboBox, QTextEdit, QPlainTextEdit {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #555;
    border-radius: 3px;
    padding: 3px 6px;
    selection-background-color: #3c6de8;
}
QComboBox QAbstractItemView {
    background-color: #2d2d2d;
    color: #e0e0e0;
    selection-background-color: #3c6de8;
}
QPushButton {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #555;
    border-radius: 3px;
    padding: 5px 14px;
}
QPushButton:hover {
    background-color: #3a3a3a;
}
QPushButton:pressed {
    background-color: #3c6de8;
    color: #ffffff;
}
QCheckBox {
    color: #e0e0e0;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #555;
    border-radius: 2px;
    background-color: #2d2d2d;
}
QCheckBox::indicator:checked {
    background-color: #3c6de8;
    border-color: #3c6de8;
}
QSlider::groove:horizontal {
    height: 6px;
    background-color: #444;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background-color: #3c6de8;
    border: none;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}
QSlider::sub-page:horizontal {
    background-color: #3c6de8;
    border-radius: 3px;
}
QGroupBox {
    border: 1px solid #444;
    border-radius: 4px;
    margin-top: 8px;
    color: #e0e0e0;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
}
QHeaderView::section {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #444;
    padding: 4px;
}
QTableWidget {
    background-color: #1e1e1e;
    color: #e0e0e0;
    gridline-color: #444;
}
QTableWidget::item:selected {
    background-color: #3c6de8;
}
QScrollBar:vertical, QScrollBar:horizontal {
    background-color: #2d2d2d;
    width: 10px;
    height: 10px;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background-color: #555;
    border-radius: 4px;
    min-height: 20px;
    min-width: 20px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {
    background-color: #3c6de8;
}
QScrollBar::add-line, QScrollBar::sub-line {
    background: none;
    border: none;
}
QStatusBar {
    background-color: #2d2d2d;
    color: #aaaaaa;
}
QMenuBar {
    background-color: #2d2d2d;
    color: #e0e0e0;
}
QMenuBar::item:selected {
    background-color: #3c6de8;
}
QMenu {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #444;
}
QMenu::item:selected {
    background-color: #3c6de8;
}
QToolBar {
    background-color: #2d2d2d;
    border-bottom: 1px solid #444;
    spacing: 4px;
}
QLabel {
    color: #e0e0e0;
}
"""


def apply_theme(app: QApplication, dark: bool) -> None:
    """
    Apply dark or light theme to the entire QApplication.

    Args:
        app:  The running QApplication instance.
        dark: True → apply dark QSS; False → restore system theme (empty stylesheet).
    """
    if dark:
        app.setStyleSheet(_DARK_QSS)
    else:
        app.setStyleSheet("")


# ---------------------------------------------------------------------------
# SettingsDialog
# ---------------------------------------------------------------------------

class SettingsDialog(QDialog):
    """
    Application settings dialog — 5 tabs, 10 settings.

    All initial widget values are read from config_loader on __init__.
    On OK, all changes are written in a single update_config() call.
    On Cancel, nothing is written.

    Args:
        config_loader: ConfigLoader instance (the only dependency).
        parent:        Optional parent widget.
    """

    def __init__(self, config_loader, parent=None):
        super().__init__(parent)
        self._cfg = config_loader
        self.setWindowTitle("Inställningar")
        self.setMinimumSize(520, 420)
        self._init_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _init_ui(self):
        layout = QVBoxLayout(self)

        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_appearance_tab(), "Utseende")
        self._tabs.addTab(self._build_map_tab(),        "Karta")
        self._tabs.addTab(self._build_data_tab(),       "Data")
        self._tabs.addTab(self._build_api_tab(),        "API-nycklar")
        self._tabs.addTab(self._build_debug_tab(),      "Debug")
        layout.addWidget(self._tabs)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_ok)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # --- Tab: Utseende ---

    def _build_appearance_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.setSpacing(12)
        form.setContentsMargins(16, 16, 16, 16)

        self._dark_mode = QCheckBox()
        self._dark_mode.setChecked(bool(self._cfg.get_setting("dark_mode", False)))
        form.addRow("Mörkt läge:", self._dark_mode)

        self._temperature_unit = QComboBox()
        self._temperature_unit.addItems(["°C", "°F"])
        unit = self._cfg.get_setting("temperature_unit", "C")
        self._temperature_unit.setCurrentIndex(0 if unit == "C" else 1)
        form.addRow("Temperaturenhet:", self._temperature_unit)

        return widget

    # --- Tab: Karta ---

    def _build_map_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.setSpacing(12)
        form.setContentsMargins(16, 16, 16, 16)

        self._map_layer = QComboBox()
        layer_options = [("Stationer", "stations"), ("Heatmap", "heatmap"), ("Sensorer", "sensors")]
        for label, value in layer_options:
            self._map_layer.addItem(label, userData=value)
        saved_layer = self._cfg.get_setting("map_default_layer", "stations")
        idx = next((i for i, (_, v) in enumerate(layer_options) if v == saved_layer), 0)
        self._map_layer.setCurrentIndex(idx)
        form.addRow("Standard kartlager:", self._map_layer)

        opacity_row = QWidget()
        opacity_layout = QHBoxLayout(opacity_row)
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        self._heatmap_opacity = QSlider(Qt.Horizontal)
        self._heatmap_opacity.setRange(0, 100)
        saved_opacity = int(self._cfg.get_setting("heatmap_opacity", 70))
        self._heatmap_opacity.setValue(saved_opacity)
        self._opacity_label = QLabel(f"{saved_opacity}%")
        self._opacity_label.setMinimumWidth(36)
        self._heatmap_opacity.valueChanged.connect(
            lambda v: self._opacity_label.setText(f"{v}%")
        )
        opacity_layout.addWidget(self._heatmap_opacity)
        opacity_layout.addWidget(self._opacity_label)
        form.addRow("Heatmap opacitet:", opacity_row)

        return widget

    # --- Tab: Data ---

    def _build_data_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.setSpacing(12)
        form.setContentsMargins(16, 16, 16, 16)

        self._update_interval = QSpinBox()
        self._update_interval.setRange(1, 120)
        self._update_interval.setSuffix(" min")
        self._update_interval.setValue(
            int(self._cfg.get_setting("auto_update_interval_minutes", 10))
        )
        form.addRow("Auto-update intervall:", self._update_interval)

        self._retention_days = QSpinBox()
        self._retention_days.setRange(7, 365)
        self._retention_days.setSuffix(" dagar")
        self._retention_days.setValue(
            int(self._cfg.get_setting("data_retention_days", 90))
        )
        form.addRow("Datalagring:", self._retention_days)

        return widget

    # --- Tab: API-nycklar ---

    def _build_api_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        note = QLabel(
            "API-nycklar sparas i <code>config.json</code>. "
            "Nycklar i <code>.env</code> har alltid högre prioritet och visas inte här."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        form = QFormLayout()
        form.setSpacing(10)

        self._oaq_key = QLineEdit()
        self._oaq_key.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self._oaq_key.setPlaceholderText("OpenAQ API-nyckel")
        oaq_val = self._cfg.config.get("api_keys", {}).get("openaq") or ""
        self._oaq_key.setText(oaq_val)
        form.addRow("OpenAQ:", self._oaq_key)

        layout.addLayout(form)
        layout.addStretch()
        return widget

    # --- Tab: Debug ---

    def _build_debug_tab(self) -> QWidget:
        widget = QWidget()
        form = QFormLayout(widget)
        form.setSpacing(12)
        form.setContentsMargins(16, 16, 16, 16)

        self._debug_mode = QCheckBox()
        self._debug_mode.setChecked(bool(self._cfg.get_setting("debug_mode", False)))
        form.addRow("Debug-läge:", self._debug_mode)

        desc = QLabel(
            "När debug-läge är aktivt visar kartstationsmarkörer rådata, "
            "normaliserade värden (<code>wind_norm</code>, <code>hum_norm</code>), "
            "nationellt basvärde, <code>deviation_factor</code> och "
            "<code>inversion_model_version</code> direkt i popupen."
        )
        desc.setWordWrap(True)
        form.addRow(desc)

        return widget

    # ------------------------------------------------------------------
    # OK handler — single atomic write
    # ------------------------------------------------------------------

    def _on_ok(self):
        """Collect all widget values and write to config in one call."""
        unit = "C" if self._temperature_unit.currentIndex() == 0 else "F"
        layer = self._map_layer.currentData()

        oaq_key = self._oaq_key.text().strip() or None

        self._cfg.update_config({
            "settings": {
                "dark_mode":                    self._dark_mode.isChecked(),
                "temperature_unit":             unit,
                "map_default_layer":            layer,
                "heatmap_opacity":              self._heatmap_opacity.value(),
                "auto_update_interval_minutes": self._update_interval.value(),
                "data_retention_days":          self._retention_days.value(),
                "debug_mode":                   self._debug_mode.isChecked(),
            },
            "api_keys": {
                "openaq": oaq_key,
            },
        })
        self.accept()
