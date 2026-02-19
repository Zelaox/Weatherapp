"""Utility for loading and managing Swedish cities."""

from typing import List, Dict, Set


# List of popular Swedish cities with coordinates
SWEDISH_CITIES = [
    {"name": "Stockholm", "lat": 59.3293, "lon": 18.0686},
    {"name": "Göteborg", "lat": 57.7089, "lon": 11.9746},
    {"name": "Malmö", "lat": 55.6059, "lon": 13.0007},
    {"name": "Uppsala", "lat": 59.8586, "lon": 17.6389},
    {"name": "Västerås", "lat": 59.6099, "lon": 16.5448},
    {"name": "Örebro", "lat": 59.2741, "lon": 15.2066},
    {"name": "Linköping", "lat": 58.4108, "lon": 15.6214},
    {"name": "Helsingborg", "lat": 56.0467, "lon": 12.6944},
    {"name": "Jönköping", "lat": 57.7815, "lon": 14.1562},
    {"name": "Norrköping", "lat": 58.5877, "lon": 16.1924},
    {"name": "Lund", "lat": 55.7047, "lon": 13.1910},
    {"name": "Umeå", "lat": 63.8258, "lon": 20.2630},
    {"name": "Gävle", "lat": 60.6749, "lon": 17.1413},
    {"name": "Borås", "lat": 57.7210, "lon": 12.9401},
    {"name": "Eskilstuna", "lat": 59.3666, "lon": 16.5077},
    {"name": "Södertälje", "lat": 59.1955, "lon": 17.6252},
    {"name": "Karlstad", "lat": 59.3793, "lon": 13.5036},
    {"name": "Halmstad", "lat": 56.6744, "lon": 12.8578},
    {"name": "Växjö", "lat": 56.8777, "lon": 14.8094},
    {"name": "Sundsvall", "lat": 62.3908, "lon": 17.3069},
    {"name": "Trollhättan", "lat": 58.2833, "lon": 12.2900},
    {"name": "Luleå", "lat": 65.5842, "lon": 22.1547},
    {"name": "Kalmar", "lat": 56.6634, "lon": 16.3567},
    {"name": "Falun", "lat": 60.6036, "lon": 15.6259},
    {"name": "Kristianstad", "lat": 56.0294, "lon": 14.1567},
    {"name": "Skellefteå", "lat": 64.7507, "lon": 20.9528},
    {"name": "Hudiksvall", "lat": 61.7290, "lon": 17.1034},
    {"name": "Östersund", "lat": 63.1792, "lon": 14.6357},
    {"name": "Borlänge", "lat": 60.4858, "lon": 15.4371},
    {"name": "Mölndal", "lat": 57.6553, "lon": 12.0138},
    {"name": "Piteå", "lat": 65.3172, "lon": 21.4794},
    {"name": "Ängelholm", "lat": 56.2428, "lon": 12.8622},
    {"name": "Karlskrona", "lat": 56.1616, "lon": 15.5866},
    {"name": "Landskrona", "lat": 55.8708, "lon": 12.8301},
    {"name": "Örnsköldsvik", "lat": 63.2909, "lon": 18.7153},
    {"name": "Nyköping", "lat": 58.7530, "lon": 17.0079},
    {"name": "Härnösand", "lat": 62.6323, "lon": 17.9379},
    {"name": "Varberg", "lat": 57.1056, "lon": 12.2508},
    {"name": "Uddevalla", "lat": 58.3478, "lon": 11.9424},
    {"name": "Trelleborg", "lat": 55.3751, "lon": 13.1569},
]


def get_cities_to_add(current_cities: List[Dict], multiplier: int = 6) -> List[Dict]:
    """
    Get list of cities to add based on current city count.
    
    Args:
        current_cities: List of current city dicts with 'name' key
        multiplier: How many cities to add per existing city (default 6)
        
    Returns:
        List of city dicts to add (with 'name', 'lat', 'lon')
    """
    current_count = len(current_cities)
    
    # If 0 cities, add multiplier cities. Otherwise add multiplier * current_count
    if current_count == 0:
        to_add_count = multiplier
    else:
        to_add_count = multiplier * current_count
    
    # Get existing city names (case-insensitive)
    existing_names = {city['name'].lower() for city in current_cities}
    
    # Filter out cities that already exist
    available_cities = [
        city for city in SWEDISH_CITIES
        if city['name'].lower() not in existing_names
    ]
    
    # Return first N cities from available list
    return available_cities[:to_add_count]


def get_city_by_name(name: str) -> Dict:
    """
    Get city data by name.
    
    Args:
        name: City name
        
    Returns:
        City dict with 'name', 'lat', 'lon' or None if not found
    """
    name_lower = name.lower()
    for city in SWEDISH_CITIES:
        if city['name'].lower() == name_lower:
            return city
    return None
