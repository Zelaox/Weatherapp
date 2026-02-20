"""Custom API sensor provider with security middleware."""

from core.sensor_provider import SensorProvider, SensorReading
from core.provider_registry import sensor_provider
from core.security_middleware import SecurityMiddleware
from typing import Dict, Optional, Any
from datetime import datetime
import aiohttp
import logging

logger = logging.getLogger("WeatherApp.providers.custom_api")


@sensor_provider("custom_api")
class CustomAPISensorProvider(SensorProvider):
    """Custom API sensor provider with security middleware."""
    
    def __init__(self, logger=None, security_middleware: Optional[SecurityMiddleware] = None):
        """
        Initialize custom API provider.
        
        Args:
            logger: Logger instance
            security_middleware: Security middleware instance (created if None)
        """
        self.logger = logger or logging.getLogger("WeatherApp.providers.custom_api")
        self.security = security_middleware or SecurityMiddleware()
    
    @property
    def provider_type(self) -> str:
        return "custom_api"
    
    @property
    def capabilities(self) -> Dict[str, bool]:
        return {
            "supports_bulk_fetch": False,
            "supports_history": False,
            "requires_auth": True,  # May require auth depending on config
            "supports_custom_endpoints": True
        }
    
    async def fetch(self, config: Dict[str, Any]) -> Optional[SensorReading]:
        """
        Fetch from custom API with security validation.
        
        Config structure:
        {
            "endpoint": "https://...",
            "method": "GET",  # Optional, default GET
            "headers": {},  # Optional
            "timeout": 30,  # Optional
            "value_path": "data.value",  # JSON path to value
            "parameter": "pm25",  # Parameter name
            "sensor_id": 123  # Sensor ID
        }
        """
        endpoint = config.get("endpoint")
        if not endpoint:
            raise ValueError("Missing required config: endpoint")
        
        # Security validation
        is_valid, error = self.security.validate_url(endpoint)
        if not is_valid:
            raise ValueError(f"Invalid URL: {error}")
        
        method = config.get("method", "GET").upper()
        headers = config.get("headers", {})
        timeout = config.get("timeout", self.security.TIMEOUT_SECONDS)
        value_path = config.get("value_path", "value")
        parameter = config.get("parameter", "unknown")
        sensor_id = config.get("sensor_id")
        
        if not sensor_id:
            raise ValueError("Missing required config: sensor_id")
        
        # Fetch with timeout and size limits
        try:
            timeout_obj = aiohttp.ClientTimeout(total=timeout)
            async with aiohttp.ClientSession(timeout=timeout_obj) as session:
                async with session.request(method, endpoint, headers=headers) as response:
                    # Check response size
                    content_length = response.headers.get('Content-Length')
                    if content_length:
                        is_valid, error = self.security.validate_response_size(int(content_length))
                        if not is_valid:
                            raise ValueError(f"Response too large: {error}")
                    
                    # Read response with size limit
                    content = await response.read(self.security.MAX_RESPONSE_SIZE + 1)
                    if len(content) > self.security.MAX_RESPONSE_SIZE:
                        raise ValueError(f"Response exceeds max size: {self.security.MAX_RESPONSE_SIZE}")
                    
                    # Parse JSON
                    import json
                    data = json.loads(content.decode('utf-8'))
                    
                    # Extract value using JSON path
                    value = self._extract_value(data, value_path)
                    if value is None:
                        raise ValueError(f"Could not extract value from path: {value_path}")
                    
                    return SensorReading(
                        sensor_id=sensor_id,
                        value=float(value),
                        parameter=parameter,
                        timestamp=datetime.now(),
                        metadata={"endpoint": endpoint, "status_code": response.status}
                    )
        except aiohttp.ClientError as e:
            raise ValueError(f"HTTP error: {e}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON response: {e}")
        except Exception as e:
            raise ValueError(f"Fetch error: {e}")
    
    def _extract_value(self, data: Any, path: str) -> Optional[float]:
        """
        Extract value from JSON using dot-notation path.
        
        Args:
            data: JSON data
            path: Dot-notation path (e.g., "data.value")
            
        Returns:
            Extracted value or None
        """
        parts = path.split('.')
        current = data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    index = int(part)
                    current = current[index] if 0 <= index < len(current) else None
                except (ValueError, IndexError):
                    return None
            else:
                return None
            if current is None:
                return None
        return current if isinstance(current, (int, float)) else None
    
    def validate_config(self, config: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate custom API config.
        
        Args:
            config: Config to validate
            
        Returns:
            (is_valid, error_message)
        """
        required = ["endpoint", "sensor_id", "parameter"]
        for key in required:
            if key not in config:
                return False, f"Missing required key: {key}"
        
        # Validate endpoint URL
        endpoint = config.get("endpoint")
        is_valid, error = self.security.validate_url(endpoint)
        if not is_valid:
            return False, f"Invalid endpoint URL: {error}"
        
        return True, None
