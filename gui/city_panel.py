"""City panel for managing cities."""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QListWidget, QPushButton, QHBoxLayout,
    QInputDialog, QMessageBox, QDialog, QFormLayout, QLineEdit, QDialogButtonBox
)
from PyQt5.QtCore import Qt, pyqtSignal
from utils.geocoding import Geocoder


class CityPanel(QWidget):
    """Left panel for city list management."""
    
    city_selected = pyqtSignal(int)  # Signal emitted when city is selected
    
    def __init__(self, controller):
        """
        Initialize city panel.
        
        Args:
            controller: Weather controller instance
        """
        super().__init__()
        self.controller = controller
        self.geocoder = Geocoder(controller.logger)
        self._init_ui()
        self.refresh()
    
    def _init_ui(self):
        """Initialize UI."""
        layout = QVBoxLayout(self)
        layout.setSpacing(5)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Title
        title = QPushButton("Städer")
        title.setEnabled(False)
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)
        
        # City list
        self.city_list = QListWidget()
        self.city_list.itemSelectionChanged.connect(self._on_city_selected)
        layout.addWidget(self.city_list)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.add_button = QPushButton("+ Lägg till")
        self.add_button.clicked.connect(self._add_city)
        button_layout.addWidget(self.add_button)
        
        self.remove_button = QPushButton("- Ta bort")
        self.remove_button.clicked.connect(self._remove_city)
        button_layout.addWidget(self.remove_button)
        
        layout.addLayout(button_layout)
    
    def _on_city_selected(self):
        """Handle city selection."""
        current_item = self.city_list.currentItem()
        if current_item:
            city_id = current_item.data(Qt.UserRole)
            self.controller.select_city(city_id)
            self.city_selected.emit(city_id)
    
    def _add_city(self):
        """Add a new city."""
        dialog = AddCityDialog(self, self.geocoder)
        if dialog.exec_() == QDialog.Accepted:
            name, lat, lon = dialog.get_city_data()
            try:
                city_id = self.controller.add_city(name, lat, lon)
                self.refresh()
                self.controller.logger.info(f"Lade till stad: {name}")
            except ValueError as e:
                QMessageBox.warning(self, "Fel", str(e))
    
    def _remove_city(self):
        """Remove selected city."""
        current_item = self.city_list.currentItem()
        if not current_item:
            QMessageBox.information(self, "Info", "Välj en stad att ta bort")
            return
        
        city_name = current_item.text()
        reply = QMessageBox.question(
            self,
            "Bekräfta",
            f"Ta bort {city_name}?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            city_id = current_item.data(Qt.UserRole)
            self.controller.remove_city(city_id)
            self.refresh()
            self.controller.logger.info(f"Tog bort stad: {city_name}")
    
    def refresh(self):
        """Refresh city list with error handling."""
        try:
            cities = self.controller.get_all_cities()
        except RecursionError:
            # Silently fail - don't show error dialog for recursion
            return
        except Exception as e:
            # Log error but don't show dialog to avoid spam
            if hasattr(self.controller, 'logger'):
                self.controller.logger.error(f"Fel vid uppdatering av stadlista: {e}")
            return
        
        self.city_list.clear()
        for city in cities:
            item_text = f"{city['name']}"
            from PyQt5.QtWidgets import QListWidgetItem
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, city['id'])
            self.city_list.addItem(item)
        
        if cities:
            self.city_list.setCurrentRow(0)


class AddCityDialog(QDialog):
    """Dialog for adding a city."""
    
    def __init__(self, parent, geocoder):
        """
        Initialize dialog.
        
        Args:
            parent: Parent widget
            geocoder: Geocoder instance
        """
        super().__init__(parent)
        self.geocoder = geocoder
        self.setWindowTitle("Lägg till stad")
        self.setModal(True)
        self._init_ui()
    
    def _init_ui(self):
        """Initialize UI."""
        layout = QFormLayout(self)
        
        # City name
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("t.ex. Stockholm")
        layout.addRow("Stadnamn:", self.name_input)
        
        # Manual coordinates option
        self.lat_input = QLineEdit()
        self.lat_input.setPlaceholderText("Latitud (lämna tom för geocoding)")
        layout.addRow("Latitud:", self.lat_input)
        
        self.lon_input = QLineEdit()
        self.lon_input.setPlaceholderText("Longitud (lämna tom för geocoding)")
        layout.addRow("Longitud:", self.lon_input)
        
        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
    
    def _validate_and_accept(self):
        """Validate input and geocode if needed."""
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Fel", "Ange stadnamn")
            return
        
        lat_str = self.lat_input.text().strip()
        lon_str = self.lon_input.text().strip()
        
        # Manual coordinates
        if lat_str and lon_str:
            try:
                lat = float(lat_str)
                lon = float(lon_str)
                if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                    raise ValueError("Ogiltiga koordinater")
                self.city_name = name
                self.city_lat = lat
                self.city_lon = lon
                self.accept()
                return
            except ValueError:
                QMessageBox.warning(self, "Fel", "Ogiltiga koordinater")
                return
        
        # Geocoding
        if not lat_str and not lon_str:
            coords = self.geocoder.geocode(name)
            if coords:
                self.city_name = name
                self.city_lat, self.city_lon = coords
                self.accept()
            else:
                QMessageBox.warning(self, "Fel", f"Kunde inte hitta koordinater för {name}")
        else:
            QMessageBox.warning(self, "Fel", "Ange både latitud och longitud, eller lämna båda tomma för geocoding")
    
    def get_city_data(self):
        """Get city data."""
        return self.city_name, self.city_lat, self.city_lon
