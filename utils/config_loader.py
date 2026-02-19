"""Configuration loader for dynamic config.json management."""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
import logging

try:
    from dotenv import load_dotenv
    # Load .env file at module level
    load_dotenv()
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False
    logger_temp = logging.getLogger("WeatherApp.config")
    logger_temp.warning("python-dotenv not installed, .env file will not be loaded")

# Get module logger
logger = logging.getLogger("WeatherApp.config")


class ConfigLoader:
    """Loads and manages configuration from config.json."""
    
    DEFAULT_CONFIG = {
        "api_keys": {
            "openweather": None,  # No hardcoded key - read from .env or config.json
            "openaq": None        # No hardcoded key - read from .env or config.json
        },
        "settings": {
            "auto_update_interval_minutes": 10,
            "data_retention_days": 90,
            "default_cities": []
        }
    }
    
    def __init__(self, config_path: str = "config.json"):
        """
        Initialize config loader.
        
        Args:
            config_path: Path to config.json file
        """
        self.config_path = Path(config_path)
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """Load config from file or create default."""
        if self.config_path.exists():
            logger.info(f"Laddar konfiguration från {self.config_path}")
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                logger.debug("Konfigurationsfil läst")
                # Merge with defaults to ensure all keys exist
                merged = self.DEFAULT_CONFIG.copy()
                merged.update(config)
                # Deep merge for nested dicts
                if "api_keys" in config:
                    merged["api_keys"].update(config["api_keys"])
                if "settings" in config:
                    merged["settings"].update(config["settings"])
                logger.info("Konfiguration laddad")
                return merged
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Fel vid läsning av konfiguration: {e}. Använder standardvärden.")
                return self._create_default_config()
        else:
            logger.info(f"Konfigurationsfil {self.config_path} saknas, skapar standardkonfiguration")
            return self._create_default_config()
    
    def _create_default_config(self) -> Dict[str, Any]:
        """Create default config file."""
        try:
            logger.info(f"Skapar standardkonfigurationsfil: {self.config_path}")
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.DEFAULT_CONFIG, f, indent=4)
            logger.info(f"Standardkonfigurationsfil skapad: {self.config_path}")
        except IOError as e:
            logger.error(f"Kunde inte skapa konfigurationsfil: {e}")
        
        return self.DEFAULT_CONFIG.copy()
    
    def get_api_key(self, provider: str) -> Optional[str]:
        """
        Get API key for a provider.
        
        Priority order:
        1. Environment variable (.env file) - HIGHEST PRIORITY
        2. config.json file - FALLBACK
        3. None - NO HARDCODED DEFAULTS
        
        Args:
            provider: Provider name ('openweather', 'openaq')
            
        Returns:
            API key or None if not found
        """
        # 1. Try environment variable first (from .env file)
        # Support both uppercase and lowercase variants
        env_key_upper = os.getenv(f"{provider.upper()}_API_KEY")
        env_key_lower = os.getenv(f"{provider.lower()}_api_key")
        env_key = env_key_upper or env_key_lower
        
        if env_key:
            logger.debug(f"API-nyckel för {provider} läst från miljövariabel")
            return env_key
        
        # 2. Fallback to config.json
        key = self.config.get("api_keys", {}).get(provider)
        if key:
            logger.debug(f"API-nyckel för {provider} läst från config.json")
            return key
        
        # 3. No key found
        logger.warning(f"API-nyckel för {provider} saknas (kontrollera .env eller config.json)")
        return None
    
    def get_setting(self, key: str, default: Any = None) -> Any:
        """
        Get a setting value.
        
        Args:
            key: Setting key
            default: Default value if not found
            
        Returns:
            Setting value or default
        """
        return self.config.get("settings", {}).get(key, default)
    
    def get_all_config(self) -> Dict[str, Any]:
        """Get entire configuration."""
        return self.config.copy()
    
    def update_config(self, updates: Dict[str, Any]):
        """
        Update configuration and save to file.
        
        Args:
            updates: Dictionary of updates to merge
        """
        self.config.update(updates)
        if "api_keys" in updates:
            self.config["api_keys"].update(updates["api_keys"])
        if "settings" in updates:
            self.config["settings"].update(updates["settings"])
        
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4)
        except IOError as e:
            print(f"Error saving config: {e}")
