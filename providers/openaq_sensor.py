"""OpenAQ sensor provider implementing SensorProvider interface."""

from core.sensor_provider import SensorProvider, SensorReading
from core.provider_registry import sensor_provider
from typing import Dict, Optional, Any
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
import logging

logger = logging.getLogger("WeatherApp.providers.openaq_sensor")

# CET timezone
CET = ZoneInfo("Europe/Stockholm")


@sensor_provider("openaq")
class OpenAQSensorProvider(SensorProvider):
    """OpenAQ sensor provider - config-driven."""
    
    BASE_URL = "https://api.openaq.org/v3"
    
    def __init__(self, logger=None, api_key: Optional[str] = None):
        """
        Initialize OpenAQ sensor provider.
        
        Args:
            logger: Logger instance
            api_key: Optional API key (can be in config)
        """
        self.logger = logger or logging.getLogger("WeatherApp.providers.openaq_sensor")
        self.default_api_key = api_key
    
    @property
    def provider_type(self) -> str:
        return "openaq"
    
    @property
    def capabilities(self) -> Dict[str, bool]:
        return {
            "supports_bulk_fetch": False,
            "supports_history": True,
            "requires_auth": True,  # API key required
            "supports_custom_endpoints": False
        }
    
    async def fetch(self, config: Dict[str, Any]) -> Optional[SensorReading]:
        """
        Fetch from OpenAQ using config.
        
        Config structure:
        {
            "api_key": "...",
            "sensor_id": 12345,
            "parameter": "pm25",
            "endpoint": "https://api.openaq.org/v3/sensors/{sensor_id}"  # Optional
        }
        """
        import aiohttp
        
        # Read all from config - no hardcoded endpoints
        api_key = config.get("api_key") or self.default_api_key
        if not api_key:
            raise ValueError("Missing required config: api_key")
        
        sensor_id = config.get("sensor_id")
        if not sensor_id:
            raise ValueError("Missing required config: sensor_id")
        
        parameter = config.get("parameter")
        if not parameter:
            raise ValueError("Missing required config: parameter")
        
        # Use endpoint from config or default
        endpoint_template = config.get("endpoint", f"{self.BASE_URL}/sensors/{{sensor_id}}")
        endpoint = endpoint_template.format(sensor_id=sensor_id)
        
        headers = {
            "X-API-Key": api_key
        }
        
        try:
            # Fetch using aiohttp for async support
            async with aiohttp.ClientSession() as session:
                async with session.get(endpoint, headers=headers) as response:
                    if response.status != 200:
                        raise ValueError(f"API returned status {response.status}")
                    
                    data = await response.json()
                    
                    # Extract value from response
                    # OpenAQ v3 sensor response structure
                    value = None
                    timestamp = None
                    
                    if isinstance(data, dict):
                        # Try different possible response structures
                        if "results" in data and isinstance(data["results"], list) and len(data["results"]) > 0:
                            result = data["results"][0]
                            value = result.get("value")
                            if "date" in result:
                                timestamp_str = result["date"].get("utc") or result["date"].get("local")
                                if timestamp_str:
                                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                        elif "value" in data:
                            value = data["value"]
                            if "date" in data:
                                timestamp_str = data["date"].get("utc") or data["date"].get("local")
                                if timestamp_str:
                                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    
                    if value is None:
                        raise ValueError("Could not extract value from API response")
                    
                    if timestamp is None:
                        timestamp = datetime.now(CET)
                    
                    return SensorReading(
                        sensor_id=sensor_id,
                        value=float(value),
                        parameter=parameter,
                        timestamp=timestamp,
                        metadata={"endpoint": endpoint, "status_code": response.status}
                    )
        except aiohttp.ClientError as e:
            raise ValueError(f"HTTP error: {e}")
        except Exception as e:
            raise ValueError(f"Fetch error: {e}")
    
    def validate_config(self, config: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate OpenAQ config.
        
        Args:
            config: Config to validate
            
        Returns:
            (is_valid, error_message)
        """
        required = ["sensor_id", "parameter"]
        for key in required:
            if key not in config:
                return False, f"Missing required key: {key}"
        
        # API key can be in config or provided at init
        if not config.get("api_key") and not self.default_api_key:
            return False, "Missing required config: api_key"
        
        return True, None
