"""Geographic distance utilities (e.g. Haversine). No hardcoded coordinates."""

import math
from typing import Optional

# Earth radius in km (WGS84 approximate)
EARTH_RADIUS_KM = 6371.0


def haversine_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    radius_km: Optional[float] = None,
) -> float:
    """
    Distance between two points on Earth (Haversine formula).

    Args:
        lat1, lon1: First point (degrees).
        lat2, lon2: Second point (degrees).
        radius_km: Earth radius in km (default EARTH_RADIUS_KM).

    Returns:
        Distance in kilometres.
    """
    R = radius_km if radius_km is not None else EARTH_RADIUS_KM
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))
