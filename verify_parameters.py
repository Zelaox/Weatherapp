"""Verify that parameters are in the database."""

import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from database.db_manager import DatabaseManager

db = DatabaseManager()
conn = db.get_connection()
cursor = conn.cursor()

cursor.execute("SELECT parameter_name, display_name, category FROM parameter_registry ORDER BY category, parameter_name")
rows = cursor.fetchall()

print(f"Total parameters: {len(rows)}")
print("\nAir Quality Parameters:")
for r in rows:
    if r['category'] == 'air_quality':
        print(f"  - {r['parameter_name']}: {r['display_name']}")

print("\nWeather Parameters:")
for r in rows:
    if r['category'] == 'weather':
        print(f"  - {r['parameter_name']}: {r['display_name']}")
