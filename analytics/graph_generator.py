"""Graph generator for weather data visualization."""

import os
import re
import math
from datetime import datetime, date
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import logging

try:
    _PANDAS_VERSION = tuple(int(x) for x in pd.__version__.split(".")[:2])
except Exception:
    _PANDAS_VERSION = (0, 0)

# Matplotlib imports
# Backend is set in main.py before any imports
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib import dates as mdates
from PyQt5.QtGui import QColor
import pandas as pd

from database.db_manager import DatabaseManager
from analytics.graph_modes import BaseMode

# CET timezone for all operations
CET = ZoneInfo("Europe/Stockholm")

# Get module logger
logger = logging.getLogger("WeatherApp.analytics.graph_generator")


class GraphGenerator:
    """Generate graphs from weather data following strict design principles."""
    
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

    def _parse_timestamp_column(
        self,
        df: pd.DataFrame,
        column_name: str,
        logger_context: str,
    ) -> Tuple[pd.Series, int]:
        """
        Parse a timestamp column robustly (mixed formats, numeric Unix s/ms).
        No hardcoded date format strings; data-driven parsing only.

        Returns:
            (parsed_series, count_still_nat)
        """
        series = df[column_name]
        parsed = pd.Series(index=series.index, dtype="datetime64[ns]")
        num_nat = 0

        if _PANDAS_VERSION >= (2, 0):
            try:
                parsed = pd.to_datetime(
                    series, format="mixed", errors="coerce", utc=False
                )
            except TypeError:
                parsed = pd.to_datetime(series, errors="coerce", utc=False)
        else:
            parsed = pd.to_datetime(series, errors="coerce", utc=False)

        still_nat = parsed.isna()
        if still_nat.any():
            raw = series[still_nat]
            numeric = pd.to_numeric(raw, errors="coerce")
            ok = numeric.notna()
            if ok.any():
                converted = pd.to_datetime(numeric[ok], unit="s", errors="coerce")
                parsed = parsed.copy()
                parsed.update(converted)
            still_nat = parsed.isna()
            if still_nat.any():
                raw = series[still_nat]
                numeric = pd.to_numeric(raw, errors="coerce")
                ok = numeric.notna()
                if ok.any():
                    converted = pd.to_datetime(numeric[ok], unit="ms", errors="coerce")
                    parsed = parsed.copy()
                    parsed.update(converted)

        num_nat = int(parsed.isna().sum())
        if num_nat > 0 and logger_context:
            first_fail = series[parsed.isna()].iloc[0]
            logger.debug(
                f"Timestamp parsing {logger_context}: first unparseable value: {first_fail!r} (type={type(first_fail).__name__})"
            )
        return parsed, num_nat

    def _get_export_timestamp(self) -> str:
        """
        Get current timestamp for export filename (CET timezone).
        
        Returns:
            Timestamp string in format YYYYMMDD_HHMMSS
        """
        return datetime.now(CET).strftime("%Y%m%d_%H%M%S")
    
    def _discover_parameters_from_schema(self) -> List[str]:
        """
        Discover parameter columns from database schema.
        
        Returns:
            List of parameter column names (excluding metadata columns)
        """
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(weather_data)")
            columns = [row[1] for row in cursor.fetchall()]
            
            # Exclude non-parameter columns
            excluded = {'id', 'city_id', 'timestamp', 'source', 'aqi', 'measurement_timestamp'}
            parameters = [col for col in columns if col not in excluded]
            
            logger.debug(f"Discovered parameters from schema: {parameters}")
            return parameters
        except Exception as e:
            logger.error(f"Error discovering parameters from schema: {e}")
            # Fallback to empty list (NO fallback to hardcoded list)
            return []
    
    def _get_parameter_order(self, parameters: List[str]) -> List[str]:
        """
        Get parameters in logical order: pollutants first, then weather parameters.
        
        Args:
            parameters: List of discovered parameter names
            
        Returns:
            Ordered list of parameters
        """
        # Define preferred order: pollutants first, then weather
        preferred_order = ['pm25', 'pm10', 'no2', 'o3', 'temperature', 'wind_speed', 'humidity']
        
        # Order parameters according to preferred order, then append any others
        ordered = []
        for param in preferred_order:
            if param in parameters:
                ordered.append(param)
        
        # Add any remaining parameters not in preferred order
        for param in parameters:
            if param not in ordered:
                ordered.append(param)
        
        return ordered
    
    def _detect_temporal_gaps(
        self, 
        timestamps: pd.Series, 
        max_gap_minutes: Optional[int] = None
    ) -> List[Tuple[int, int]]:
        """
        Detect temporal gaps in timestamp series.
        
        Returns list of (start_idx, end_idx) tuples for continuous segments.
        Gaps larger than max_gap_minutes are treated as breaks.
        
        Args:
            timestamps: Sorted timestamp series
            max_gap_minutes: Maximum gap in minutes before treating as break.
                            If None, uses calibration_parameter 'graph_max_gap_minutes'
                            or default 120 minutes (2 hours)
        
        Returns:
            List of (start_idx, end_idx) tuples for continuous segments
        """
        if timestamps.empty or len(timestamps) < 2:
            return [(0, len(timestamps) - 1)] if len(timestamps) > 0 else []
        
        # Get max_gap from calibration_parameters or use default
        if max_gap_minutes is None:
            max_gap_minutes = self.db.get_calibration_parameter('graph_max_gap_minutes')
            if max_gap_minutes is None:
                max_gap_minutes = 240  # Default: 4 hours (increased for WeeklyMode to handle sparse data better)
        
        segments = []
        start_idx = 0
        
        for i in range(1, len(timestamps)):
            gap = (timestamps.iloc[i] - timestamps.iloc[i-1]).total_seconds() / 60.0
            
            if gap > max_gap_minutes:
                # Gap detected - end current segment, start new one
                segments.append((start_idx, i - 1))
                start_idx = i
        
        # Add final segment
        segments.append((start_idx, len(timestamps) - 1))
        
        return segments
    
    def _get_y_axis_epsilon(self, y_min: float) -> float:
        """
        Get epsilon value for Y-axis edge case handling.
        
        Args:
            y_min: Minimum Y value
        
        Returns:
            Epsilon value from calibration_parameters or computed default
        """
        # Try to get from calibration_parameters
        epsilon_factor = self.db.get_calibration_parameter('graph_y_axis_epsilon_factor')
        epsilon_absolute = self.db.get_calibration_parameter('graph_y_axis_epsilon_absolute')
        
        if epsilon_factor is not None:
            return abs(y_min) * epsilon_factor
        elif epsilon_absolute is not None:
            return epsilon_absolute
        else:
            # Default: 1% of value or 0.1 if zero
            return abs(y_min) * 0.01 if y_min != 0 else 0.1
    
    def _get_plot_style_params(self) -> Dict[str, any]:
        """
        Get plot styling parameters from calibration_parameters.
        
        Returns:
            Dictionary with style parameters
        """
        show_legend_val = self.db.get_calibration_parameter('graph_show_legend')
        show_legend = bool(show_legend_val and float(show_legend_val) != 0)
        return {
            'linewidth': self.db.get_calibration_parameter('graph_linewidth') or 1.0,
            'figsize_width': self.db.get_calibration_parameter('graph_figsize_width') or 12.0,
            'figsize_height': self.db.get_calibration_parameter('graph_figsize_height') or 8.0,
            'dpi': self.db.get_calibration_parameter('graph_dpi') or 150,
            'grid_alpha': self.db.get_calibration_parameter('graph_grid_alpha') or 0.3,
            'fontsize_title': self.db.get_calibration_parameter('graph_fontsize_title') or 10,
            'show_legend': show_legend,
        }
    
    def _export_matplotlib_figure(self, figure: Figure, filepath: Path, style: Dict) -> None:
        """
        Export matplotlib Figure to PNG file.
        
        Args:
            figure: Matplotlib Figure to export
            filepath: Path to save PNG file
            style: Style parameters dict with 'dpi', 'figsize_width', 'figsize_height'
        """
        # Set figure size
        figure.set_size_inches(style['figsize_width'], style['figsize_height'])
        
        # Create canvas and save
        canvas = FigureCanvasAgg(figure)
        canvas.print_figure(str(filepath), dpi=style['dpi'], bbox_inches='tight')

    def _export_placeholder_for_city(
        self,
        city_name: str,
        selected_date: date,
        export_timestamp: str,
        mode: Optional[BaseMode],
        category: Optional[str],
    ) -> Optional[str]:
        """
        Export a placeholder PNG for a city that has no data for the selected date.
        Keeps one-file-per-city for date-based exports (e.g. Daily).
        """
        try:
            style = self._get_plot_style_params()
            fig = Figure(facecolor='white')
            ax = fig.add_subplot(111)
            ax.set_axis_off()
            ax.text(
                0.5, 0.5,
                f"{city_name}\nIngen data för {selected_date.isoformat()}",
                transform=ax.transAxes,
                fontsize=style.get('fontsize_title', 10) or 10,
                ha='center',
                va='center',
                wrap=True,
            )
            sanitized = self._sanitize_filename(city_name)
            filename = f"{sanitized}_{export_timestamp}.png"
            if category:
                category_dir = self.output_dir / category
                category_dir.mkdir(parents=True, exist_ok=True)
                if mode:
                    mode_dir = category_dir / mode.get_name()
                    mode_dir.mkdir(parents=True, exist_ok=True)
                    filepath = mode_dir / filename
                else:
                    filepath = category_dir / filename
            elif mode:
                mode_dir = self.output_dir / mode.get_name()
                mode_dir.mkdir(parents=True, exist_ok=True)
                filepath = mode_dir / filename
            else:
                filepath = self.output_dir / filename
            self._export_matplotlib_figure(fig, filepath, style)
            logger.debug(f"Placeholder export för {city_name}: {filepath}")
            return str(filepath)
        except Exception as e:
            logger.warning(f"Kunde inte skapa placeholder för {city_name}: {e}")
            return None

    def _create_matplotlib_default_plot(
        self,
        df: pd.DataFrame,
        available_params: List[str],
        title: str,
        style: Dict
    ) -> Figure:
        """
        Create matplotlib plot for default behavior (one line per parameter).
        
        Args:
            df: DataFrame with weather data
            available_params: List of parameters to plot
            title: Plot title
            style: Style parameters dict
            
        Returns:
            Matplotlib Figure with plots
        """
        figure = Figure(figsize=(style['figsize_width'], style['figsize_height']))
        rows, cols = self._calculate_grid_layout(len(available_params))
        
        # Set title
        figure.suptitle(title, fontsize=style['fontsize_title'])
        
        # Plot each parameter
        for idx, param in enumerate(available_params):
            row = idx // cols
            col = idx % cols
            ax = figure.add_subplot(rows, cols, idx + 1)
            
            # Get values for this parameter
            timestamps = df['timestamp']
            values = df[param]
            valid_mask = values.notna()
            valid_timestamps = timestamps[valid_mask]
            valid_values = values[valid_mask]
            
            if valid_values.empty:
                continue
            
            # Detect gaps and plot segments separately
            segments = self._detect_temporal_gaps(valid_timestamps)
            
            # Plot each continuous segment
            for start_idx, end_idx in segments:
                seg_timestamps = valid_timestamps.iloc[start_idx:end_idx+1]
                seg_values = valid_values.iloc[start_idx:end_idx+1].values
                
                if len(seg_timestamps) >= 2:
                    ax.plot(seg_timestamps, seg_values, linewidth=style['linewidth'], color='black')
            
            # Grid and labels
            ax.grid(True, alpha=style['grid_alpha'])
            ax.set_ylabel(param.upper(), fontsize=9)
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
            figure.autofmt_xdate(rotation=45)
        
        figure.tight_layout()
        return figure
    
    def _get_available_parameters(self, data: List[Dict]) -> List[str]:
        """
        Get list of parameters that have at least one non-None value.
        Uses dynamic parameter discovery from database schema.
        
        Args:
            data: List of weather data dictionaries
            
        Returns:
            List of parameter names with data, in logical order
        """
        if not data:
            return []
        
        # Discover parameters from database schema
        all_parameters = self._discover_parameters_from_schema()
        
        if not all_parameters:
            logger.warning("No parameters discovered from schema")
            return []
        
        # Check which parameters have actual data
        available = []
        for param in all_parameters:
            # Check if parameter exists in data and has at least one non-None value
            for row in data:
                if param in row and row[param] is not None:
                    available.append(param)
                    break
        
        # Log discovered vs available parameters
        logger.info(f"Discovered {len(all_parameters)} parameters from schema: {all_parameters}")
        logger.info(f"Found {len(available)} parameters with data: {available}")
        
        # Return in logical order
        return self._get_parameter_order(available)
    
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

    def _has_plottable_data(
        self,
        df_transformed: pd.DataFrame,
        param: str,
        mode_obj: BaseMode,
    ) -> bool:
        """
        Return True if the parameter has at least one plottable series (min 1 point per group).
        Used to avoid empty subplots: only params with plottable data get a panel.
        """
        if df_transformed.empty or param not in df_transformed.columns:
            return False
        if mode_obj.needs_date_selection():
            # DailyMode: hour index, single series per param
            values = df_transformed[param].dropna()
            return len(values) >= 1
        if 'group' not in df_transformed.columns:
            return False
        for group_key in df_transformed['group'].unique():
            group_data = df_transformed[df_transformed['group'] == group_key]
            valid = group_data[param].dropna()
            if len(valid) >= 1:
                return True
        return False

    def _generate_plot_with_mode(
        self,
        df: pd.DataFrame,
        mode_obj: BaseMode,
        city_name: str,
        available_params: List[str],
        selected_date: Optional[date] = None
    ):
        """
        Generate plot using mode object with matplotlib - no if-else logic.
        
        Args:
            df: DataFrame with weather data
            mode_obj: Mode object for transformation
            city_name: City name
            available_params: List of parameters with data
            selected_date: Optional date for modes that require it (e.g. DailyMode)
            
        Returns:
            Matplotlib Figure or None if data is empty
        """
        # Get style parameters
        style = self._get_plot_style_params()
        
        # Check if mode needs date selection and date is provided
        if mode_obj.needs_date_selection() and selected_date is None:
            logger.warning(f"{mode_obj.get_name()} requires selected_date but none provided")
            return None
        
        # Transform dataframe using mode
        df_transformed = mode_obj.transform(df, selected_date=selected_date)
        
        if df_transformed.empty:
            # No data after transformation - return None (NO fallback)
            return None

        # Only show subplots for parameters that have plottable data (no empty panels)
        plottable_params = [p for p in available_params if self._has_plottable_data(df_transformed, p, mode_obj)]
        if not plottable_params:
            logger.info(f"[GRAPH] Inga parametrar med plottbar data efter transform för {city_name}")
            return None
        
        # DailyMode special handling: hour as index (0-23), NOT group column
        if mode_obj.needs_date_selection():
            # DailyMode: df_transformed has hour as index (0-23)
            # Calculate grid layout
            rows, cols = self._calculate_grid_layout(len(plottable_params))
            
            # Create matplotlib figure
            figure = Figure(figsize=(style['figsize_width'], style['figsize_height']))
            
            # Title with selected date
            if selected_date:
                title = f"{city_name} – {selected_date.strftime('%Y-%m-%d')}"
            else:
                title = mode_obj.title(df_transformed, city_name)
            figure.suptitle(title, fontsize=style['fontsize_title'])
            
            # Plot each parameter (only those with plottable data)
            for idx, param in enumerate(plottable_params):
                row = idx // cols
                col = idx % cols
                ax = figure.add_subplot(rows, cols, idx + 1)
                
                # Get values for this parameter (hour is index)
                values = df_transformed[param].dropna()
                if values.empty:
                    continue
                
                # VALIDATION: Check for constant/invalid time series
                unique_values = values.nunique()
                value_std = values.std()
                value_count = len(values)
                
                # Log data statistics for debugging
                logger.info(f"[DATA CHECK] {city_name} - {param.upper()} (DailyMode): count={value_count}, unique={unique_values}, std={value_std:.4f}, min={values.min():.2f}, max={values.max():.2f}")
                
                # Log constant/near-constant data at DEBUG only (e.g. SUNSHINE_DURATION=0 at night is valid)
                if unique_values == 1:
                    logger.debug(
                        f"Constant data: {city_name} - {param.upper()} (DailyMode) single value {values.iloc[0]:.2f} over {value_count} hours"
                    )
                elif value_std < 0.01:
                    logger.debug(
                        f"Low variation: {city_name} - {param.upper()} (DailyMode) std={value_std:.4f} over {value_count} hours"
                    )
                
                # Hours are the index (0-23)
                hours = values.index.tolist()
                hour_values = values.values.tolist()
                
                # Plot: black line, grid, minimal styling
                ax.plot(hours, hour_values, linewidth=style['linewidth'], color='black')
                
                # Add grid and labels
                ax.grid(True, alpha=style['grid_alpha'])
                ax.set_ylabel(param.upper(), fontsize=9)
                ax.set_xlabel('Hour', fontsize=9)
                
                # X-axis: 0-23 (hours of day)
                ax.set_xlim(0, 23)
                
                # Set Y-axis: data.min() to data.max() (dynamic from data)
                y_min = values.min()
                y_max = values.max()
                
                # Numerisk stabilisering (inte fallback): hantera min==max edge case
                if y_min == y_max:
                    epsilon = self._get_y_axis_epsilon(y_min)
                    ax.set_ylim(y_min - epsilon, y_max + epsilon)
                else:
                    ax.set_ylim(y_min, y_max)
            
            figure.tight_layout()
            return figure
        
        else:
            # Other modes: df_transformed has 'group' column
            if 'group' not in df_transformed.columns:
                # No groups after transformation - return None (NO fallback)
                return None
            
            # Calculate grid layout (only params with plottable data)
            rows, cols = self._calculate_grid_layout(len(plottable_params))
            
            # Create matplotlib figure
            figure = Figure(figsize=(style['figsize_width'], style['figsize_height']))
            title = mode_obj.title(df_transformed, city_name)
            figure.suptitle(title, fontsize=style['fontsize_title'])
            
            # Plot each parameter (only those with plottable data)
            for idx, param in enumerate(plottable_params):
                row = idx // cols
                col = idx % cols
                ax = figure.add_subplot(rows, cols, idx + 1)
                
                # Get unique groups
                unique_groups = df_transformed['group'].unique()
                
                # Plot each group as separate line
                for group_key in sorted(unique_groups):
                    group_data = df_transformed[df_transformed['group'] == group_key].copy()
                    
                    # Get values for this parameter and group
                    if param not in group_data.columns:
                        continue
                    
                    # CRITICAL: Sort by timestamp to ensure correct plotting order
                    if 'timestamp' in group_data.columns:
                        group_data = group_data.sort_values('timestamp')
                    
                    # Keep all timestamps, but only plot non-NULL values
                    timestamps = group_data['timestamp']
                    values = group_data[param]
                    valid_mask = values.notna()
                    valid_timestamps = timestamps[valid_mask]
                    valid_values = values[valid_mask]
                    
                    if valid_values.empty:
                        continue
                    
                    # Log data statistics for debugging
                    unique_vals = valid_values.nunique()
                    value_std = valid_values.std()
                    logger.debug(f"[GRAPH] {city_name} - {param.upper()} ({group_key}): {len(valid_values)} points, unique={unique_vals}, std={value_std:.4f}, range=[{valid_values.min():.2f}, {valid_values.max():.2f}]")
                    
                    # Warn if constant data (only one unique value)
                    if unique_vals == 1:
                        logger.warning(f"[GRAPH] ⚠️ Konstant data: {city_name} - {param.upper()} ({group_key}) har endast ett värde ({valid_values.iloc[0]:.2f}) över {len(valid_values)} datapunkter")
                    
                    # Detect gaps and plot segments separately
                    segments = self._detect_temporal_gaps(valid_timestamps)
                    
                    if len(segments) > 1:
                        logger.debug(f"[GRAPH] {city_name} - {param.upper()} ({group_key}): {len(segments)} separata segment (gaps i data)")
                    
                    # Calculate data coverage
                    if not valid_timestamps.empty and len(valid_timestamps) > 1:
                        time_span = (valid_timestamps.max() - valid_timestamps.min()).total_seconds() / 3600.0  # hours
                        # Get x-axis range from transformed data
                        if not df_transformed.empty and 'timestamp' in df_transformed.columns:
                            all_timestamps = df_transformed['timestamp'].dropna()
                            if not all_timestamps.empty:
                                x_axis_span = (all_timestamps.max() - all_timestamps.min()).total_seconds() / 3600.0  # hours
                                if x_axis_span > 0:
                                    coverage = (time_span / x_axis_span) * 100.0
                                    logger.debug(f"[GRAPH] Data coverage för {city_name} - {param.upper()} ({group_key}): {coverage:.1f}%")
                                    
                                    # Warn if coverage is very low
                                    if coverage < 10.0:
                                        logger.warning(f"[GRAPH] ⚠️ Mycket sparse data: {city_name} - {param.upper()} ({group_key}) har endast {coverage:.1f}% coverage ({len(valid_values)} datapunkter över {x_axis_span:.1f}h)")
                    
                    legend_label = mode_obj.legend_label(group_key)
                    
                    # Plot each continuous segment separately
                    for seg_idx, (start_idx, end_idx) in enumerate(segments):
                        seg_timestamps = valid_timestamps.iloc[start_idx:end_idx+1]
                        seg_values = valid_values.iloc[start_idx:end_idx+1].values
                        
                        # Only plot if segment has at least 2 points
                        if len(seg_timestamps) >= 2:
                            ax.plot(seg_timestamps, seg_values, linewidth=style['linewidth'], 
                                   color='black', label=legend_label if seg_idx == 0 else '')
                        elif len(seg_timestamps) == 1:
                            # Single point: plot as marker instead of line
                            ax.plot(seg_timestamps, seg_values, linewidth=style['linewidth'], 
                                   color='black', marker='o', markersize=3, 
                                   label=legend_label if seg_idx == 0 else '')
                
                # Add grid and labels
                ax.grid(True, alpha=style['grid_alpha'])
                ax.set_ylabel(param.upper(), fontsize=9)
                ax.set_xlabel('Timestamp', fontsize=9)
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
                figure.autofmt_xdate(rotation=45)
                
                # Add legend only if enabled in calibration (default off)
                if style.get('show_legend') and len(unique_groups) > 1:
                    ax.legend()
                
                # Set Y-axis: data.min() to data.max() (dynamic from data)
                all_values = df_transformed[param].dropna()
                if not all_values.empty:
                    y_min = all_values.min()
                    y_max = all_values.max()
                    
                    # Numerisk stabilisering (inte fallback): hantera min==max edge case
                    if y_min == y_max:
                        epsilon = self._get_y_axis_epsilon(y_min)
                        ax.set_ylim(y_min - epsilon, y_max + epsilon)
                    else:
                        ax.set_ylim(y_min, y_max)
                
                # Set X-axis: first to last timestamp (dynamic from data)
                if not df_transformed.empty and 'timestamp' in df_transformed.columns:
                    timestamps = df_transformed['timestamp'].dropna()
                    if not timestamps.empty:
                        ax.set_xlim(timestamps.min(), timestamps.max())
            
            figure.tight_layout()
            return figure
    
    def generate_city_graph(
        self,
        city_id: int,
        hours: Optional[int] = None,
        export_timestamp: Optional[str] = None,
        mode: Optional[BaseMode] = None,
        selected_date: Optional[date] = None,
        category: Optional[str] = None
    ) -> Optional[str]:
        """
        Generate graph for a single city.
        
        Args:
            city_id: City ID
            hours: Optional hours to filter (None = ALL history)
            export_timestamp: Optional export timestamp (if None, generates new one)
            mode: Optional mode object for grouping (if None, uses default: one line per parameter)
            selected_date: Optional date for modes that require it (e.g. DailyMode)
            category: Optional category to filter parameters ('weather', 'air_quality', 'solar', 'storm', 'lightning')
            
        Returns:
            File path to generated graph, or None if no data
        """
        logger.debug(f"Genererar graf för stad {city_id}, hours={hours}, mode={mode}, selected_date={selected_date}, category={category}")
        
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
        
        # Special-hantering för blixtar (lightning-events kommer från separat tabell)
        if category == "lightning":
            # Använd hours om satt, annars ta 24h per default för blixtgrafer
            lightning_hours = hours if hours is not None else 24
            max_distance_km = self.db.get_calibration_parameter("lightning_graph_max_distance_km")
            try:
                events = self.db.get_lightning_events(
                    city_id=city_id,
                    hours=int(lightning_hours),
                    max_distance_km=float(max_distance_km) if max_distance_km is not None else None,
                )
            except Exception as e:
                logger.error(f"Fel vid hämtning av lightning events för stad {city_name}: {e}")
                return None

            if not events:
                logger.info(f"Inga lightning events för stad {city_name} (ID: {city_id})")
                return None

            df = pd.DataFrame(events)

            if "timestamp" not in df.columns:
                logger.warning(f"Inga timestamp-kolumn i lightning events för stad {city_name}")
                return None

            try:
                parsed, num_failed = self._parse_timestamp_column(
                    df, "timestamp", logger_context=f"lightning events {city_name}"
                )
                df["timestamp"] = parsed
                if num_failed > 0:
                    logger.warning(
                        f"Kunde inte parsa {num_failed} timestamp(s) i lightning events för stad {city_name}, hoppar över dessa rader"
                    )
                    df = df[df["timestamp"].notna()]
                if df.empty:
                    logger.info(f"Inga giltiga tidsstämplar i lightning events för stad {city_name}")
                    return None
                if df["timestamp"].dt.tz is None:
                    df["timestamp"] = df["timestamp"].dt.tz_localize(CET)
                elif df["timestamp"].dt.tz != CET:
                    df["timestamp"] = df["timestamp"].dt.tz_convert(CET)
            except Exception as e:
                logger.error(f"Fel vid timestamp-konvertering för lightning events för stad {city_name}: {e}")
                return None

            # Välj parametrar att plotta om de finns
            lightning_params = [p for p in ["intensity", "distance_km"] if p in df.columns]
            if not lightning_params:
                logger.info(f"Inga numeriska lightning-parametrar att plotta för stad {city_name}")
                return None

            style = self._get_plot_style_params()

            first_ts = df["timestamp"].min()
            last_ts = df["timestamp"].max()
            title = f"{city_name} – Lightning events {first_ts} to {last_ts}"

            widget = self._create_matplotlib_default_plot(df, lightning_params, title, style)

            sanitized_city_name = self._sanitize_filename(city_name)
            if export_timestamp is None:
                export_timestamp = self._get_export_timestamp()

            category_dir = self.output_dir / "lightning"
            category_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{sanitized_city_name}_{export_timestamp}.png"
            filepath = category_dir / filename

            self._export_matplotlib_figure(widget, filepath, style)
            logger.info(f"Lightning-graf genererad för {city_name}: {filepath}")
            return str(filepath)
        
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
            
            # Discover all parameters from schema
            all_parameters = self._discover_parameters_from_schema()
            logger.info(f"[DEBUG] {city_name}: Discovered {len(all_parameters)} parameters from schema: {all_parameters}")
            
            # Check all discovered parameters for data availability
            for param in all_parameters:
                param_values = [row.get(param) for row in data if row.get(param) is not None]
                if param_values:
                    unique_vals = len(set(param_values))
                    logger.info(f"[DEBUG] {city_name} - {param.upper()}: {len(param_values)} värden, {unique_vals} unika värden, första 5: {param_values[:5]}")
                else:
                    logger.info(f"[DEBUG] {city_name} - {param.upper()}: Inga värden")
        
        # Get available parameters (dynamically discovered)
        available_params = self._get_available_parameters(data)
        logger.info(
            f"[GRAPH DEBUG] City {city_name} ({city_id}): discovered {len(available_params)} parameters with data: "
            f"{available_params}"
        )
        
        # Filter by category if provided
        if category:
            category_params = self.db.get_parameters_by_category(category)
            if category_params:
                category_param_names = {p['parameter_name'] for p in category_params}
                before_count = len(available_params)
                available_params = [p for p in available_params if p in category_param_names]
                logger.info(
                    f"[GRAPH DEBUG] City {city_name} ({city_id}): category='{category}', "
                    f"registry_params={sorted(category_param_names)}, "
                    f"before_filter={before_count}, after_filter={len(available_params)}"
                )
            else:
                # No registry parameters for this category – log but keep all discovered parameters
                logger.warning(
                    f"[GRAPH DEBUG] Inga parametrar hittades i parameter_registry för kategori '{category}' – "
                    f"använder alla upptäckta parametrar utan kategorifilter."
                )
        
        if not available_params:
            logger.info(
                f"[GRAPH DEBUG] Ingen parameter-data för stad {city_name} (ID={city_id}); "
                f"alla parametrar saknar icke-NULL värden efter filtrering."
            )
            return None
        
        # Convert to DataFrame
        df = pd.DataFrame(data)
        
        # Convert timestamp to datetime and ensure timezone-aware (CET)
        if 'timestamp' in df.columns:
            try:
                parsed, num_failed = self._parse_timestamp_column(
                    df, 'timestamp', logger_context=city_name
                )
                df['timestamp'] = parsed
                if num_failed > 0:
                    logger.warning(
                        f"Kunde inte parsa {num_failed} timestamp(s) för stad {city_name}, hoppar över dessa rader"
                    )
                    df = df[df['timestamp'].notna()]
                if df.empty:
                    logger.info(f"Ingen giltig data efter timestamp-parsing för stad {city_name}")
                    return None
                if df['timestamp'].dt.tz is None:
                    df['timestamp'] = df['timestamp'].dt.tz_localize(CET)
                elif df['timestamp'].dt.tz != CET:
                    df['timestamp'] = df['timestamp'].dt.tz_convert(CET)
            except Exception as e:
                logger.error(f"Fel vid timestamp-konvertering för stad {city_name}: {e}")
                return None

        # Get style parameters
        style = self._get_plot_style_params()

        # Use mode if provided, otherwise default behavior
        if mode is not None:
            widget = self._generate_plot_with_mode(df, mode, city_name, available_params, selected_date)
            if widget is None:
                logger.info(f"Ingen data efter transformation för stad {city_name}")
                return None
        else:
            # Default behavior: one line per parameter using matplotlib
            first_ts = df['timestamp'].min() if not df.empty else None
            last_ts = df['timestamp'].max() if not df.empty else None
            if first_ts and last_ts:
                title = f"{city_name} - {first_ts} to {last_ts}"
            else:
                title = city_name
            
            widget = self._create_matplotlib_default_plot(df, available_params, title, style)
        
        # Generate filename with category and mode organization
        sanitized_city_name = self._sanitize_filename(city_name)
        if export_timestamp is None:
            export_timestamp = self._get_export_timestamp()
        
        # Organize by category and mode if provided
        if category:
            category_dir = self.output_dir / category
            category_dir.mkdir(parents=True, exist_ok=True)
            if mode:
                mode_dir = category_dir / mode.get_name()
                mode_dir.mkdir(parents=True, exist_ok=True)
                filename = f"{sanitized_city_name}_{export_timestamp}.png"
                filepath = mode_dir / filename
            else:
                filename = f"{sanitized_city_name}_{export_timestamp}.png"
                filepath = category_dir / filename
        elif mode:
            mode_dir = self.output_dir / mode.get_name()
            mode_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{sanitized_city_name}_{export_timestamp}.png"
            filepath = mode_dir / filename
        else:
            filename = f"{sanitized_city_name}_{export_timestamp}.png"
            filepath = self.output_dir / filename
        
        # Export using matplotlib
        self._export_matplotlib_figure(widget, filepath, style)
        
        logger.info(f"Graf genererad för {city_name}: {filepath}")
        return str(filepath)
    
    def generate_all_city_graphs(
        self,
        hours: Optional[int] = None,
        export_timestamp: Optional[str] = None,
        mode: Optional[BaseMode] = None,
        selected_date: Optional[date] = None,
        category: Optional[str] = None
    ) -> tuple:
        """
        Generate graphs for all cities.
        
        Args:
            hours: Optional hours to filter (None = ALL history)
            export_timestamp: Optional export timestamp (if None, generates new one)
            mode: Optional mode object for grouping
            selected_date: Optional date for modes that require it (e.g. DailyMode)
            category: Optional category to filter parameters ('weather', 'air_quality', 'solar', 'storm')
            
        Returns:
            Tuple of (list of file paths, export_timestamp used)
        """
        # Get all cities dynamically
        cities = self.db.get_all_cities()
        num_cities = len(cities)
        logger.info(
            f"Genererar grafer för alla städer: {num_cities} städer, hours={hours}, mode={mode}, selected_date={selected_date}, category={category}"
        )

        if not cities:
            logger.warning("Inga städer hittades")
            return ([], export_timestamp or self._get_export_timestamp())

        # Generate export timestamp (global for all graphs in this batch)
        if export_timestamp is None:
            export_timestamp = self._get_export_timestamp()

        # When using a date-based mode (e.g. Daily), export one file per city: real graph or placeholder
        export_placeholders = (
            mode is not None
            and mode.needs_date_selection()
            and selected_date is not None
        )

        filepaths = []
        for city in cities:
            city_id = city['id']
            city_name = city.get('name', 'Unknown')
            filepath = self.generate_city_graph(
                city_id,
                hours=hours,
                export_timestamp=export_timestamp,
                mode=mode,
                selected_date=selected_date,
                category=category
            )
            if filepath:
                filepaths.append(filepath)
            elif export_placeholders:
                # One export per city: add placeholder for "no data for this date"
                placeholder_path = self._export_placeholder_for_city(
                    city_name, selected_date, export_timestamp, mode, category
                )
                if placeholder_path:
                    filepaths.append(placeholder_path)

        skipped = num_cities - len(filepaths)
        if skipped > 0 and selected_date is not None and not export_placeholders:
            logger.info(
                f"Genererade {len(filepaths)} stadsgrafer; {skipped} städer hoppades över (ingen data för valt datum {selected_date})"
            )
        else:
            logger.info(f"Genererade {len(filepaths)} stadsgrafer (av {num_cities} städer)")
        return (filepaths, export_timestamp)
    
    def generate_category_graphs(
        self,
        category: str,
        mode: Optional[BaseMode] = None,
        selected_date: Optional[date] = None,
        hours: Optional[int] = None
    ) -> tuple:
        """
        Generate graphs for all cities, filtered by category.
        
        Args:
            category: Category name ('weather', 'air_quality', 'solar', 'storm', 'lightning')
            mode: Optional mode object for grouping
            selected_date: Optional date for modes that require it
            hours: Optional hours to filter (None = ALL history)
            
        Returns:
            Tuple of (list of file paths, export_timestamp used)
        """
        # Get parameters for category from parameter_registry
        category_params = self.db.get_parameters_by_category(category)
        if not category_params:
            logger.warning(f"Inga parametrar hittades för kategori '{category}'")
            return ([], self._get_export_timestamp())
        
        param_names = [p['parameter_name'] for p in category_params]
        logger.info(f"Genererar {category}-grafer för parametrar: {param_names}")
        
        # Generate with category filter
        return self.generate_all_city_graphs(
            hours=hours,
            mode=mode,
            selected_date=selected_date,
            category=category
        )
    
    def generate_national_graph(
        self,
        hours: Optional[int] = None,
        export_timestamp: Optional[str] = None,
        mode: Optional[BaseMode] = None,
        selected_date: Optional[date] = None,
        category: Optional[str] = None
    ) -> Optional[str]:
        """
        Generate national average graph.
        
        Args:
            hours: Optional hours to filter (None = ALL history)
            export_timestamp: Optional export timestamp (if None, generates new one)
            mode: Optional mode object for grouping (if None, uses default: one line per parameter)
            selected_date: Optional date for modes that require it (e.g. DailyMode)
            category: Optional category to filter parameters ('weather', 'air_quality', 'solar', 'storm', 'lightning')
            
        Returns:
            File path to generated graph, or None if no data
        """
        logger.info(f"Genererar nationell graf, hours={hours}, mode={mode}, selected_date={selected_date}, category={category}")
        
        # Special-hantering för nationell blixtgraf (lightning är event-baserad)
        if category == "lightning":
            lightning_hours = hours if hours is not None else 24
            try:
                events = self.db.get_lightning_events(city_id=None, hours=int(lightning_hours), max_distance_km=None)
            except Exception as e:
                logger.error(f"Fel vid hämtning av nationella lightning events: {e}")
                return None

            if not events:
                logger.info("Inga lightning events för nationell graf")
                return None

            df = pd.DataFrame(events)
            if "timestamp" not in df.columns:
                logger.warning("Ingen timestamp-kolumn i lightning events för nationell graf")
                return None

            try:
                parsed, num_failed = self._parse_timestamp_column(
                    df, "timestamp", logger_context="lightning events nationell graf"
                )
                df["timestamp"] = parsed
                if num_failed > 0:
                    logger.warning(
                        f"Kunde inte parsa {num_failed} timestamp(s) i lightning events för nationell graf, hoppar över dessa rader"
                    )
                    df = df[df["timestamp"].notna()]
                if df.empty:
                    logger.info("Inga giltiga tidsstämplar i lightning events för nationell graf")
                    return None
                if df["timestamp"].dt.tz is None:
                    df["timestamp"] = df["timestamp"].dt.tz_localize(CET)
                elif df["timestamp"].dt.tz != CET:
                    df["timestamp"] = df["timestamp"].dt.tz_convert(CET)
            except Exception as e:
                logger.error(f"Fel vid timestamp-konvertering för nationella lightning events: {e}")
                return None

            lightning_params = [p for p in ["intensity", "distance_km"] if p in df.columns]
            if not lightning_params:
                logger.info("Inga numeriska lightning-parametrar att plotta för nationell graf")
                return None

            style = self._get_plot_style_params()

            first_ts = df["timestamp"].min()
            last_ts = df["timestamp"].max()
            title = f"Sweden Lightning – {first_ts} to {last_ts}"

            widget = self._create_matplotlib_default_plot(df, lightning_params, title, style)

            if export_timestamp is None:
                export_timestamp = self._get_export_timestamp()

            category_dir = self.output_dir / "lightning"
            category_dir.mkdir(parents=True, exist_ok=True)
            filename = f"sweden_{export_timestamp}.png"
            filepath = category_dir / filename

            self._export_matplotlib_figure(widget, filepath, style)
            logger.info(f"Nationell lightning-graf genererad: {filepath}")
            return str(filepath)
        
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
                parsed, num_failed = self._parse_timestamp_column(
                    df, 'timestamp', logger_context="nationell graf"
                )
                df['timestamp'] = parsed
                if num_failed > 0:
                    logger.warning(
                        f"Kunde inte parsa {num_failed} timestamp(s) för nationell graf, hoppar över dessa rader"
                    )
                    df = df[df['timestamp'].notna()]
                if df.empty:
                    logger.info("Ingen giltig data efter timestamp-parsing för nationell graf")
                    return None
                if df['timestamp'].dt.tz is None:
                    df['timestamp'] = df['timestamp'].dt.tz_localize(CET)
                elif df['timestamp'].dt.tz != CET:
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
        
        # Discover parameters from database schema dynamically
        all_parameters = self._discover_parameters_from_schema()
        
        if not all_parameters:
            logger.warning("No parameters discovered from schema for national graph")
            return None
        
        # Identify pollutant parameters dynamically (not hardcoded)
        # Pollutants are parameters that are NOT weather parameters (temperature, wind_speed, humidity)
        # This is derived from schema, not hardcoded
        weather_params = {'temperature', 'wind_speed', 'humidity'}
        pollutant_params = [p for p in all_parameters if p not in weather_params]
        
        # Filter out rows where ALL pollutant parameters are NULL
        # This improves data quality in national average by excluding rows with no pollutant data
        # Only filter if we have pollutant parameters in the data
        if pollutant_params and all(p in df.columns for p in pollutant_params):
            rows_before = len(df)
            # Keep rows where at least one pollutant has data
            df = df[df[pollutant_params].notna().any(axis=1)]
            rows_after = len(df)
            if rows_before > rows_after:
                filtered_count = rows_before - rows_after
                logger.info(f"National average: Filtrerade bort {filtered_count} rader utan pollutant-data (förbättrar datakvalitet)")
                logger.debug(f"National average: Pollutant-parametrar använda för filtrering: {pollutant_params}")
        elif pollutant_params:
            logger.debug(f"National average: Pollutant-parametrar {pollutant_params} finns inte i DataFrame-kolumner")
        
        if df.empty:
            logger.info("Ingen data med pollutant-värden för nationell graf")
            return None
        
        # Filter to only parameters that exist in DataFrame columns
        available_numeric_cols = [col for col in all_parameters if col in df.columns]
        
        # Filter by category if provided
        if category:
            category_params = self.db.get_parameters_by_category(category)
            if category_params:
                category_param_names = {p['parameter_name'] for p in category_params}
                before_count = len(available_numeric_cols)
                available_numeric_cols = [p for p in available_numeric_cols if p in category_param_names]
                logger.info(
                    f"[GRAPH DEBUG] National graph: category='{category}', "
                    f"registry_params={sorted(category_param_names)}, "
                    f"before_filter={before_count}, after_filter={len(available_numeric_cols)}"
                )
            else:
                logger.warning(
                    f"[GRAPH DEBUG] Inga parametrar hittades i parameter_registry för kategori '{category}' i national graph – "
                    f"använder alla upptäckta numeriska parametrar utan kategorifilter."
                )
        
        if not available_numeric_cols:
            logger.info("Inga numeriska kolumner för nationell graf")
            return None
        
        logger.info(f"National graph: Using {len(available_numeric_cols)} parameters: {available_numeric_cols}")
        
        # Step 1: Ensure one value per city per timestamp
        # Group by (city_id, timestamp) and take mean (handles duplicate timestamps per city)
        # This ensures each city contributes exactly one value per timestamp
        if 'city_id' not in df.columns:
            logger.error("city_id column missing from data - cannot calculate national average")
            return None
        
        city_timestamp_avg = df.groupby(['city_id', 'timestamp'])[available_numeric_cols].mean(numeric_only=True).reset_index()
        
        # Step 2: Group by timestamp and take mean across cities (equal weight per city)
        # This gives correct national average per timestamp where each city has equal weight
        grouped = city_timestamp_avg.groupby('timestamp')[available_numeric_cols].mean(numeric_only=True)
        
        # Step 3: Validation - check cities per timestamp
        cities_per_timestamp = city_timestamp_avg.groupby('timestamp')['city_id'].nunique()
        if len(cities_per_timestamp) > 0:
            min_cities = cities_per_timestamp.min()
            max_cities = cities_per_timestamp.max()
            mean_cities = cities_per_timestamp.mean()
            logger.info(f"National average: Cities per timestamp - min={min_cities}, max={max_cities}, mean={mean_cities:.1f}")
            
            # Warn if some timestamps have very few cities
            if min_cities < 2:
                logger.warning(f"Some timestamps have only {min_cities} city(ies) - national average may be unreliable")
            
            # Log distribution for debugging
            cities_distribution = cities_per_timestamp.value_counts().sort_index()
            logger.debug(f"Cities per timestamp distribution: {dict(cities_distribution)}")
        else:
            logger.warning("No valid timestamps after aggregation")
            return None
        
        # Store min_cities for final validation (will be checked after parameter discovery)
        min_cities_for_validation = min_cities
        
        # Get available parameters (those with at least one non-NaN value)
        # Handle missing data correctly: if a city has NULL for a parameter at timestamp t,
        # it's excluded from that parameter's average (pandas mean handles NaN automatically)
        available_params = []
        for param in available_numeric_cols:
            if param in grouped.columns:
                # Check if has at least one non-NaN value
                param_data = grouped[param].dropna()
                if not param_data.empty:
                    # Log data quality for this parameter
                    valid_timestamps = len(param_data)
                    total_timestamps = len(grouped)
                    coverage = (valid_timestamps / total_timestamps * 100) if total_timestamps > 0 else 0
                    logger.debug(f"National {param}: {valid_timestamps}/{total_timestamps} timestamps have data ({coverage:.1f}% coverage)")
                    available_params.append(param)
                else:
                    logger.debug(f"National {param}: No valid data (all NaN)")
        
        # Order parameters logically
        available_params = self._get_parameter_order(available_params)
        
        if not available_params:
            logger.info("Inga parametrar med data för nationell graf (alla värden är NaN)")
            return None
        
        # Final validation: ensure we have sufficient data quality
        # Require at least 1 city contributing to at least some timestamps
        if min_cities_for_validation < 1:
            logger.warning(f"National average has insufficient data quality (min cities per timestamp: {min_cities_for_validation})")
            return None
        
        # Get style parameters
        style = self._get_plot_style_params()
        
        # Use mode if provided, otherwise default behavior
        if mode is not None:
            # For national graph with mode, transform the grouped data
            df_for_mode = grouped.reset_index()
            df_transformed = mode.transform(df_for_mode, selected_date=selected_date)
            
            # Create widget with mode
            widget = self._generate_plot_with_mode(df_transformed, mode, "Sweden National Average", available_params, selected_date)
            if widget is None:
                logger.info("Ingen data efter transformation för nationell graf")
                return None
        else:
            # Default behavior: one line per parameter using matplotlib
            first_ts = grouped.index[0]
            last_ts = grouped.index[-1]
            title = f"Sweden National Average - {first_ts} to {last_ts}"
            
            # Convert grouped DataFrame to format expected by _create_matplotlib_default_plot
            # grouped has timestamp as index, need to reset and rename
            df_for_plot = grouped.reset_index()
            df_for_plot.rename(columns={'timestamp': 'timestamp'}, inplace=True)
            
            widget = self._create_matplotlib_default_plot(df_for_plot, available_params, title, style)
        
        # Generate filename
        if export_timestamp is None:
            export_timestamp = self._get_export_timestamp()
        # Organize by category and mode if provided
        if category:
            category_dir = self.output_dir / category
            category_dir.mkdir(parents=True, exist_ok=True)
            if mode:
                mode_dir = category_dir / mode.get_name()
                mode_dir.mkdir(parents=True, exist_ok=True)
                filename = f"sweden_{export_timestamp}.png"
                filepath = mode_dir / filename
            else:
                filename = f"sweden_{export_timestamp}.png"
                filepath = category_dir / filename
        elif mode:
            mode_dir = self.output_dir / mode.get_name()
            mode_dir.mkdir(parents=True, exist_ok=True)
            filename = f"sweden_{export_timestamp}.png"
            filepath = mode_dir / filename
        else:
            filename = f"sweden_{export_timestamp}.png"
            filepath = self.output_dir / filename
        
        # Export using matplotlib
        self._export_matplotlib_figure(widget, filepath, style)
        
        logger.info(f"Nationell graf genererad: {filepath}")
        return str(filepath)
