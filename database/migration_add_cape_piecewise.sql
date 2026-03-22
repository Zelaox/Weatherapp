-- CAPE piecewise segments for storm_risk factor and storm panel display suffixes.
-- Parity with prior hardcoded thresholds 100, 1000, 2500 and factors 0.3, 1.0, 1.5, 2.0.

CREATE TABLE IF NOT EXISTS cape_piecewise_segment (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sort_order INTEGER NOT NULL UNIQUE,
    lower_bound_jkg REAL NOT NULL,
    upper_bound_jkg REAL,
    storm_risk_factor REAL NOT NULL,
    display_suffix_sv TEXT NOT NULL DEFAULT ''
);

INSERT OR IGNORE INTO cape_piecewise_segment (id, sort_order, lower_bound_jkg, upper_bound_jkg, storm_risk_factor, display_suffix_sv) VALUES
    (1, 0, 0.0, 100.0, 0.3, ' (svag)'),
    (2, 1, 100.0, 1000.0, 1.0, ' (måttlig)'),
    (3, 2, 1000.0, 2500.0, 1.5, ' (stark)'),
    (4, 3, 2500.0, NULL, 2.0, ' (extrem)');
