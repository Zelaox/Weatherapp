"""Dynamic provider registry with auto-discovery."""

import importlib
import inspect
from pathlib import Path
from typing import Dict, Type, Optional, List
from core.sensor_provider import SensorProvider
import logging

logger = logging.getLogger("WeatherApp.core.provider_registry")

# Global registry for decorator-based registration
_PROVIDER_REGISTRY = {}


def sensor_provider(provider_type: str):
    """
    Decorator for auto-registering sensor providers.
    
    Usage:
        @sensor_provider("openaq")
        class OpenAQSensorProvider(SensorProvider):
            ...
    
    Args:
        provider_type: Provider type identifier
    """
    def decorator(cls: Type[SensorProvider]):
        _PROVIDER_REGISTRY[provider_type] = cls
        logger.debug(f"Registered provider '{provider_type}' via decorator")
        return cls
    return decorator


class ProviderRegistry:
    """Dynamic provider registry with auto-discovery - no manual registration."""
    
    def __init__(self, providers_dir: str = "providers"):
        """
        Initialize provider registry with auto-discovery.
        
        Args:
            providers_dir: Directory containing provider modules
        """
        self._providers: Dict[str, Type[SensorProvider]] = {}
        self.providers_dir = Path(providers_dir)
        self._auto_discover()
        # Also load from decorator registry
        self._providers.update(_PROVIDER_REGISTRY)
    
    def _auto_discover(self):
        """Auto-discover providers from providers directory."""
        if not self.providers_dir.exists():
            logger.warning(f"Providers directory not found: {self.providers_dir}")
            return
        
        # Scan for *_sensor.py files
        for file_path in self.providers_dir.glob("*_sensor.py"):
            module_name = file_path.stem
            try:
                # Import module dynamically
                module = importlib.import_module(f"providers.{module_name}")
                
                # Find all SensorProvider subclasses
                for name, obj in inspect.getmembers(module):
                    if (inspect.isclass(obj) and 
                        issubclass(obj, SensorProvider) and 
                        obj != SensorProvider):
                        # Check if decorated with @sensor_provider
                        if hasattr(obj, '_provider_type'):
                            provider_type = obj._provider_type
                            self._providers[provider_type] = obj
                            logger.info(f"Auto-discovered provider '{provider_type}' from {module_name}")
                        else:
                            # Fallback: use provider_type property (requires instantiation)
                            try:
                                # Try to get provider_type without full instantiation
                                # This is a fallback for providers not using decorator
                                if hasattr(obj, 'provider_type'):
                                    # Create temporary instance to get type
                                    # Note: This might fail if __init__ requires args
                                    # In that case, provider should use decorator
                                    try:
                                        instance = obj()
                                        provider_type = instance.provider_type
                                        self._providers[provider_type] = obj
                                        logger.info(f"Auto-discovered provider '{provider_type}' from {module_name} (via property)")
                                    except Exception as e:
                                        logger.warning(f"Could not instantiate {name} to get provider_type: {e}")
                            except Exception as e:
                                logger.debug(f"Could not get provider_type for {name}: {e}")
            except Exception as e:
                # Log error but continue discovery
                logger.warning(f"Failed to load provider from {module_name}: {e}")
    
    def get_provider(self, provider_type: str, **kwargs) -> Optional[SensorProvider]:
        """
        Get provider instance by type.
        
        Args:
            provider_type: Provider type from DB
            **kwargs: Provider initialization args
            
        Returns:
            Provider instance or None if not found
        """
        if provider_type not in self._providers:
            logger.warning(f"Provider type '{provider_type}' not found in registry")
            return None
        
        try:
            provider_class = self._providers[provider_type]
            return provider_class(**kwargs)
        except Exception as e:
            logger.error(f"Failed to instantiate provider '{provider_type}': {e}")
            return None
    
    def get_available_types(self) -> List[str]:
        """
        Get list of registered provider types.
        
        Returns:
            List of provider type strings
        """
        return list(self._providers.keys())
