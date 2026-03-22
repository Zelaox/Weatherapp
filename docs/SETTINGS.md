# Settings Dialog — Technical Documentation

## Overview

The settings system consists of three components:

| Component | File | Responsibility |
|---|---|---|
| `SettingsDialog` | `gui/settings_dialog.py` | 5-tab PyQt5 dialog — reads/writes all 10 settings |
| `apply_theme(app, dark)` | `gui/settings_dialog.py` | Module-level function — applies dark or light QSS to `QApplication` |
| `ConfigLoader` | `utils/config_loader.py` | Persistence layer — `load_config()`, `update_config()`, `setdefault` merge |

---

## Configuration Keys

All keys live under `config["settings"]`. The table below shows every key, its type, default value, and which dialog tab controls it.

| Key | Type | Default | Tab | Description |
|---|---|---|---|---|
| `auto_update_interval_minutes` | `int` | `10` | Data | Interval between automatic API fetches |
| `data_retention_days` | `int` | `90` | Data | How many days of `weather_data` rows to keep |
| `dark_mode` | `bool` | `false` | Utseende | Activates dark QSS theme |
| `temperature_unit` | `str` | `"C"` | Utseende | `"C"` (Celsius) or `"F"` (Fahrenheit) |
| `map_default_layer` | `str` | `"stations"` | Karta | Active layer on map load: `"stations"`, `"heatmap"`, or `"sensors"` |
| `heatmap_opacity` | `int` | `70` | Karta | Heatmap layer opacity, 0–100 |
| `inversion_model_version` | `int` | `3` | *(read-only in Debug tab)* | Version tag for the inversion risk model — never modified by the dialog |
| `debug_mode` | `bool` | `false` | Debug | Shows raw/normalised analytical values in map popups |

### Config-merge safety

On every `_load_config()` call, new default keys are injected into existing user configs via a `setdefault` loop:

```python
for key, value in DEFAULT_CONFIG["settings"].items():
    loaded["settings"].setdefault(key, value)
```

This guarantees that users upgrading from older `config.json` versions get new keys at their defaults without overwriting values they have already set.

---

## SettingsDialog

### Instantiation

```python
from gui.settings_dialog import SettingsDialog

dlg = SettingsDialog(config_loader)   # pass the shared ConfigLoader instance
if dlg.exec_() == QDialog.Accepted:
    # changes already persisted to config.json
    pass
```

### Invariants

- **No hardcoded defaults in the dialog.** Every widget is initialised from `config_loader.get("settings.key")`. If a key is missing in config it will have been added by the merge loop before the dialog opens.
- **Single atomic write.** On `Accepted`, all changed values are collected into one dict and written with a single `config_loader.update_config(changes)` call. No partial state is ever persisted.
- **No side effects on Cancel.** `QDialog.Rejected` exits without touching `config.json`.

### Tab structure

| # | Tab label | Widgets |
|---|---|---|
| 0 | Utseende | Dark mode `QCheckBox`, temperature unit `QComboBox` (`°C` / `°F`) |
| 1 | Karta | Map default layer `QComboBox`, heatmap opacity `QSlider` 0–100 |
| 2 | Data | Auto-update interval `QSpinBox` (1–60 min), data retention `QSpinBox` (7–365 days) |
| 3 | API-nycklar | OpenWeatherMap key `QLineEdit` (echo mode Password), OpenAQ key `QLineEdit` (echo mode Password) |
| 4 | Debug | Debug mode `QCheckBox`, inversion model version `QLabel` (read-only) |

---

## apply_theme()

```python
def apply_theme(app: QApplication, dark: bool) -> None
```

- `dark=True` → applies a full dark QSS stylesheet to `app`
- `dark=False` → calls `app.setStyleSheet("")` to restore the platform default system theme

Called in two places:

1. **`MainWindow.__init__`** — immediately after `_init_ui()` to restore the saved theme at startup without flicker
2. **`MainWindow._show_settings_dialog()`** — first step in the post-close sequence (see below)

### Dark QSS scope

The dark stylesheet targets:
- `QMainWindow`, `QDialog`, `QWidget` — background `#1e1e1e`, foreground `#d4d4d4`
- `QTabWidget`, `QTabBar` — dark tab backgrounds, active tab highlight `#0078d4`
- `QMenuBar`, `QMenu`, `QMenu::item:selected` — matching dark palette
- `QPushButton` — dark background `#3c3c3c`, hover `#505050`
- `QLineEdit`, `QTextEdit`, `QPlainTextEdit`, `QComboBox`, `QSpinBox` — dark input fields, border `#555`
- `QScrollBar` — minimal dark scrollbar
- `QListWidget`, `QTableWidget`, `QTreeWidget` — dark item backgrounds, selection `#094771`
- `QGroupBox` — dark border `#555`

---

## Post-Close Sequence

After `SettingsDialog.exec_()` returns `Accepted`, `MainWindow._show_settings_dialog()` executes the following steps **in order**:

```
1. apply_theme(app, dark)          — theme applied before any widget repaint
2. controller.pause_auto_update()  — scheduler stopped, prevents concurrent API fetch
3. stations_tab.load_map()         — map HTML rebuilt with new layer/opacity settings
4. controller.restart_auto_update(minutes)  — scheduler restarted with new interval
```

**Why this order matters:**

- `apply_theme` first ensures no widget repaints during map reload use the wrong palette.
- `pause_auto_update` before `load_map` prevents a scheduled fetch from firing while the Leaflet JS context is being rebuilt (which would cause a double fetch and potential race condition).
- `restart_auto_update` last ensures the new interval from settings is picked up.

### Controller interface

These two methods are wired up in `main.py`:

```python
controller.pause_auto_update = scheduler.stop
controller.restart_auto_update = lambda minutes: (
    scheduler.set_interval(minutes), scheduler.start()
)
```

`pause_auto_update` is semantically distinct from disabling auto-update — it only halts the timer temporarily. `restart_auto_update(minutes)` always re-enables and reconfigures it.

---

## See also

- [DATABASE.md](DATABASE.md) — SQLite, `parameter_registry`, wind units  
- [ANALYTICAL_MAP.md](ANALYTICAL_MAP.md) — Stations tab map architecture

---

## Version History

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-02 | Initial settings dialog with 5 tabs, 10 keys, dark mode, debug mode |
