"""Stations tab with analytical Leaflet map showing OpenAQ sensors."""

import json
import math
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from zoneinfo import ZoneInfo
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QDialog, QFormLayout, QLineEdit, QDialogButtonBox, QMessageBox
)
from PyQt5.QtCore import Qt, QUrl
import logging
from utils.parameter_formatter import format_parameter_name
from analytics.warnings import WarningDetector

# Try to import QWebEngineView (optional dependency)
try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView
    WEBENGINE_AVAILABLE = True
except ImportError:
    WEBENGINE_AVAILABLE = False

logger = logging.getLogger("WeatherApp.gui.stations_tab")

# ---------------------------------------------------------------------------
# Inversion score configuration — the complete set of non-derived constants.
# These are sensitivity/tolerance parameters, not physical thresholds.
# ---------------------------------------------------------------------------
INVERSION_P_LOW  = 5    # lower winsorization percentile
INVERSION_P_HIGH = 95   # upper winsorization percentile
INVERSION_WIND_WEIGHT     = 0.6
INVERSION_HUMIDITY_WEIGHT = 0.4


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp value to [lo, hi]."""
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# MapDataBuilder
# ---------------------------------------------------------------------------

class MapDataBuilder:
    """
    Builds the full enriched JSON payload consumed by the Leaflet map.

    All intelligence lives here in Python.  The JavaScript layer only
    renders — it makes no decisions.

    Sub-computations:
      A  Per-city enriched record (AQI colour, trend, inversion score, region)
      B  Relative cluster analysis (deviation from 7-day national baseline)
      C  Winsorized inversion score (outlier-robust, temporally stable)
      D  Station density map (self-calibrating heatmap radius per city)
    """

    def __init__(self, db, warning_detector: WarningDetector):
        self.db = db
        self.detector = warning_detector

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def build(self) -> Dict:
        """
        Build and return the complete map payload.

        Returns:
            {
                "cities":         [...],   # per-city enriched records
                "sensors":        [...],   # raw sensor markers
                "cluster_alerts": [...],   # regional deviation alerts
                "score_metadata": {...},   # inversion score calibration info
            }
        """
        # ---- Fetch base data ----
        city_weather = self.db.get_cities_with_weather_for_map()
        all_sensors  = self.db.get_all_sensors()
        national_7d  = self.db.get_national_pm25_7day_average()

        # ---- Fetch winsorized bounds once for both parameters ----
        wind_lo, wind_hi = self.db.get_parameter_winsorized_bounds(
            "wind_speed", INVERSION_P_LOW, INVERSION_P_HIGH
        )
        hum_lo, hum_hi = self.db.get_parameter_winsorized_bounds(
            "humidity", INVERSION_P_LOW, INVERSION_P_HIGH
        )

        bounds_available = (
            wind_lo is not None and wind_hi is not None
            and hum_lo is not None and hum_hi is not None
        )

        wind_range = (wind_hi - wind_lo) if bounds_available else None
        hum_range  = (hum_hi  - hum_lo)  if bounds_available else None

        # ---- Collect row count for metadata ----
        try:
            conn = self.db.get_connection()
            cur  = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM weather_data "
                "WHERE wind_speed IS NOT NULL AND humidity IS NOT NULL"
            )
            data_rows_used = cur.fetchone()[0]
        except Exception:
            data_rows_used = 0

        score_metadata = {
            "wind_bounds":      [wind_lo, wind_hi],
            "humidity_bounds":  [hum_lo,  hum_hi],
            "percentile_range": [INVERSION_P_LOW, INVERSION_P_HIGH],
            "data_rows_used":   data_rows_used,
            "bounds_available": bounds_available,
        }

        # ---- Build per-city enriched records ----
        cities_out = []
        valid_cities = []   # only cities with pm25_24h != None

        for cw in city_weather:
            city_id = cw["city_id"]

            # 24-hour rolling PM2.5
            pm25_24h = self.db.get_24h_rolling_average(city_id, "pm25")

            # AQI level + colour — single source of truth: WarningDetector
            if pm25_24h is not None:
                level = self.detector.get_warning_level(pm25_24h)
                color = self.detector.LEVEL_COLORS[level]
                level_name = self.detector.LEVEL_NAMES[level]
            else:
                level = "no_data"
                color = "#cccccc"
                level_name = "Ingen data"

            # 24-hour PM2.5 trend (list of {ts, pm25})
            history = self.db.get_weather_history(city_id, hours=24)
            trend_24h = [
                {
                    "ts":   str(h.get("timestamp", "")),
                    "pm25": h.get("pm25"),
                }
                for h in history
                if h.get("pm25") is not None
            ]

            # Inversion score
            inversion_score = self._compute_inversion_score(
                wind_speed=cw.get("wind_speed"),
                humidity=cw.get("humidity"),
                wind_lo=wind_lo, wind_hi=wind_hi,
                hum_lo=hum_lo,   hum_hi=hum_hi,
                wind_range=wind_range, hum_range=hum_range,
                bounds_available=bounds_available,
                city_id=city_id,
            )

            record = {
                "city_id":         city_id,
                "city_name":       cw["city_name"],
                "latitude":        cw["latitude"],
                "longitude":       cw["longitude"],
                "pm25_24h":        pm25_24h,
                "aqi_level":       level,
                "aqi_color":       color,
                "aqi_level_name":  level_name,
                "temperature":     cw.get("temperature"),
                "humidity":        cw.get("humidity"),
                "wind_speed":      cw.get("wind_speed"),
                "no2":             cw.get("no2"),
                "o3":              cw.get("o3"),
                "trend_24h":       trend_24h,
                "inversion_score": inversion_score,
                "low_density":     False,   # filled below in section D
                "density_radius":  0,       # filled below in section D
                "cluster_region":  None,    # filled below in section B
            }
            cities_out.append(record)

            if pm25_24h is not None:
                valid_cities.append(record)

        # ---- Section B: regional cluster analysis ----
        cluster_alerts = self._compute_cluster_alerts(valid_cities, national_7d)

        # ---- Section D: station density ----
        self._compute_density(cities_out)

        # ---- Format sensors for raw marker layer ----
        sensors_out = self._format_sensors(all_sensors)

        return {
            "cities":         cities_out,
            "sensors":        sensors_out,
            "cluster_alerts": cluster_alerts,
            "score_metadata": score_metadata,
        }

    # ------------------------------------------------------------------
    # Section C — winsorized inversion score
    # ------------------------------------------------------------------

    def _compute_inversion_score(
        self,
        wind_speed: Optional[float],
        humidity:   Optional[float],
        wind_lo: Optional[float], wind_hi: Optional[float],
        hum_lo:  Optional[float], hum_hi:  Optional[float],
        wind_range: Optional[float], hum_range: Optional[float],
        bounds_available: bool,
        city_id: int,
    ) -> Optional[float]:
        """
        Compute inversion risk score in [0, 100].

        Returns None if bounds are unavailable, ranges are zero,
        or input values are None.
        """
        if not bounds_available:
            return None

        if wind_speed is None or humidity is None:
            return None

        if wind_range == 0:
            logger.info(
                f"inversion_score: wind_range=0 for city {city_id}, "
                f"score set to null (data quality signal)"
            )
            return None

        if hum_range == 0:
            logger.info(
                f"inversion_score: hum_range=0 for city {city_id}, "
                f"score set to null (data quality signal)"
            )
            return None

        wind_norm = _clamp((wind_speed - wind_lo) / wind_range, 0.0, 1.0)
        hum_norm  = _clamp((humidity   - hum_lo)  / hum_range,  0.0, 1.0)

        score = (
            (1.0 - wind_norm) * INVERSION_WIND_WEIGHT
            + hum_norm        * INVERSION_HUMIDITY_WEIGHT
        ) * 100.0

        return round(score, 1)

    # ------------------------------------------------------------------
    # Section B — relative cluster analysis
    # ------------------------------------------------------------------

    def _compute_cluster_alerts(
        self,
        valid_cities: List[Dict],
        national_7d:  Optional[float],
    ) -> List[Dict]:
        """
        Emit cluster alerts only when a region deviates from the
        7-day national baseline by more than the deviation_factor.

        The north/south boundary is the median latitude of all valid cities.
        deviation_factor is derived from existing WarningDetector thresholds.
        """
        if not valid_cities or national_7d is None or national_7d == 0:
            return []

        # Deviation factor: ratio of two existing threshold values — not a new constant
        deviation_factor = (
            self.detector.THRESHOLDS["moderate"] / self.detector.THRESHOLDS["good"]
        )

        # Dynamic north/south boundary = median latitude of valid cities
        lats = sorted(c["latitude"] for c in valid_cities)
        n = len(lats)
        if n == 0:
            return []
        mid = n // 2
        if n % 2 == 1:
            median_lat = lats[mid]
        else:
            median_lat = (lats[mid - 1] + lats[mid]) / 2.0

        # Split into regions
        regions = {
            "norr":  [c for c in valid_cities if c["latitude"] >= median_lat],
            "söder": [c for c in valid_cities if c["latitude"] <  median_lat],
        }

        alerts = []
        for region_label, members in regions.items():
            if not members:
                continue
            region_mean = sum(c["pm25_24h"] for c in members) / len(members)
            threshold   = national_7d * deviation_factor

            if region_mean > threshold:
                deviation_pct = round((region_mean / national_7d - 1.0) * 100.0, 1)
                alerts.append({
                    "region":           region_label,
                    "region_mean":      round(region_mean, 2),
                    "national_baseline": round(national_7d, 2),
                    "deviation_pct":    deviation_pct,
                    "city_count":       len(members),
                })

        return alerts

    # ------------------------------------------------------------------
    # Section D — station density
    # ------------------------------------------------------------------

    def _compute_density(self, cities: List[Dict]) -> None:
        """
        Mutates each city record in-place with:
          density_radius  — count of neighbours within 2° lat/lon box
          low_density     — True if fewer than 2 neighbours
        """
        for city in cities:
            lat = city["latitude"]
            lon = city["longitude"]
            count = sum(
                1 for other in cities
                if other is not city
                and abs(other["latitude"]  - lat) <= 2.0
                and abs(other["longitude"] - lon) <= 2.0
            )
            city["density_radius"] = count
            city["low_density"]    = count < 2

    # ------------------------------------------------------------------
    # Sensor formatter
    # ------------------------------------------------------------------

    def _format_sensors(self, sensors: List[Dict]) -> List[Dict]:
        """Format raw sensor records for the JS sensor marker layer."""
        out = []
        for s in sensors:
            fs = s.copy()
            fs["formatted_parameter"] = (
                format_parameter_name(s["parameter"])
                if s.get("parameter")
                else "Okänd"
            )
            fs["formatted_timestamp"] = _format_timestamp(s.get("last_updated"))
            out.append(fs)
        return out


# ---------------------------------------------------------------------------
# Timestamp helper (module-level, used by both MapDataBuilder and StationsTab)
# ---------------------------------------------------------------------------

def _format_timestamp(timestamp) -> str:
    if timestamp is None:
        return "Okänd"
    try:
        if isinstance(timestamp, str):
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"]:
                try:
                    dt = datetime.strptime(timestamp, fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=ZoneInfo("Europe/Stockholm"))
                    return dt.strftime("%Y-%m-%d %H:%M")
                except ValueError:
                    continue
            return timestamp
        elif isinstance(timestamp, datetime):
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=ZoneInfo("Europe/Stockholm"))
            else:
                timestamp = timestamp.astimezone(ZoneInfo("Europe/Stockholm"))
            return timestamp.strftime("%Y-%m-%d %H:%M")
        else:
            return str(timestamp)
    except Exception:
        return "Okänd"


# ---------------------------------------------------------------------------
# CustomMarkerDialog (unchanged)
# ---------------------------------------------------------------------------

class CustomMarkerDialog(QDialog):
    """Dialog for adding custom markers."""

    def __init__(self, parent=None, lat: Optional[float] = None, lon: Optional[float] = None):
        super().__init__(parent)
        self.setWindowTitle("Lägg till Custom Marker")
        self.setModal(True)
        self._init_ui(lat, lon)

    def _init_ui(self, lat: Optional[float], lon: Optional[float]):
        layout = QFormLayout(self)

        self.lat_input = QLineEdit()
        if lat is not None:
            self.lat_input.setText(str(lat))
        self.lat_input.setPlaceholderText("t.ex. 59.3293")
        layout.addRow("Latitud:", self.lat_input)

        self.lon_input = QLineEdit()
        if lon is not None:
            self.lon_input.setText(str(lon))
        self.lon_input.setPlaceholderText("t.ex. 18.0686")
        layout.addRow("Longitud:", self.lon_input)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("t.ex. Min sensor")
        layout.addRow("Namn:", self.name_input)

        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("t.ex. Luftkvalitetssensor hemma")
        layout.addRow("Beskrivning:", self.desc_input)

        self.value_input = QLineEdit()
        self.value_input.setPlaceholderText("Valfritt värde (t.ex. 15.5)")
        layout.addRow("Värde (µg/m³):", self.value_input)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def _validate_and_accept(self):
        try:
            lat = float(self.lat_input.text().strip())
            lon = float(self.lon_input.text().strip())
            if not (-90 <= lat <= 90):
                QMessageBox.warning(self, "Fel", "Latitud måste vara mellan -90 och 90")
                return
            if not (-180 <= lon <= 180):
                QMessageBox.warning(self, "Fel", "Longitud måste vara mellan -180 och 180")
                return
            self.latitude    = lat
            self.longitude   = lon
            self.name        = self.name_input.text().strip()
            self.description = self.desc_input.text().strip()
            value_str        = self.value_input.text().strip()
            self.value       = float(value_str) if value_str else None
            self.accept()
        except ValueError:
            QMessageBox.warning(self, "Fel", "Ogiltiga koordinater eller värde")

    def get_marker_data(self) -> Dict:
        return {
            "latitude":    self.latitude,
            "longitude":   self.longitude,
            "name":        self.name,
            "description": self.description,
            "value":       self.value,
        }


# ---------------------------------------------------------------------------
# StationsTab
# ---------------------------------------------------------------------------

class StationsTab(QWidget):
    """Tab showing stations and sensors on an analytical interactive map."""

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self._sensors_loaded = False
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if not WEBENGINE_AVAILABLE:
            error_label = QLabel("WebEngine krävs för karta. Installera PyQtWebEngine.")
            error_label.setAlignment(Qt.AlignCenter)
            error_label.setStyleSheet("color: red; font-size: 14px; padding: 20px;")
            layout.addWidget(error_label)
            return

        toolbar = QHBoxLayout()
        refresh_button = QPushButton("Uppdatera Stationer")
        refresh_button.clicked.connect(self._refresh_map)
        toolbar.addWidget(refresh_button)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.map_view = QWebEngineView()
        layout.addWidget(self.map_view)

        self._load_map()

    # ------------------------------------------------------------------
    # Map loading
    # ------------------------------------------------------------------

    def _load_map(self):
        if not WEBENGINE_AVAILABLE:
            return

        warning_detector = WarningDetector(self.controller.db)
        builder = MapDataBuilder(self.controller.db, warning_detector)

        try:
            payload = builder.build()
        except Exception as e:
            logger.error(f"MapDataBuilder.build() failed: {e}")
            payload = {"cities": [], "sensors": [], "cluster_alerts": [], "score_metadata": {}}

        html = self._generate_map_html(payload)
        self.map_view.setHtml(html)
        self.map_view.page().titleChanged.connect(self._on_title_changed)
        self._sensors_loaded = True

    def _refresh_map(self):
        logger.info("Uppdaterar analytisk karta")
        self._load_map()

    # ------------------------------------------------------------------
    # HTML / Leaflet generation
    # ------------------------------------------------------------------

    def _generate_map_html(self, payload: Dict) -> str:
        """
        Generate the full Leaflet HTML from the enriched payload.

        Python injects one JSON object.  JavaScript only renders.
        No logic crosses the boundary in either direction.
        """
        cities  = payload.get("cities", [])
        sensors = payload.get("sensors", [])

        # Compute map centre from cities with coordinates
        lats = [c["latitude"]  for c in cities if c.get("latitude")  is not None]
        lons = [c["longitude"] for c in cities if c.get("longitude") is not None]
        if lats and lons:
            center_lat = sum(lats) / len(lats)
            center_lon = sum(lons) / len(lons)
        else:
            center_lat, center_lon = 62.0, 15.0

        payload_json = json.dumps(payload, default=str)

        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.heat@0.2.0/dist/leaflet-heat.js"></script>
<style>
  body  {{ margin:0; padding:0; font-family: sans-serif; }}
  #map  {{ height:100vh; width:100%; }}

  /* Layer toggle toolbar */
  #layer-toolbar {{
    position: absolute; top: 10px; left: 50px; z-index: 1000;
    background: rgba(255,255,255,0.92); border-radius: 6px;
    padding: 6px 10px; box-shadow: 0 2px 6px rgba(0,0,0,0.3);
    display: flex; gap: 8px; align-items: center;
  }}
  .layer-btn {{
    padding: 4px 10px; border: 1px solid #999; border-radius: 4px;
    cursor: pointer; font-size: 12px; background: #f0f0f0;
    user-select: none;
  }}
  .layer-btn.active {{ background: #3a7bd5; color: #fff; border-color: #3a7bd5; }}

  /* Cluster alert banner */
  #cluster-banner {{
    position: absolute; bottom: 30px; left: 50%; transform: translateX(-50%);
    z-index: 1000; display: flex; flex-direction: column; gap: 6px;
    max-width: 480px; width: 90%;
  }}
  .cluster-alert {{
    background: rgba(220,53,69,0.88); color: #fff;
    padding: 7px 14px; border-radius: 6px; font-size: 13px;
    box-shadow: 0 2px 6px rgba(0,0,0,0.35);
  }}

  /* Popup styles */
  .popup-title     {{ font-weight: bold; font-size: 14px; margin-bottom: 4px; }}
  .aqi-badge       {{ display:inline-block; padding:2px 8px; border-radius:10px;
                      color:#fff; font-size:11px; font-weight:bold; margin-bottom:6px; }}
  .sparkline-wrap  {{ margin: 6px 0; }}
  .inv-bar-wrap    {{ margin: 6px 0; }}
  .inv-bar-bg      {{ background:#e0e0e0; border-radius:4px; height:10px; width:180px; }}
  .inv-bar-fill    {{ height:10px; border-radius:4px; }}
  .meta-note       {{ font-size:10px; color:#888; margin-top:4px; }}
  .low-density-note {{ font-size:11px; color:#e67e22; margin-top:4px; }}
</style>
</head>
<body>

<div id="layer-toolbar">
  <span style="font-size:12px;font-weight:bold;color:#555;">Lager:</span>
  <span class="layer-btn active" id="btn-markers"  onclick="toggleLayer('markers')">Stationer</span>
  <span class="layer-btn active" id="btn-heatmap"  onclick="toggleLayer('heatmap')">Heatmap</span>
  <span class="layer-btn active" id="btn-sensors"  onclick="toggleLayer('sensors')">Sensorer</span>
</div>

<div id="cluster-banner"></div>
<div id="map"></div>

<script>
// ── Payload injected by Python ────────────────────────────────────────────
var PAYLOAD = {payload_json};

var cities        = PAYLOAD.cities        || [];
var sensors       = PAYLOAD.sensors       || [];
var clusterAlerts = PAYLOAD.cluster_alerts || [];
var scoreMeta     = PAYLOAD.score_metadata || {{}};

// ── Map init ─────────────────────────────────────────────────────────────
var map = L.map('map').setView([{center_lat}, {center_lon}], 6);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
  attribution: '© OpenStreetMap contributors'
}}).addTo(map);
L.control.zoom({{ position: 'topright' }}).addTo(map);
map.scrollWheelZoom.enable();

// ── Layer groups ─────────────────────────────────────────────────────────
var markerGroup  = L.layerGroup().addTo(map);
var sensorGroup  = L.layerGroup().addTo(map);
var heatLayer    = null;
var layerState   = {{ markers: true, heatmap: true, sensors: true }};

// ── Sparkline SVG helper ─────────────────────────────────────────────────
function buildSparkline(trend) {{
  if (!trend || trend.length < 2) return '<em style="font-size:11px;color:#aaa;">Trend ej tillgänglig</em>';
  var vals = trend.map(function(p) {{ return p.pm25; }}).filter(function(v) {{ return v != null; }});
  if (vals.length < 2) return '<em style="font-size:11px;color:#aaa;">Otillräcklig data</em>';
  var W = 180, H = 40, pad = 4;
  var mn = Math.min.apply(null, vals), mx = Math.max.apply(null, vals);
  var rng = mx - mn || 1;
  var pts = vals.map(function(v, i) {{
    var x = pad + (i / (vals.length - 1)) * (W - 2 * pad);
    var y = H - pad - ((v - mn) / rng) * (H - 2 * pad);
    return x.toFixed(1) + ',' + y.toFixed(1);
  }}).join(' ');
  return '<svg width="' + W + '" height="' + H + '" style="display:block">' +
    '<polyline points="' + pts + '" fill="none" stroke="#3a7bd5" stroke-width="1.5"/>' +
    '<text x="2" y="' + (H - 2) + '" font-size="9" fill="#999">' + mn.toFixed(1) + '</text>' +
    '<text x="2" y="10" font-size="9" fill="#999">' + mx.toFixed(1) + '</text>' +
    '</svg>';
}}

// ── Inversion gauge helper ────────────────────────────────────────────────
function buildInvGauge(score, meta) {{
  if (score === null || score === undefined) {{
    var reason = meta.bounds_available
      ? 'Otillräcklig variationsbredd i historiken'
      : 'Historik &lt; 20 rader — kalibrering pågår';
    return '<div class="meta-note">Inversionspoäng: ' + reason + '</div>';
  }}
  var pct   = Math.round(score);
  var color = pct >= 70 ? '#c0392b' : pct >= 40 ? '#e67e22' : '#27ae60';
  var wb    = meta.wind_bounds     && meta.wind_bounds[0]     !== null;
  var hb    = meta.humidity_bounds && meta.humidity_bounds[0] !== null;
  var wStr  = wb ? meta.wind_bounds[0].toFixed(1) + '–' + meta.wind_bounds[1].toFixed(1) + ' m/s' : '?';
  var hStr  = hb ? meta.humidity_bounds[0].toFixed(0) + '–' + meta.humidity_bounds[1].toFixed(0) + '%' : '?';
  var rows  = meta.data_rows_used || 0;
  var pRange= (meta.percentile_range || [5,95]).join('–');
  return '<div class="inv-bar-wrap">' +
    '<div style="font-size:11px;margin-bottom:3px;">Inversionsrisk: <strong>' + pct + '/100</strong></div>' +
    '<div class="inv-bar-bg"><div class="inv-bar-fill" style="width:' + pct + '%;background:' + color + '"></div></div>' +
    '<div class="meta-note">Kalibrerad mot ' + rows + ' mätningar (p' + pRange + ')<br>' +
    'Vind: ' + wStr + ' · Fuktighet: ' + hStr + '</div>' +
    '</div>';
}}

// ── City markers layer ────────────────────────────────────────────────────
var heatPoints = [];

cities.forEach(function(city) {{
  var lat = city.latitude, lon = city.longitude;
  if (lat == null || lon == null) return;

  var color   = city.aqi_color   || '#cccccc';
  var pm25    = city.pm25_24h;
  var ws      = city.wind_speed;

  // Wind-speed ring radius: scale between 6 and 22px from wind_speed
  var ringR = 8;
  if (ws != null && scoreMeta.wind_bounds && scoreMeta.wind_bounds[1] != null) {{
    var wsMax = scoreMeta.wind_bounds[1];
    ringR = wsMax > 0 ? 6 + Math.round((ws / wsMax) * 16) : 8;
    ringR = Math.max(6, Math.min(22, ringR));
  }}

  // Outer wind-speed ring (grey, proportional)
  L.circleMarker([lat, lon], {{
    radius:      ringR,
    color:       '#888',
    weight:      1,
    fillColor:   '#888',
    fillOpacity: 0.08,
    interactive: false,
  }}).addTo(markerGroup);

  // Inner AQI-colour station dot
  var dot = L.circleMarker([lat, lon], {{
    radius:      7,
    color:       '#fff',
    weight:      1.5,
    fillColor:   color,
    fillOpacity: 0.9,
  }}).addTo(markerGroup);

  // Heatmap input: [lat, lon, intensity]
  if (pm25 != null) {{
    heatPoints.push([lat, lon, pm25]);
  }}

  // ── Analytical popup ────────────────────────────────────────────────
  var sparkline = buildSparkline(city.trend_24h);
  var invGauge  = buildInvGauge(city.inversion_score, scoreMeta);

  var pm25Str  = pm25  != null ? pm25.toFixed(1)  + ' µg/m³' : 'Ingen data';
  var tempStr  = city.temperature  != null ? city.temperature.toFixed(1)  + ' °C'    : '–';
  var humStr   = city.humidity     != null ? city.humidity.toFixed(0)     + '%'       : '–';
  var wsStr    = city.wind_speed   != null ? city.wind_speed.toFixed(1)   + ' m/s'   : '–';
  var no2Str   = city.no2          != null ? city.no2.toFixed(1)          + ' µg/m³' : '–';
  var o3Str    = city.o3           != null ? city.o3.toFixed(1)           + ' µg/m³' : '–';

  var densityNote = city.low_density
    ? '<div class="low-density-note">⚠ Gles stationstäckning — heatmap-interpolation osäker</div>'
    : '';

  var popupHtml =
    '<div class="popup-title">' + city.city_name + '</div>' +
    '<span class="aqi-badge" style="background:' + color + '">' + city.aqi_level_name + '</span><br>' +
    '<b>PM2.5 (24h):</b> ' + pm25Str + '<br>' +
    '<b>Temp:</b> ' + tempStr + ' &nbsp; <b>Fukt:</b> ' + humStr + ' &nbsp; <b>Vind:</b> ' + wsStr + '<br>' +
    '<b>NO₂:</b> ' + no2Str + ' &nbsp; <b>O₃:</b> ' + o3Str + '<br>' +
    '<div class="sparkline-wrap">' + sparkline + '</div>' +
    invGauge +
    densityNote +
    '<div style="margin-top:4px"><a href="https://www.google.com/maps?q=' + lat + ',' + lon +
    '" target="_blank" style="font-size:11px">Öppna i Google Maps</a></div>';

  dot.bindPopup(popupHtml, {{ maxWidth: 240 }});
}});

// ── Heatmap layer ─────────────────────────────────────────────────────────
// leaflet.heat calls canvas.getImageData() synchronously on addTo(map).
// Inside QWebEngineView, map.whenReady() fires before Qt's layout engine
// has assigned real pixel dimensions to the canvas, so size.x is still 0.
// Fix: defer with setTimeout + map.invalidateSize() so the Qt layout pass
// completes and the canvas has non-zero dimensions before leaflet.heat runs.
setTimeout(function() {{
  map.invalidateSize();
  if (heatPoints.length > 0) {{
    heatLayer = L.heatLayer(heatPoints, {{
      radius:  28,
      blur:    20,
      maxZoom: 10,
      max:     150,
      gradient: {{ 0.0: '#00e400', 0.25: '#ffff00', 0.5: '#ff7e00', 0.75: '#ff0000', 1.0: '#7e0023' }}
    }}).addTo(map);
  }}
}}, 300);

// ── Sensor marker layer ───────────────────────────────────────────────────
sensors.forEach(function(s) {{
  var lat = s.latitude, lon = s.longitude;
  if (lat == null || lon == null) return;

  var marker = L.marker([lat, lon]).addTo(sensorGroup);
  var content = '';

  if (s.is_custom == 1) {{
    var ci = s.custom_info ? JSON.parse(s.custom_info) : {{}};
    content += '<b>' + (ci.name || 'Custom Marker') + '</b><br>';
    if (ci.description) content += ci.description + '<br>';
    if (ci.value != null) content += 'Värde: ' + ci.value + ' µg/m³<br>';
  }} else {{
    content += '<b>Sensor ID:</b> '  + (s.sensor_id           || 'Okänd') + '<br>';
    content += '<b>Parameter:</b> '  + (s.formatted_parameter || 'Okänd') + '<br>';
    if (s.last_value   != null) content += '<b>Värde:</b> '     + s.last_value             + ' µg/m³<br>';
    if (s.formatted_timestamp && s.formatted_timestamp !== 'Okänd')
      content += '<b>Uppdaterad:</b> ' + s.formatted_timestamp + '<br>';
    if (s.city_name) content += '<b>Stad:</b> ' + s.city_name + '<br>';
  }}
  content += '<a href="https://www.google.com/maps?q=' + lat + ',' + lon +
             '" target="_blank">Öppna i Google Maps</a>';
  marker.bindPopup(content);
}});

// ── Cluster alert banner ──────────────────────────────────────────────────
(function() {{
  var banner = document.getElementById('cluster-banner');
  clusterAlerts.forEach(function(a) {{
    var div = document.createElement('div');
    div.className = 'cluster-alert';
    div.innerHTML =
      '⚠ Regional påverkan: <strong>' + a.region.charAt(0).toUpperCase() + a.region.slice(1) +
      'ra Sverige</strong> — PM2.5 snitt ' + a.region_mean.toFixed(1) +
      ' µg/m³ (+' + a.deviation_pct + '% mot nationellt 7d-snitt ' +
      a.national_baseline.toFixed(1) + ' µg/m³, ' + a.city_count + ' stationer)';
    banner.appendChild(div);
  }});
}})();

// ── Layer toggle logic ────────────────────────────────────────────────────
function toggleLayer(name) {{
  layerState[name] = !layerState[name];
  var btn = document.getElementById('btn-' + name);
  if (layerState[name]) {{
    btn.classList.add('active');
    if (name === 'markers') map.addLayer(markerGroup);
    if (name === 'sensors') map.addLayer(sensorGroup);
    if (name === 'heatmap' && heatLayer) map.addLayer(heatLayer);
  }} else {{
    btn.classList.remove('active');
    if (name === 'markers') map.removeLayer(markerGroup);
    if (name === 'sensors') map.removeLayer(sensorGroup);
    if (name === 'heatmap' && heatLayer) map.removeLayer(heatLayer);
  }}
}}

// ── Right-click context menu (custom marker placement) ───────────────────
map.on('contextmenu', function(e) {{
  window.mapRightClickLat = e.latlng.lat;
  window.mapRightClickLon = e.latlng.lng;
  document.title = 'MAP_RIGHT_CLICK:' + e.latlng.lat + ',' + e.latlng.lng;
}});
</script>
</body>
</html>"""
        return html

    # ------------------------------------------------------------------
    # Right-click → custom marker
    # ------------------------------------------------------------------

    def _on_title_changed(self, title: str):
        if title.startswith("MAP_RIGHT_CLICK:"):
            try:
                coords_str = title.replace("MAP_RIGHT_CLICK:", "")
                lat_str, lon_str = coords_str.split(",")
                lat = float(lat_str)
                lon = float(lon_str)
                self._on_map_right_click(lat, lon)
                self.map_view.page().runJavaScript("document.title = 'Stations Map';")
            except (ValueError, IndexError) as e:
                logger.warning(f"Fel vid parsing av right-click koordinater: {e}")

    def _on_map_right_click(self, lat: float, lon: float):
        dialog = CustomMarkerDialog(self, lat, lon)
        if dialog.exec_() == QDialog.Accepted:
            marker_data = dialog.get_marker_data()

            cities    = self.controller.get_all_cities()
            nearest   = None
            min_dist  = float("inf")

            for city in cities:
                dist = ((lat - city["latitude"]) ** 2 + (lon - city["longitude"]) ** 2) ** 0.5
                if dist < min_dist:
                    min_dist = dist
                    nearest  = city

            if nearest and min_dist < 0.5:
                city_id = nearest["id"]
            else:
                if cities:
                    city_id = cities[0]["id"]
                else:
                    QMessageBox.warning(self, "Fel", "Inga städer hittades. Lägg till en stad först.")
                    return

            custom_info = json.dumps({
                "name":        marker_data["name"],
                "description": marker_data["description"],
                "value":       marker_data["value"],
            })

            try:
                self.controller.db.add_custom_marker(
                    city_id=city_id,
                    latitude=lat,
                    longitude=lon,
                    custom_info=custom_info,
                )
                logger.info(f"Custom marker tillagd för stad {city_id}")
                QMessageBox.information(self, "Klart", "Custom marker tillagd!")
                self._refresh_map()
            except Exception as e:
                logger.error(f"Fel vid tillägg av custom marker: {e}")
                QMessageBox.warning(self, "Fel", f"Kunde inte lägga till marker: {e}")
