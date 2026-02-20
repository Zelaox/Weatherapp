# Event-Driven UI Refresh Plan

## Overview

Replace timer-based UI refresh (5 seconds) with event-driven refresh that only updates UI when new data is actually saved to the database.

## Design Principles

- **No hardcoded values**: All intervals from config
- **No fallbacks**: Only emit signal when data is actually saved
- **Event-driven**: UI updates only on data change events
- **Dirty check**: Track if data was actually inserted (not just attempted)
- **Thread-safe**: Signals must be emitted from correct thread context

## Current Architecture

### Current Flow (Timer-Based)
```
QTimer (5 seconds)
    ↓
refresh_all() called
    ↓
All tabs refresh from DB
    ↓
UI repaints (even if no new data)
```

### Desired Flow (Event-Driven)
```
Scheduler (10 min)
    ↓
update_all_cities()
    ↓
_update_cities_thread()
    ↓
_update_city_weather()
    ↓
db.add_weather_data() → returns data_id if saved
    ↓
If data_id > 0 (new row inserted):
    ↓
Emit data_updated signal
    ↓
UI refresh (only when signal received)
```

## Implementation

### 1. Add PyQt Signal to WeatherController

**File**: `controllers/weather_controller.py`

**Changes**:
- Import `QObject` and `pyqtSignal` from `PyQt5.QtCore`
- Make `WeatherController` inherit from `QObject` (or create separate signal emitter)
- Add signal: `data_updated = pyqtSignal(int, int)`  # (city_id, data_id)

**Note**: Since `WeatherController` runs in background thread, we need to emit signals safely. Options:
- Option A: Create a separate `QObject` signal emitter in main thread
- Option B: Use `QMetaObject.invokeMethod()` to emit from main thread
- Option C: Use `QTimer.singleShot(0, lambda: signal.emit())` to queue signal

**Recommended**: Option A - Create `DataUpdateEmitter(QObject)` in main thread, pass to controller.

### 2. Track Data Insertion in Database

**File**: `database/db_manager.py`

**Current**: `add_weather_data()` returns `data_id` (lastrowid)

**Change**: 
- Already returns `data_id` if successful
- Return `None` or `0` if no data was inserted (deduplication logic)
- This is already handled by intelligent storage logic

**Verify**: Check if deduplication in `add_weather_data()` or `_update_city_weather()` prevents saving duplicates.

### 3. Emit Signal After Successful Save

**File**: `controllers/weather_controller.py`

**In `_update_city_weather()` method**:
- After calling `db.add_weather_data()`, check if `data_id` is valid (> 0)
- If valid, emit signal: `self.data_updated.emit(city_id, data_id)`

**Thread Safety**:
- Since `_update_cities_thread()` runs in background thread, signals must be emitted safely
- Use `QMetaObject.invokeMethod()` or queue signal to main thread

### 4. Remove Timer-Based Refresh

**File**: `gui/main_window.py`

**Remove**:
- `self.gui_refresh_timer = QTimer()` (lines 112-116)
- `self.gui_refresh_timer.start()` (line 121)
- Timer initialization and connection

**Keep**:
- `refresh_all()` method (still needed for manual refresh)
- Manual refresh button functionality

### 5. Connect Signal to UI Refresh

**File**: `gui/main_window.py` or `main.py`

**In `MainWindow.__init__()` or `main()`**:
- Connect signal: `controller.data_updated.connect(self.refresh_all)`
- Or use lambda: `controller.data_updated.connect(lambda city_id, data_id: self.refresh_all())`

**Thread Safety**:
- Signal connection automatically handles thread-safe emission
- PyQt signals are thread-safe by design

### 6. Optional: Last Update Timestamp Label

**File**: `gui/main_window.py`

**If desired** (for showing "Last update: 21:30"):
- Add optional 1-second timer that only updates timestamp label
- Does NOT refresh entire UI
- Updates from database query: `SELECT MAX(timestamp) FROM weather_data`

## Data Flow

```
UpdateScheduler (10 min timer)
    ↓
controller.update_all_cities()
    ↓
_update_cities_thread() [background thread]
    ↓
For each city:
    _update_city_weather()
        ↓
    db.add_weather_data()
        ↓
    Returns data_id (if saved) or None (if duplicate)
        ↓
    If data_id > 0:
        data_updated.emit(city_id, data_id) [queued to main thread]
            ↓
    Main thread receives signal
        ↓
    MainWindow.refresh_all() called
        ↓
    All tabs refresh from database
        ↓
    UI updates (only when new data exists)
```

## Edge Cases

### 1. Multiple Cities Updated Simultaneously
- Each city emits separate signal
- UI refreshes multiple times (acceptable, or debounce)
- **Solution**: Debounce refresh (wait 100ms, then refresh once)

### 2. No Data Saved (Deduplication)
- Signal not emitted
- UI not refreshed
- **Correct behavior** - no new data to show

### 3. Background Thread Signal Emission
- Signals from background thread must be queued
- PyQt handles this automatically with `pyqtSignal`
- **Verify**: Test signal emission from background thread

### 4. Manual Refresh
- Keep manual refresh button
- Calls `refresh_all()` directly
- Not dependent on signals

## Files to Modify

1. **controllers/weather_controller.py**
   - Add `QObject` inheritance or separate signal emitter
   - Add `data_updated = pyqtSignal(int, int)`
   - Emit signal after successful `add_weather_data()`

2. **gui/main_window.py**
   - Remove `gui_refresh_timer` (lines 110-122)
   - Connect `data_updated` signal to `refresh_all()`
   - Keep `refresh_all()` method for manual refresh

3. **main.py** (optional)
   - Verify signal connection if done here instead of MainWindow

4. **database/db_manager.py** (verify)
   - Ensure `add_weather_data()` returns `data_id` correctly
   - Verify deduplication logic doesn't prevent signal emission

## Testing

1. **Test signal emission**:
   - Enable auto-update
   - Verify signal emitted when data saved
   - Verify signal NOT emitted when duplicate prevented

2. **Test UI refresh**:
   - Verify UI updates only when signal received
   - Verify no constant repainting
   - Verify scroll position maintained

3. **Test manual refresh**:
   - Verify manual refresh button still works
   - Verify refresh doesn't depend on signals

4. **Test thread safety**:
   - Verify signals work from background thread
   - Verify UI updates on main thread only

## Benefits

- ✅ No constant UI repainting
- ✅ No scroll position reset
- ✅ Lower CPU usage
- ✅ Cleaner architecture
- ✅ Professional feel
- ✅ Only updates when data changes

## Migration Notes

- Remove 5-second timer completely
- Keep manual refresh functionality
- Ensure signal connection is thread-safe
- Test with auto-update enabled/disabled
