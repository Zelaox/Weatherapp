-- Graph legend visibility: 0 = off (default), 1 = on. No hardcoded legend in code.

INSERT OR IGNORE INTO calibration_parameters (key, value, unit, description, source) VALUES
    ('graph_show_legend', 0, 'boolean', 'Show legend in mode-based graphs when multiple groups (0=off, 1=on)', 'migration_add_graph_legend_setting.sql');
