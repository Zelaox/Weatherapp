-- Migration: normalization_profile + seed default winsor 5/95 (parity with prior code literals).

CREATE TABLE IF NOT EXISTS normalization_profile (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_key TEXT NOT NULL UNIQUE,
    mode TEXT NOT NULL CHECK (mode IN ('winsorized_percentile', 'fixed_domain', 'identity')),
    p_low REAL,
    p_high REAL,
    history_days REAL,
    fixed_min REAL,
    fixed_max REAL,
    config_json TEXT
);

INSERT OR IGNORE INTO normalization_profile (id, profile_key, mode, p_low, p_high, history_days, fixed_min, fixed_max)
VALUES (
    1,
    'winsor_p5_p95_default',
    'winsorized_percentile',
    5.0,
    95.0,
    NULL,
    NULL,
    NULL
);
