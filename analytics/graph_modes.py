"""Mode architecture for graph generation."""

import calendar
from abc import ABC, abstractmethod
from datetime import datetime, date
from zoneinfo import ZoneInfo
from typing import Dict, Optional
import pandas as pd

# CET timezone for all operations
CET = ZoneInfo("Europe/Stockholm")


class BaseMode(ABC):
    """Abstract base class for graph modes."""
    
    @abstractmethod
    def transform(self, df: pd.DataFrame, selected_date: Optional[date] = None) -> pd.DataFrame:
        """
        Transform dataframe with grouping logic.
        
        Args:
            df: DataFrame with timestamp column
            selected_date: Optional date for modes that require date selection (e.g. DailyMode)
            
        Returns:
            Transformed DataFrame (with 'group' column for historical modes, or hour index for DailyMode)
        """
        raise NotImplementedError
    
    @abstractmethod
    def legend_label(self, group_key) -> str:
        """
        Generate legend label for a group key.
        
        Args:
            group_key: Group key from transform()
            
        Returns:
            Legend label string
        """
        raise NotImplementedError
    
    @abstractmethod
    def title(self, df: pd.DataFrame, city_name: str) -> str:
        """
        Generate title for the graph.
        
        Args:
            df: Transformed DataFrame
            city_name: City name
            
        Returns:
            Title string
        """
        raise NotImplementedError
    
    @abstractmethod
    def get_name(self) -> str:
        """
        Return mode name for menu.
        
        Returns:
            Mode name string
        """
        raise NotImplementedError
    
    def needs_date_selection(self) -> bool:
        """
        Return True if mode requires date selection (e.g. DailyMode).
        
        Returns:
            True if date selection is required, False otherwise
        """
        return False
    
    def _ensure_timezone_aware(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Ensure timestamp column is timezone-aware (Europe/Stockholm).
        
        Args:
            df: DataFrame with timestamp column
            
        Returns:
            DataFrame with timezone-aware timestamp
        """
        if df.empty or 'timestamp' not in df.columns:
            return df
        
        # Convert to datetime if needed
        if not pd.api.types.is_datetime64_any_dtype(df['timestamp']):
            # Use errors='coerce' to handle problematic timestamps gracefully
            # This handles timezone-aware strings like "2026-02-19 18:15:00+01:00"
            df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce', utc=False)
            
            # Drop rows where timestamp parsing failed (NaT)
            if df['timestamp'].isna().any():
                num_failed = df['timestamp'].isna().sum()
                # Log warning but don't raise - let caller handle empty DataFrame
                import logging
                logger = logging.getLogger("WeatherApp.analytics.graph_modes")
                logger.warning(f"Kunde inte parsa {num_failed} timestamp(s), hoppar över dessa rader")
                df = df[df['timestamp'].notna()]
        
        if df.empty:
            return df
        
        # Ensure timezone-aware
        if df['timestamp'].dt.tz is None:
            # Naive datetime - localize to CET
            df['timestamp'] = df['timestamp'].dt.tz_localize(CET)
        elif df['timestamp'].dt.tz != CET:
            # Different timezone - convert to CET
            df['timestamp'] = df['timestamp'].dt.tz_convert(CET)
        
        return df


class DailyMode(BaseMode):
    """Mode that shows exact one day with hour-based X-axis (0-23)."""
    
    def transform(self, df: pd.DataFrame, selected_date: Optional[date] = None) -> pd.DataFrame:
        """
        Filter exact one day and aggregate per hour.
        
        Args:
            df: DataFrame with timestamp column
            selected_date: Date for the specific day (REQUIRED for DailyMode)
            
        Returns:
            Aggregated DataFrame with hour as index (0-23)
        """
        if selected_date is None:
            raise ValueError("DailyMode requires selected_date parameter")
        
        if df.empty or 'timestamp' not in df.columns:
            return pd.DataFrame()
        
        df = self._ensure_timezone_aware(df.copy())
        
        # Filter exact one day
        df_day = df[df["timestamp"].dt.date == selected_date]
        
        # If no data for this day, return empty DataFrame (NO fallback)
        if df_day.empty:
            return pd.DataFrame()
        
        # Create hour column
        df_day["hour"] = df_day["timestamp"].dt.hour
        
        # Aggregate per hour (NOT smoothing, just aggregation)
        # This handles multiple datapoints per hour
        hourly = df_day.groupby("hour").mean(numeric_only=True)
        
        # Return aggregated DataFrame with hour as index (0-23)
        return hourly
    
    def legend_label(self, group_key) -> str:
        """Generate legend label (not used in DailyMode, but kept for interface compliance)."""
        return f"{group_key}:00"
    
    def title(self, df: pd.DataFrame, city_name: str) -> str:
        """
        Generate title: '{city_name} – {date}'.
        
        Note: selected_date should be passed separately, but for compatibility
        we try to extract from df if it has hour index.
        """
        # For DailyMode, we use the selected_date that was used in transform()
        # Since we can't pass it here, we'll use a generic format
        # The actual date will be set in GraphGenerator
        return f"{city_name} – Daily"
    
    def get_name(self) -> str:
        """Return mode name."""
        return "Daily"
    
    def needs_date_selection(self) -> bool:
        """Return True - DailyMode requires date selection."""
        return True


class WeeklyMode(BaseMode):
    """Mode that groups data by day of week."""
    
    def transform(self, df: pd.DataFrame, selected_date: Optional[date] = None) -> pd.DataFrame:
        """Group by day of week."""
        if df.empty or 'timestamp' not in df.columns:
            return df
        
        df = self._ensure_timezone_aware(df.copy())
        df["group"] = df["timestamp"].dt.day_name()
        return df
    
    def legend_label(self, group_key) -> str:
        """Generate legend label: day name."""
        return str(group_key)
    
    def title(self, df: pd.DataFrame, city_name: str) -> str:
        """Generate title: '{city_name} – Vecka {week} ({year})'."""
        if df.empty or 'timestamp' not in df.columns:
            return f"{city_name} – Weekly"
        
        first_ts = df['timestamp'].min()
        if pd.isna(first_ts):
            return f"{city_name} – Weekly"
        
        week = first_ts.isocalendar()[1]
        year = first_ts.year
        return f"{city_name} – Vecka {week} ({year})"
    
    def get_name(self) -> str:
        """Return mode name."""
        return "Weekly"


class MonthlyMode(BaseMode):
    """Mode that groups data by week of month."""
    
    def transform(self, df: pd.DataFrame, selected_date: Optional[date] = None) -> pd.DataFrame:
        """Group by week of month (1-4 or 5)."""
        if df.empty or 'timestamp' not in df.columns:
            return df
        
        df = self._ensure_timezone_aware(df.copy())
        df["group"] = (df["timestamp"].dt.day - 1) // 7 + 1
        return df
    
    def legend_label(self, group_key) -> str:
        """Generate legend label: 'Vecka {key}'."""
        return f"Vecka {group_key}"
    
    def title(self, df: pd.DataFrame, city_name: str) -> str:
        """Generate title: '{city_name} – {month} {year}'."""
        if df.empty or 'timestamp' not in df.columns:
            return f"{city_name} – Monthly"
        
        first_ts = df['timestamp'].min()
        if pd.isna(first_ts):
            return f"{city_name} – Monthly"
        
        month_name = first_ts.strftime("%B")
        year = first_ts.year
        return f"{city_name} – {month_name} {year}"
    
    def get_name(self) -> str:
        """Return mode name."""
        return "Monthly"


class YearlyMode(BaseMode):
    """Mode that groups data by month of year."""
    
    def transform(self, df: pd.DataFrame, selected_date: Optional[date] = None) -> pd.DataFrame:
        """Group by month of year."""
        if df.empty or 'timestamp' not in df.columns:
            return df
        
        df = self._ensure_timezone_aware(df.copy())
        df["group"] = df["timestamp"].dt.month
        return df
    
    def legend_label(self, group_key) -> str:
        """Generate legend label: month name."""
        return calendar.month_name[group_key]
    
    def title(self, df: pd.DataFrame, city_name: str) -> str:
        """Generate title: '{city_name} – År {year}'."""
        if df.empty or 'timestamp' not in df.columns:
            return f"{city_name} – Yearly"
        
        first_ts = df['timestamp'].min()
        if pd.isna(first_ts):
            return f"{city_name} – Yearly"
        
        year = first_ts.year
        return f"{city_name} – År {year}"
    
    def get_name(self) -> str:
        """Return mode name."""
        return "Yearly"


# Mode registration - order determines menu order
MODES: Dict[str, type] = {
    "Daily": DailyMode,
    "Weekly": WeeklyMode,
    "Monthly": MonthlyMode,
    "Yearly": YearlyMode,
}
