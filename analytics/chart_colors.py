"""Chart style mapper for dynamic charts."""

from typing import Dict, Optional
import logging
from database.db_manager import DatabaseManager

logger = logging.getLogger("WeatherApp.analytics.chart_colors")


class ChartStyleMapper:
    """Maps chart categories to styles (colors, line widths, etc.)."""
    
    def __init__(self, db: DatabaseManager):
        self.db = db
        self._style_cache = {}
        self._load_styles()
    
    def _load_styles(self):
        """Load chart styles from database."""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            # Check if chart_category_styles table exists
            cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='chart_category_styles'
            """)
            
            if cursor.fetchone():
                cursor.execute("""
                    SELECT category, line_color, fill_color, line_width
                    FROM chart_category_styles
                """)
                
                for row in cursor.fetchall():
                    self._style_cache[row['category']] = {
                        'line_color': row['line_color'],
                        'fill_color': row['fill_color'],
                        'line_width': row['line_width'] or 2.0
                    }
            else:
                # Use default styles if table doesn't exist
                self._style_cache = {
                    'air_quality': {
                        'line_color': '#ff6b6b',
                        'fill_color': '#ff6b6b80',
                        'line_width': 2.0
                    },
                    'weather': {
                        'line_color': '#4ecdc4',
                        'fill_color': '#4ecdc480',
                        'line_width': 2.0
                    }
                }
        except Exception as e:
            logger.warning(f"Error loading chart category styles: {e}")
            # Use default styles on error
            self._style_cache = {
                'air_quality': {
                    'line_color': '#ff6b6b',
                    'fill_color': '#ff6b6b80',
                    'line_width': 2.0
                },
                'weather': {
                    'line_color': '#4ecdc4',
                    'fill_color': '#4ecdc480',
                    'line_width': 2.0
                }
            }
    
    def get_style(self, category: str) -> Dict:
        """Get style for a category."""
        return self._style_cache.get(category, {
            'line_color': '#888888',
            'fill_color': '#88888880',
            'line_width': 2.0
        })
