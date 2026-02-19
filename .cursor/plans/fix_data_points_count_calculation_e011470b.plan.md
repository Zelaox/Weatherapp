---
name: Fix Data Points Count Calculation
overview: Fix the data points count to show total rows in weather_data table instead of number of cities. Add a database method to count total rows and update the analyzer to use it dynamically.
todos: []
---

# Fix Data Points Count Calculation

## Problem

Currently, "Datapunkter" shows the number of cities (40) instead of the total number of data points in the database. The code uses `len(all_weather)` or `len(pm25_averages)`, which counts cities, not actual measurement rows.

## Data Model Clarification

In `weather_data` table:

- **1 row = 1 city × 1 timestamp**
- Each row contains multiple parameters (pm25, pm10, no2, o3, temperature, humidity, wind_speed) in the same row
- NOT normalized by parameter (not 1 row per parameter)

Example:

- 40 cities × 10 timestamps = 400 rows (not 40 × 10 × 4 parameters = 1600)

## Solution

Add database methods to count total rows and unique cities in `weather_data` table, then update the analyzer to use them dynamically.

## Implementation

### 1. Add Database Methods

**File**: `database/db_manager.py`

Add two new methods:

**Method 1: `get_total_data_points_count()`**

```sql
SELECT COUNT(*) FROM weather_data
```

- Returns `int` (total count of rows)
- **Error handling**: Let exceptions propagate (don't mask database errors)
- Returns `0` only if table exists but is empty (not if query fails)
- No hardcoded values
- Direct database query

**Method 2: `get_unique_cities_in_data_count()`** (optional enhancement)

```sql
SELECT COUNT(DISTINCT city_id) FROM weather_data
```

- Returns `int` (number of unique cities that have data)
- Same error handling as above
- Used for validation: ensures no cities are missing from data

**Location**: Add after `get_all_latest_weather()` method (around line 537)

### 2. Update Analyzer

**File**: `analytics/analyzer.py`

Update `get_all_cities_averages()` method:

**For 'latest' timeframe** (line ~204):

- Replace `'data_points': len(all_weather)` 
- With `'data_points': self.db.get_total_data_points_count()`

**For '24h' timeframe** (line ~263):

- Replace `'data_points': len(pm25_averages)`
- With `'data_points': self.db.get_total_data_points_count()`

**For empty data cases** (lines ~149, ~217):

- Replace `'data_points': 0`
- With `'data_points': self.db.get_total_data_points_count()` (still call DB, even if no averages - shows total historical data)

### 3. Error Handling

**Database Level** (`db_manager.py`):

- **DO NOT** catch exceptions and return 0 on query failure
- Let exceptions propagate to caller
- Only return `0` if query succeeds but table is empty
- Log errors at database level using logger

**Analyzer Level** (`analyzer.py`):

- Wrap database calls in try/except
- If exception occurs, return `None` for `data_points` (not `0`)
- This signals error state vs empty table

**GUI Level** (`averages_tab.py`):

- Check if `data_points` is `None`
- If `None`, display error state: `"Fel vid hämtning"` or `"--"` (not `0`)
- If `0`, display `"0"` (table exists but is empty)
- If `int`, display the count normally

### 4. Optional Enhancement: Unique Cities Count

**File**: `analytics/analyzer.py`

Add `unique_cities_in_data` to return dictionary:

- Call `self.db.get_unique_cities_in_data_count()`
- Include in return dict: `'unique_cities_in_data': count`

**File**: `gui/averages_tab.py`

Optionally display unique cities count in metadata section:

- Label: "Unika städer i DB:"
- Value: from `averages.get('unique_cities_in_data')`
- Helps validate data integrity (should match total city count)

### 5. Performance Considerations

**Current Implementation**:

- `COUNT(*)` in SQLite is fast for current scale
- Indexes already exist: `idx_weather_city_timestamp` and `idx_weather_timestamp` (from `schema.sql`)
- Direct query on every GUI refresh is acceptable for current data volume

**Future Optimization (if table grows to 5-10 million rows)**:

If performance becomes an issue, consider:

1. **Caching Strategy**:

   - Cache count in memory (e.g., `self._cached_data_points_count`)
   - Update cache when inserting new rows in `add_weather_data()`
   - Invalidate cache on bulk operations
   - Refresh cache periodically or on-demand

2. **Implementation** (future):
   ```python
   # In DatabaseManager.__init__()
   self._cached_data_points_count = None
   
   # In get_total_data_points_count()
   if self._cached_data_points_count is not None:
       return self._cached_data_points_count
   # ... execute COUNT(*) and cache result
   
   # In add_weather_data()
   if self._cached_data_points_count is not None:
       self._cached_data_points_count += 1
   ```

3. **Note**: Do NOT implement caching in initial version

   - Current scale doesn't require it
   - Keep implementation simple and direct
   - Add caching only if profiling shows it's needed

## Data Flow

```
DatabaseManager.get_total_data_points_count()
    ↓
    SELECT COUNT(*) FROM weather_data
    ↓
    Returns: int (total rows) OR raises exception
    ↓
Analyzer.get_all_cities_averages()
    ↓
    try/except around DB call
    ↓
    Returns: {'data_points': int} OR {'data_points': None} on error
    ↓
AveragesTab.refresh()
    ↓
    Checks if None → shows error state
    Checks if 0 → shows "0" (empty table)
    Checks if int → displays count
```

## Validation

- "Datapunkter" should show total rows in `weather_data` table
- Count should increase as new data is collected
- Count should be independent of number of cities
- Count should be: number of cities × number of timestamps (not × parameters)
- No hardcoded values
- No fallback values masking errors
- Error state clearly distinguished from empty table (None vs 0)
- Optional: Unique cities count validates data integrity

## Performance Notes

- **Current scale**: Direct `COUNT(*)` query is acceptable
- **Indexes**: Already exist (`idx_weather_city_timestamp`, `idx_weather_timestamp`)
- **Future**: If table grows to 5-10 million rows, consider caching count
- **Do NOT** implement caching in initial version - keep it simple