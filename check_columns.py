from database.db_manager import DatabaseManager

db = DatabaseManager()
conn = db.get_connection()
cursor = conn.cursor()
cursor.execute('PRAGMA table_info(weather_data)')
cols = [r[1] for r in cursor.fetchall()]
print('Kolumner i weather_data:')
for c in cols:
    print(f'  - {c}')
print(f'\nmeasurement_timestamp finns: {"measurement_timestamp" in cols}')
