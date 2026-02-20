"""Abstract base class for sensor providers."""

from abc import ABC, abstractmethod
from typing import Dict, Optional, Any
from dataclasses import dataclass
from datetime import datetime


@dataclass
class SensorReading:
    """Standardized sensor reading."""
    sensor_id: int
    value: float
    parameter: str
    timestamp: datetime
    metadata: Optional[Dict[str, Any]] = None


class SensorProvider(ABC):
    """Abstract base class for sensor providers."""
    
    @property
    @abstractmethod
    def provider_type(self) -> str:
        """
        Provider type identifier (e.g., 'openaq', 'custom_api').
        
        Returns:
            Provider type string
        """
        pass
    
    @property
    @abstractmethod
    def capabilities(self) -> Dict[str, bool]:
        """
        Provider capabilities.
        
        Returns:
            Dict with keys like:
            - supports_bulk_fetch: bool
            - supports_history: bool
            - requires_auth: bool
            - supports_custom_endpoints: bool
        """
        pass
    
    @abstractmethod
    async def fetch(self, config: Dict[str, Any]) -> Optional[SensorReading]:
        """
        Fetch sensor reading from provider.
        
        Args:
            config: Provider-specific config from config_json
            
        Returns:
            SensorReading or None if failed
        """
        pass
    
    @abstractmethod
    def validate_config(self, config: Dict[str, Any]) -> tuple[bool, Optional[str]]:
        """
        Validate provider config.
        
        Args:
            config: Config to validate
            
        Returns:
            (is_valid, error_message)
        """
        pass
