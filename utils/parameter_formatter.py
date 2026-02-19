"""Parameter name formatter for human-readable display."""

from typing import Optional


def format_parameter_name(param_name: Optional[str]) -> str:
    """
    Format parameter name to human-readable display format.
    
    Args:
        param_name: Parameter name from API (e.g., "no2", "pm25", "pm2.5")
                    Can be None or empty string
        
    Returns:
        Formatted name (e.g., "NO₂", "PM₂.₅", "PM₁₀")
        Returns "Okänd" if param_name is None or empty
    """
    if not param_name:
        return "Okänd"
    
    # Convert to lowercase for normalization
    param_lower = str(param_name).lower().strip()
    
    # Dynamic mapping based on common patterns
    # No hardcoded IDs - only string-based matching
    if param_lower in ["pm2.5", "pm25", "pm2_5"]:
        return "PM₂.₅"
    elif param_lower == "pm10":
        return "PM₁₀"
    elif param_lower == "no2":
        return "NO₂"
    elif param_lower == "o3":
        return "O₃"
    elif param_lower == "co":
        return "CO"
    elif param_lower == "so2":
        return "SO₂"
    else:
        # For unknown parameters, capitalize and return as-is
        # Never show "Parameter_X" - always use actual name
        return param_name.upper()
