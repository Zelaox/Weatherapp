"""Graph generator for weather data visualization."""

import os
import re
import math
from datetime import datetime, date
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import List, Dict, Optional
import logging

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import pandas as pd

from database.db_manager import DatabaseManager
from analytics.graph_modes import BaseMode

# CET timezone for all operations
CET = ZoneInfo("Europe/Stockholm")

# Get module logger
logger = logging.getLogger("WeatherApp.analytics.graph_generator")


class GraphGenerator:
    """Generate graphs from weather data following strict design principles."""
    
    # Parameters to plot (in order)
    PARAMETERS = ['pm25', 'pm10', 'no2', 'o3', 'temperature', 'wind_speed', 'humidity']
    
    def __init__(self, db_manager: DatabaseManager, output_dir: str = "output"):
        """
        Initialize graph generator.
        
        Args:
            db_manager: Database manager instance
            output_dir: Output directory for graphs
        """
        self.db = db_manager
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"GraphGenerator initialiserad med output_dir: {self.output_dir}")
    
    def _sanitize_filename(self, name: str) -> str:
        """
        Sanitize filename by replacing invalid characters.
        
        Args:
            name: Original name
            
        Returns:
            Sanitized name
        """
        # Replace invalid characters: / < > : " | ? * with underscore
        sanitized = re.sub(r'[<>:"|?*/]', '_', name)
        return sanitized
    
    def _get_export_timestamp(self) -> str:
        """
        Get current timestamp for export filename (CET timezone).
        
        Returns:
            Timestamp string in format YYYYMMDD_HHMMSS
        """
        return datetime.now(CET).strftime("%Y%m%d_%H%M%S")
    
    def _get_available_parameters(self, data: List[Dict]) -> List[str]:
        """
        Get list of parameters that have at least one non-None value.
        
        Args:
            data: List of weather data dictionaries
            
        Returns:
            List of parameter names with data
        """
        if not data:
            return []
        
        available = []
        for param in self.PARAMETERS:
            # Check if parameter exists in data and has at least one non-None value
            for row in data:
                if param in row and row[param] is not None:
                    available.append(param)
                    break
        
        return available
    
    def _calculate_grid_layout(self, num_params: int) -> tuple:
        """
        Calculate grid layout dimensions.
        
        Args:
            num_params: Number of parameters to plot
            
        Returns:
            Tuple of (rows, cols)
        """
        if num_params == 0:
            return (1, 1)
        
        cols = math.ceil(math.sqrt(num_params))
        rows = math.ceil(num_params / cols)
        return (rows, cols)
    
    def _convert_timestamp(self, ts) -> datetime:
        """
        Convert timestamp to datetime if needed.
        
        Args:
            ts: Timestamp (string, datetime, or other)
            
        Returns:
            datetime object
            
        Raises:
            ValueError: If timestamp cannot be parsed
        """
        if isinstance(ts, datetime):
            return ts
        elif isinstance(ts, str):
            try:
                # Use pandas parser directly - it handles timezone offsets automatically
                # This is more robust than strptime which doesn't handle timezone offsets well
                # Use errors='coerce' to return NaT for unparseable strings, then check
                parsed = pd.to_datetime(ts, errors='coerce')
                
                # Check if parsing failed
                if pd.isna(parsed):
                    logger.warning(f"Kunde inte parsa timestamp: {ts}")
                    raise ValueError(f"Invalid timestamp format: {ts}")
                
                # Convert to Python datetime if it's a pandas Timestamp
                if isinstance(parsed, pd.Timestamp):
                    return parsed.to_pydatetime()
                return parsed
            except Exception as e:
                logger.error(f"Fel vid konvertering av timestamp '{ts}': {e}")
                raise ValueError(f"Failed to parse timestamp: {ts}") from e
        else:
            try:
                # Use pandas parser for other types
                parsed = pd.to_datetime(ts, errors='coerce')
                
                if pd.isna(parsed):
                    logger.warning(f"Kunde inte parsa timestamp: {ts}")
                    raise ValueError(f"Invalid timestamp: {ts}")
                
                if isinstance(parsed, pd.Timestamp):
                    return parsed.to_pydatetime()
                return parsed
            except Exception as e:
                logger.error(f"Fel vid konvertering av timestamp '{ts}': {e}")
                raise ValueError(f"Failed to parse timestamp: {ts}") from e
    
    def _prepare_data_for_plotting(self, data: List[Dict], param: str) -> tuple:
        """
        Prepare data for plotting a parameter.
        
        Args:
            data: List of weather data dictionaries
            param: Parameter name
            
        Returns:
            Tuple of (timestamps, values) or (None, None) if no valid data
        """
        if not data:
            return (None, None)
        
        timestamps = []
        values = []
        
        for row in data:
            if param in row and row[param] is not None:
                try:
                    ts = self._convert_timestamp(row['timestamp'])
                    timestamps.append(ts)
                    values.append(row[param])
                except (ValueError, TypeError) as e:
                    # Log warning but skip this row (NO fallback)
                    logger.debug(f"Hoppar över rad med ogiltig timestamp för parameter {param}: {e}")
                    continue
        
        # If all values are None, return None (NO fallback)
        if not values:
            return (None, None)
        
        return (timestamps, values)
    
    def _generate_plot_with_mode(
        self,
        df: pd.DataFrame,
        mode_obj: BaseMode,
        city_name: str,
        available_params: List[str],
        selected_date: Optional[date] = None
    ) -> Optional[matplotlib.figure.Figure]:
        """
        Generate plot using mode object - no if-else logic.
        
        Args:
            df: DataFrame with weather data
            mode_obj: Mode object for transformation
            city_name: City name
            available_params: List of parameters with data
            selected_date: Optional date for modes that require it (e.g. DailyMode)
            
        Returns:
            matplotlib Figure or None if data is empty
        """
        # Check if mode needs date selection and date is provided
        if mode_obj.needs_date_selection() and selected_date is None:
            logger.warning(f"{mode_obj.get_name()} requires selected_date but none provided")
            return None
        
        # Transform dataframe using mode
        df_transformed = mode_obj.transform(df, selected_date=selected_date)
        
        if df_transformed.empty:
            # No data after transformation - return None (NO fallback)
            return None
        
        # DailyMode special handling: hour as index (0-23), NOT group column
        if mode_obj.needs_date_selection():
            # DailyMode: df_transformed has hour as index (0-23)
            # Calculate grid layout
            rows, cols = self._calculate_grid_layout(len(available_params))
            
            # Create figure
            fig, axes = plt.subplots(rows, cols, figsize=(12, 8))
            
            # Title with selected date
            if selected_date:
                title = f"{city_name} – {selected_date.strftime('%Y-%m-%d')}"
            else:
                title = mode_obj.title(df_transformed, city_name)
            fig.suptitle(title, fontsize=10)
            
            # Flatten axes if needed
            if rows == 1 and cols == 1:
                axes = [axes]
            elif rows == 1 or cols == 1:
                axes = axes.flatten() if hasattr(axes, 'flatten') else [axes]
            else:
                axes = axes.flatten()
            
            # Plot each parameter
            for idx, param in enumerate(available_params):
                ax = axes[idx]
                
                # Check if parameter exists in aggregated data
                if param not in df_transformed.columns:
                    ax.axis('off')
                    continue
                
                # Get values for this parameter (hour is index)
                values = df_transformed[param].dropna()
                if values.empty:
                    ax.axis('off')
                    continue
                
                # VALIDATION: Check for constant/invalid time series
                unique_values = values.nunique()
                value_std = values.std()
                value_count = len(values)
                
                # Log data statistics for debugging
                logger.info(f"[DATA CHECK] {city_name} - {param.upper()} (DailyMode): count={value_count}, unique={unique_values}, std={value_std:.4f}, min={values.min():.2f}, max={values.max():.2f}")
                
                # Warn if constant data detected
                if unique_values == 1:
                    logger.warning(f"⚠️ KONSTANT DATA UPPTÄCKT: {city_name} - {param.upper()} (DailyMode) har endast ett unikt värde ({values.iloc[0]:.2f}) över {value_count} timmar. Detta är INTE en riktig tidsserie!")
                elif value_std < 0.01:
                    logger.warning(f"⚠️ MISSTÄNKT KONSTANT DATA: {city_name} - {param.upper()} (DailyMode) har mycket låg variation (std={value_std:.4f}) över {value_count} timmar. Kontrollera datakällan.")
                
                # Hours are the index (0-23)
                hours = values.index
                
                # Plot: black line, grid, minimal styling
                # One line per parameter (NOT per hour)
                ax.plot(hours, values.values, color='black', linewidth=1)
                
                # Add grid and labels (semantic metadata, not styling)
                ax.grid(True, alpha=0.3)
                ax.set_xlabel('Hour')
                ax.set_ylabel(param.upper())
                
                # X-axis: 0-23 (hours of day)
                ax.set_xlim(0, 23)
                ax.set_xticks(range(0, 24))
                
                # NO legend (only one day)
                
                # Set Y-axis: data.min() to data.max() (dynamic from data)
                y_min = values.min()
                y_max = values.max()
                
                # Numerisk stabilisering (inte fallback): hantera min==max edge case
                if y_min == y_max:
                    epsilon = abs(y_min) * 0.01 if y_min != 0 else 0.1
                    ax.set_ylim(y_min - epsilon, y_max + epsilon)
                else:
                    ax.set_ylim(y_min, y_max)
            
            # Hide unused subplots
            for idx in range(len(available_params), len(axes)):
                axes[idx].axis('off')
            
            plt.tight_layout()
            return fig
        
        else:
            # Other modes: df_transformed has 'group' column
            if 'group' not in df_transformed.columns:
                # No groups after transformation - return None (NO fallback)
                return None
            
            # Calculate grid layout
            rows, cols = self._calculate_grid_layout(len(available_params))
            
            # Create figure
            fig, axes = plt.subplots(rows, cols, figsize=(12, 8))
            title = mode_obj.title(df_transformed, city_name)
            fig.suptitle(title, fontsize=10)
            
            # Flatten axes if needed
            if rows == 1 and cols == 1:
                axes = [axes]
            elif rows == 1 or cols == 1:
                axes = axes.flatten() if hasattr(axes, 'flatten') else [axes]
            else:
                axes = axes.flatten()
            
            # Plot each parameter
            for idx, param in enumerate(available_params):
                ax = axes[idx]
                
                # Get unique groups
                unique_groups = df_transformed['group'].unique()
                
                # Plot each group as separate line
                for group_key in sorted(unique_groups):
                    group_data = df_transformed[df_transformed['group'] == group_key]
                    
                    # Get values for this parameter and group
                    if param not in group_data.columns:
                        continue
                    
                    values = group_data[param].dropna()
                    if values.empty:
                        continue
                    
                    timestamps = group_data.loc[values.index, 'timestamp']
                    
                    # Plot: black line, grid, minimal styling
                    legend_label = mode_obj.legend_label(group_key)
                    ax.plot(timestamps, values.values, color='black', linewidth=1, label=legend_label)
                
                # Add grid and labels (semantic metadata, not styling)
                ax.grid(True, alpha=0.3)
                ax.set_xlabel('Timestamp')
                ax.set_ylabel(param.upper())
                
                # Add legend if multiple groups
                if len(unique_groups) > 1:
                    ax.legend()
                
                # Set Y-axis: data.min() to data.max() (dynamic from data)
                all_values = df_transformed[param].dropna()
                if not all_values.empty:
                    y_min = all_values.min()
                    y_max = all_values.max()
                    
                    # Numerisk stabilisering (inte fallback): hantera min==max edge case
                    if y_min == y_max:
                        epsilon = abs(y_min) * 0.01 if y_min != 0 else 0.1
                        ax.set_ylim(y_min - epsilon, y_max + epsilon)
                    else:
                        ax.set_ylim(y_min, y_max)
                
                # Set X-axis: first to last timestamp (dynamic from data)
                if not df_transformed.empty and 'timestamp' in df_transformed.columns:
                    timestamps = df_transformed['timestamp'].dropna()
                    if not timestamps.empty:
                        ax.set_xlim(timestamps.min(), timestamps.max())
            
            # Hide unused subplots
            for idx in range(len(available_params), len(axes)):
                axes[idx].axis('off')
            
            plt.tight_layout()
            return fig
    
    def generate_city_graph(
        self,
        city_id: int,
        hours: Optional[int] = None,
        export_timestamp: Optional[str] = None,
        mode: Optional[BaseMode] = None,
        selected_date: Optional[date] = None
    ) -> Optional[str]:
        """
        Generate graph for a single city.
        
        Args:
            city_id: City ID
            hours: Optional hours to filter (None = ALL history)
            export_timestamp: Optional export timestamp (if None, generates new one)
            mode: Optional mode object for grouping (if None, uses default: one line per parameter)
            selected_date: Optional date for modes that require it (e.g. DailyMode)
            
        Returns:
            File path to generated graph, or None if no data
        """
        logger.debug(f"Genererar graf för stad {city_id}, hours={hours}, mode={mode}, selected_date={selected_date}")
        
        # Check if mode needs date selection and date is provided
        if mode is not None and mode.needs_date_selection() and selected_date is None:
            logger.warning(f"{mode.get_name()} requires selected_date but none provided for city {city_id}")
            return None
        
        # Get city info
        city = self.db.get_city(city_id)
        if not city:
            logger.warning(f"Stad {city_id} hittades inte")
            return None
        
        city_name = city['name']
        
        # Get weather data
        data = self.db.get_weather_data_for_city(city_id, hours=hours)
        
        if not data:
            logger.info(f"Ingen data för stad {city_name} (ID: {city_id})")
            return None
        
        # DEBUG: Log raw data statistics
        logger.info(f"[DEBUG] Hämtade {len(data)} datapunkter för {city_name} (ID: {city_id})")
        if len(data) > 0:
            # Check for duplicate timestamps
            timestamps = [row.get('timestamp') for row in data if 'timestamp' in row]
            unique_timestamps = len(set(timestamps))
            logger.info(f"[DEBUG] {city_name}: {len(timestamps)} timestamps, {unique_timestamps} unika timestamps")
            
            # Check pollutant values
            for param in ['pm25', 'pm10', 'no2', 'o3']:
                param_values = [row.get(param) for row in data if row.get(param) is not None]
                if param_values:
                    unique_vals = len(set(param_values))
                    logger.info(f"[DEBUG] {city_name} - {param.upper()}: {len(param_values)} värden, {unique_vals} unika värden, första 5: {param_values[:5]}")
                else:
                    logger.info(f"[DEBUG] {city_name} - {param.upper()}: Inga värden")
        
        # Get available parameters
        available_params = self._get_available_parameters(data)
        
        if not available_params:
            logger.info(f"Ingen parameter-data för stad {city_name} (alla värden är None)")
            return None
        
        # Convert to DataFrame
        df = pd.DataFrame(data)
        
        # Convert timestamp to datetime and ensure timezone-aware (CET)
        if 'timestamp' in df.columns:
            try:
                # Use pd.to_datetime with errors='coerce' to handle problematic timestamps gracefully
                # This handles timezone-aware strings like "2026-02-19 18:15:00+01:00"
                df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce', utc=False)
                
                # Drop rows where timestamp parsing failed (NaT)
                if df['timestamp'].isna().any():
                    num_failed = df['timestamp'].isna().sum()
                    logger.warning(f"Kunde inte parsa {num_failed} timestamp(s) för stad {city_name}, hoppar över dessa rader")
                    df = df[df['timestamp'].notna()]
                
                if df.empty:
                    logger.info(f"Ingen giltig data efter timestamp-parsing för stad {city_name}")
                    return None
                
                # Ensure timezone-aware (CET)
                if df['timestamp'].dt.tz is None:
                    # Naive datetime - localize to CET
                    df['timestamp'] = df['timestamp'].dt.tz_localize(CET)
                elif df['timestamp'].dt.tz != CET:
                    # Different timezone - convert to CET
                    df['timestamp'] = df['timestamp'].dt.tz_convert(CET)
            except Exception as e:
                logger.error(f"Fel vid timestamp-konvertering för stad {city_name}: {e}")
                return None
        
        # Use mode if provided, otherwise default behavior
        if mode is not None:
            fig = self._generate_plot_with_mode(df, mode, city_name, available_params, selected_date)
            if fig is None:
                logger.info(f"Ingen data efter transformation för stad {city_name}")
                return None
        else:
            # Default behavior: one line per parameter
            rows, cols = self._calculate_grid_layout(len(available_params))
            fig, axes = plt.subplots(rows, cols, figsize=(12, 8))
            first_ts = df['timestamp'].min() if not df.empty else None
            last_ts = df['timestamp'].max() if not df.empty else None
            if first_ts and last_ts:
                fig.suptitle(f"{city_name} - {first_ts} to {last_ts}", fontsize=10)
            else:
                fig.suptitle(f"{city_name}", fontsize=10)
            
            # Flatten axes if needed
            if rows == 1 and cols == 1:
                axes = [axes]
            elif rows == 1 or cols == 1:
                axes = axes.flatten() if hasattr(axes, 'flatten') else [axes]
            else:
                axes = axes.flatten()
            
            # Plot each parameter
            for idx, param in enumerate(available_params):
                ax = axes[idx]
                
                # Get values for this parameter
                param_data = df[df[param].notna()]
                if param_data.empty:
                    ax.axis('off')
                    continue
                
                timestamps = param_data['timestamp']
                values = param_data[param]
                
                # VALIDATION: Check for constant/invalid time series
                unique_values = values.nunique()
                value_std = values.std()
                value_count = len(values)
                
                # Log data statistics for debugging
                logger.info(f"[DATA CHECK] {city_name} - {param.upper()}: count={value_count}, unique={unique_values}, std={value_std:.4f}, min={values.min():.2f}, max={values.max():.2f}")
                
                # Warn if constant data detected (all values identical or very low variance)
                if unique_values == 1:
                    logger.warning(f"⚠️ KONSTANT DATA UPPTÄCKT: {city_name} - {param.upper()} har endast ett unikt värde ({values.iloc[0]:.2f}) över {value_count} datapunkter. Detta är INTE en riktig tidsserie!")
                elif value_std < 0.01:
                    logger.warning(f"⚠️ MISSTÄNKT KONSTANT DATA: {city_name} - {param.upper()} har mycket låg variation (std={value_std:.4f}) över {value_count} datapunkter. Kontrollera datakällan.")
                
                # Plot: black line, grid, minimal styling
                ax.plot(timestamps, values, color='black', linewidth=1)
                ax.grid(True, alpha=0.3)
                ax.set_xlabel('Timestamp')
                ax.set_ylabel(param.upper())
                
                # Set Y-axis: data.min() to data.max() (dynamic from data)
                y_min = values.min()
                y_max = values.max()
                
                # Numerisk stabilisering (inte fallback): hantera min==max edge case
                if y_min == y_max:
                    epsilon = abs(y_min) * 0.01 if y_min != 0 else 0.1
                    ax.set_ylim(y_min - epsilon, y_max + epsilon)
                else:
                    ax.set_ylim(y_min, y_max)
                
                # Set X-axis: first to last timestamp (dynamic from data)
                ax.set_xlim(timestamps.min(), timestamps.max())
            
            # Hide unused subplots
            for idx in range(len(available_params), len(axes)):
                axes[idx].axis('off')
            
            plt.tight_layout()
        
        # Generate filename
        sanitized_city_name = self._sanitize_filename(city_name)
        if export_timestamp is None:
            export_timestamp = self._get_export_timestamp()
        filename = f"{sanitized_city_name}_{export_timestamp}.png"
        filepath = self.output_dir / filename
        
        # Save
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close()
        
        logger.info(f"Graf genererad för {city_name}: {filepath}")
        return str(filepath)
    
    def generate_all_city_graphs(
        self,
        hours: Optional[int] = None,
        export_timestamp: Optional[str] = None,
        mode: Optional[BaseMode] = None,
        selected_date: Optional[date] = None
    ) -> tuple:
        """
        Generate graphs for all cities.
        
        Args:
            hours: Optional hours to filter (None = ALL history)
            export_timestamp: Optional export timestamp (if None, generates new one)
            mode: Optional mode object for grouping
            selected_date: Optional date for modes that require it (e.g. DailyMode)
            
        Returns:
            Tuple of (list of file paths, export_timestamp used)
        """
        logger.info(f"Genererar grafer för alla städer, hours={hours}, mode={mode}, selected_date={selected_date}")
        
        # Get all cities dynamically
        cities = self.db.get_all_cities()
        
        if not cities:
            logger.warning("Inga städer hittades")
            return ([], export_timestamp or self._get_export_timestamp())
        
        # Generate export timestamp (global for all graphs in this batch)
        if export_timestamp is None:
            export_timestamp = self._get_export_timestamp()
        
        filepaths = []
        for city in cities:
            city_id = city['id']
            filepath = self.generate_city_graph(
                city_id,
                hours=hours,
                export_timestamp=export_timestamp,
                mode=mode,
                selected_date=selected_date
            )
            if filepath:
                filepaths.append(filepath)
        
        logger.info(f"Genererade {len(filepaths)} stadsgrafer")
        return (filepaths, export_timestamp)
    
    def generate_national_graph(
        self,
        hours: Optional[int] = None,
        export_timestamp: Optional[str] = None,
        mode: Optional[BaseMode] = None,
        selected_date: Optional[date] = None
    ) -> Optional[str]:
        """
        Generate national average graph.
        
        Args:
            hours: Optional hours to filter (None = ALL history)
            export_timestamp: Optional export timestamp (if None, generates new one)
            mode: Optional mode object for grouping (if None, uses default: one line per parameter)
            selected_date: Optional date for modes that require it (e.g. DailyMode)
            
        Returns:
            File path to generated graph, or None if no data
        """
        logger.info(f"Genererar nationell graf, hours={hours}, mode={mode}, selected_date={selected_date}")
        
        # Check if mode needs date selection and date is provided
        if mode is not None and mode.needs_date_selection() and selected_date is None:
            logger.warning(f"{mode.get_name()} requires selected_date but none provided for national graph")
            return None
        
        # Get all weather data
        data = self.db.get_all_weather_data(hours=hours)
        
        if not data:
            logger.info("Ingen data för nationell graf")
            return None
        
        # Convert to DataFrame
        df = pd.DataFrame(data)
        
        # Convert timestamp to datetime and ensure timezone-aware (CET)
        if 'timestamp' in df.columns:
            try:
                # Use pd.to_datetime with errors='coerce' to handle problematic timestamps gracefully
                # This handles timezone-aware strings like "2026-02-19 18:15:00+01:00"
                df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce', utc=False)
                
                # Drop rows where timestamp parsing failed (NaT)
                if df['timestamp'].isna().any():
                    num_failed = df['timestamp'].isna().sum()
                    logger.warning(f"Kunde inte parsa {num_failed} timestamp(s) för nationell graf, hoppar över dessa rader")
                    df = df[df['timestamp'].notna()]
                
                if df.empty:
                    logger.info("Ingen giltig data efter timestamp-parsing för nationell graf")
                    return None
                
                # Ensure timezone-aware (CET)
                if df['timestamp'].dt.tz is None:
                    # Naive datetime - localize to CET
                    df['timestamp'] = df['timestamp'].dt.tz_localize(CET)
                elif df['timestamp'].dt.tz != CET:
                    # Different timezone - convert to CET
                    df['timestamp'] = df['timestamp'].dt.tz_convert(CET)
            except Exception as e:
                logger.error(f"Fel vid timestamp-konvertering för nationell graf: {e}")
                return None
        
        # Filter by timestamp if hours specified (time-based, not datapoint-based)
        if hours is not None:
            cutoff_time = datetime.now(CET) - pd.Timedelta(hours=hours)
            df = df[df['timestamp'] >= cutoff_time]
        
        if df.empty:
            logger.info("Ingen data efter filtrering för nationell graf")
            return None
        
        # Group by timestamp and calculate mean (numeric only)
        numeric_cols = ['pm25', 'pm10', 'no2', 'o3', 'temperature', 'wind_speed', 'humidity']
        available_numeric_cols = [col for col in numeric_cols if col in df.columns]
        
        if not available_numeric_cols:
            logger.info("Inga numeriska kolumner för nationell graf")
            return None
        
        # Group by timestamp and mean
        grouped = df.groupby('timestamp')[available_numeric_cols].mean(numeric_only=True)
        
        # Get available parameters (those with at least one non-NaN value)
        available_params = []
        for param in self.PARAMETERS:
            if param in grouped.columns:
                # Check if has at least one non-NaN value
                if grouped[param].notna().any():
                    available_params.append(param)
        
        if not available_params:
            logger.info("Inga parametrar med data för nationell graf")
            return None
        
        # Use mode if provided, otherwise default behavior
        if mode is not None:
            # For national graph with mode, transform the grouped data
            df_for_mode = grouped.reset_index()
            df_transformed = mode.transform(df_for_mode, selected_date=selected_date)
            
            # Create figure with mode
            fig = self._generate_plot_with_mode(df_transformed, mode, "Sweden National Average", available_params, selected_date)
            if fig is None:
                logger.info("Ingen data efter transformation för nationell graf")
                return None
        else:
            # Default behavior: one line per parameter
            rows, cols = self._calculate_grid_layout(len(available_params))
            fig, axes = plt.subplots(rows, cols, figsize=(12, 8))
            first_ts = grouped.index[0]
            last_ts = grouped.index[-1]
            fig.suptitle(f"Sweden National Average - {first_ts} to {last_ts}", fontsize=10)
            
            # Flatten axes if needed
            if rows == 1 and cols == 1:
                axes = [axes]
            elif rows == 1 or cols == 1:
                axes = axes.flatten() if hasattr(axes, 'flatten') else [axes]
            else:
                axes = axes.flatten()
            
            # Plot each parameter
            for idx, param in enumerate(available_params):
                ax = axes[idx]
                
                # Get values (drop NaN)
                values = grouped[param].dropna()
                
                if values.empty:
                    # No valid data - skip subplot
                    ax.axis('off')
                    continue
                
                timestamps = values.index
                
                # Plot: black line, grid, minimal styling
                ax.plot(timestamps, values.values, color='black', linewidth=1)
                ax.grid(True, alpha=0.3)
                ax.set_xlabel('Timestamp')
                ax.set_ylabel(param.upper())
                
                # Set Y-axis: data.min() to data.max() (dynamic from data)
                y_min = values.min()
                y_max = values.max()
                
                # Numerisk stabilisering (inte fallback): hantera min==max edge case
                if y_min == y_max:
                    epsilon = abs(y_min) * 0.01 if y_min != 0 else 0.1
                    ax.set_ylim(y_min - epsilon, y_max + epsilon)
                else:
                    ax.set_ylim(y_min, y_max)
                
                # Set X-axis: first to last timestamp (dynamic from data)
                ax.set_xlim(min(timestamps), max(timestamps))
            
            # Hide unused subplots
            for idx in range(len(available_params), len(axes)):
                axes[idx].axis('off')
            
            plt.tight_layout()
        
        # Generate filename
        if export_timestamp is None:
            export_timestamp = self._get_export_timestamp()
        filename = f"sweden_{export_timestamp}.png"
        filepath = self.output_dir / filename
        
        # Save
        plt.savefig(filepath, dpi=150, bbox_inches='tight')
        plt.close()
        
        logger.info(f"Nationell graf genererad: {filepath}")
        return str(filepath)
