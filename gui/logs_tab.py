"""Logs tab."""

from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QTextEdit,
    QPushButton,
    QHBoxLayout,
)
from PyQt5.QtCore import Qt
import json


class LogsTab(QWidget):
    """Tab for displaying application logs."""
    
    def __init__(self, controller):
        """
        Initialize logs tab.
        
        Args:
            controller: Weather controller instance
        """
        super().__init__()
        self.controller = controller
        self._init_ui()
    
    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        refresh_button = QPushButton("Uppdatera")
        refresh_button.clicked.connect(self.refresh)
        button_layout.addWidget(refresh_button)
        
        clear_button = QPushButton("Rensa")
        clear_button.clicked.connect(self._clear_logs)
        button_layout.addWidget(clear_button)

        debug_button = QPushButton("Debugrapport")
        debug_button.clicked.connect(self._show_debug_report)
        button_layout.addWidget(debug_button)
        
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        # Log display
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFontFamily("Courier")
        self.log_text.setFontPointSize(9)
        layout.addWidget(self.log_text)
    
    def refresh(self):
        """Refresh log display."""
        logs = self.controller.get_logs()
        self.log_text.clear()
        self.log_text.setPlainText("\n".join(logs))
        
        # Scroll to bottom
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def _clear_logs(self):
        """Clear logs."""
        self.controller.clear_logs()
        self.refresh()

    def _show_debug_report(self):
        """Generate and display a dynamic debug report."""
        try:
            report = self.controller.generate_dynamic_debug_report()
            # Pretty-print JSON, but keep it generic and data-driven
            text = json.dumps(report, indent=2, ensure_ascii=False)
            self.log_text.clear()
            self.log_text.setPlainText(text)
            scrollbar = self.log_text.verticalScrollBar()
            scrollbar.setValue(scrollbar.minimum())
        except Exception as e:
            self.log_text.append(f"\n[DEBUG] Kunde inte generera debugrapport: {e}")
