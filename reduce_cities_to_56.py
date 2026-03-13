"""Reduce cities to 56, keeping Trollhättan, Karlstad, Jönköping, Göteborg, Uddevalla."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from database.db_manager import DatabaseManager

def main():
    db = DatabaseManager()
    cities = db.get_all_cities()
    
    print(f"Antal städer nu: {len(cities)}")
    
    # Städer som ska vara kvar
    keep_names = ['Trollhättan', 'Karlstad', 'Jönköping', 'Göteborg', 'Uddevalla']
    
    # Hitta ID:n för städerna som ska vara kvar
    keep_ids = set()
    for city in cities:
        if city['name'] in keep_names:
            keep_ids.add(city['id'])
            print(f"Behåller: {city['id']}: {city['name']}")
    
    # Ta bort alla andra städer tills vi har 56 städer kvar
    # Vi behöver behålla 56 städer totalt, så vi tar bort (totalt - 56) städer
    # Men vi måste se till att de 5 städerna alltid är kvar
    
    target_count = 56
    current_count = len(cities)
    to_remove = current_count - target_count
    
    if to_remove <= 0:
        print(f"\nRedan {current_count} städer eller färre. Inga städer att ta bort.")
        return
    
    print(f"\nMåste ta bort {to_remove} städer för att få {target_count} städer.")
    
    # Sortera städer: de som ska behållas först, sedan resten
    cities_to_keep = [c for c in cities if c['id'] in keep_ids]
    cities_to_remove = [c for c in cities if c['id'] not in keep_ids]
    
    # Ta bort städer tills vi har 56 kvar (inklusive de 5 som måste vara kvar)
    # Vi behöver behålla 56 totalt, så vi tar bort (len(cities_to_remove) - (56 - len(keep_ids))) städer
    remaining_slots = target_count - len(keep_ids)
    
    if remaining_slots < 0:
        print(f"\nFEL: Kan inte ha {target_count} städer när {len(keep_ids)} måste vara kvar!")
        return
    
    # Behåll de första (remaining_slots) städerna från cities_to_remove också
    cities_to_keep.extend(cities_to_remove[:remaining_slots])
    cities_to_remove = cities_to_remove[remaining_slots:]
    
    print(f"\nBehåller {len(cities_to_keep)} städer (inklusive {len(keep_ids)} obligatoriska)")
    print(f"Tar bort {len(cities_to_remove)} städer:")
    
    for city in cities_to_remove:
        print(f"  - {city['id']}: {city['name']}")
    
    # Ta bort städerna (automatiskt, ingen bekräftelse behövs)
    removed_count = 0
    for city in cities_to_remove:
        try:
            if db.delete_city(city['id']):
                print(f"[OK] Tog bort: {city['name']} (ID {city['id']})")
                removed_count += 1
            else:
                print(f"[FAIL] Kunde inte ta bort: {city['name']} (ID {city['id']})")
        except Exception as e:
            print(f"[ERROR] Fel vid borttagning av {city['name']} (ID {city['id']}): {e}")
    
    # Verifiera
    remaining_cities = db.get_all_cities()
    print(f"\n{'='*60}")
    print(f"Klart! Antal städer nu: {len(remaining_cities)}")
    print(f"Tog bort {removed_count} städer")
    
    # Verifiera att de obligatoriska städerna fortfarande finns
    remaining_names = {c['name'] for c in remaining_cities}
    missing = [name for name in keep_names if name not in remaining_names]
    if missing:
        print(f"\nVARNING: Följande obligatoriska städer saknas: {missing}")
    else:
        print(f"\n[OK] Alla obligatoriska städer finns kvar: {keep_names}")

if __name__ == "__main__":
    main()
