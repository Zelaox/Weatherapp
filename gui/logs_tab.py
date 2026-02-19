"""Logs tab."""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QPushButton, QHBoxLayout
)
from PyQt5.QtCore import Qt


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
