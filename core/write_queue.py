"""Batched write queue to reduce SQLite contention."""

import asyncio
from typing import List, Dict, Optional
from database.db_manager import DatabaseManager
import logging

logger = logging.getLogger("WeatherApp.core.write_queue")


class WriteQueue:
    """Batched write queue to reduce SQLite contention."""
    
    def __init__(self, db: DatabaseManager, batch_size: int = 50, flush_interval: float = 5.0):
        """
        Initialize write queue.
        
        Args:
            db: Database manager
            batch_size: Number of writes before flush
            flush_interval: Seconds between automatic flushes
        """
        self.db = db
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.readings_queue: List[Dict] = []
        self.sensor_updates_queue: List[Dict] = []
        self._lock = asyncio.Lock()
        self.running = False
        self._flush_task: Optional[asyncio.Task] = None
    
    def start(self):
        """Start write queue worker."""
        if not self.running:
            self.running = True
            loop = asyncio.get_event_loop()
            self._flush_task = loop.create_task(self._periodic_flush())
            logger.info("Write queue started")
    
    def stop(self):
        """Stop write queue and flush remaining."""
        self.running = False
        if self._flush_task:
            self._flush_task.cancel()
        # Flush remaining synchronously
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(self._flush())
        else:
            loop.run_until_complete(self._flush())
        logger.info("Write queue stopped")
    
    async def enqueue_reading(self, sensor_id: int, value: float, parameter: str, timestamp):
        """
        Enqueue sensor reading for batched write.
        
        Args:
            sensor_id: Sensor ID
            value: Reading value
            parameter: Parameter name
            timestamp: Reading timestamp
        """
        async with self._lock:
            self.readings_queue.append({
                'sensor_id': sensor_id,
                'value': value,
                'parameter': parameter,
                'timestamp': timestamp
            })
            
            # Flush if batch size reached
            if len(self.readings_queue) >= self.batch_size:
                await self._flush_readings()
    
    async def enqueue_sensor_update(self, sensor_id: int, last_value: float, last_updated):
        """
        Enqueue sensor update for batched write.
        
        Args:
            sensor_id: Sensor ID
            last_value: Last value
            last_updated: Last updated timestamp
        """
        async with self._lock:
            self.sensor_updates_queue.append({
                'sensor_id': sensor_id,
                'last_value': last_value,
                'last_updated': last_updated
            })
            
            # Flush if batch size reached
            if len(self.sensor_updates_queue) >= self.batch_size:
                await self._flush_sensor_updates()
    
    async def _periodic_flush(self):
        """Periodically flush queues."""
        while self.running:
            try:
                await asyncio.sleep(self.flush_interval)
                await self._flush()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic flush: {e}")
    
    async def _flush(self):
        """Flush all queues."""
        await self._flush_readings()
        await self._flush_sensor_updates()
    
    async def _flush_readings(self):
        """Flush readings queue to database."""
        async with self._lock:
            if not self.readings_queue:
                return
            
            batch = self.readings_queue[:self.batch_size]
            self.readings_queue = self.readings_queue[self.batch_size:]
        
        # Execute outside lock to avoid blocking
        if batch:
            try:
                # Run in executor to avoid blocking event loop
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.db.batch_add_sensor_readings, batch)
                logger.debug(f"Flushed {len(batch)} sensor readings")
            except Exception as e:
                logger.error(f"Error flushing readings: {e}")
    
    async def _flush_sensor_updates(self):
        """Flush sensor updates queue to database."""
        async with self._lock:
            if not self.sensor_updates_queue:
                return
            
            batch = self.sensor_updates_queue[:self.batch_size]
            self.sensor_updates_queue = self.sensor_updates_queue[self.batch_size:]
        
        # Execute outside lock to avoid blocking
        if batch:
            try:
                # Run in executor to avoid blocking event loop
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.db.batch_update_sensor_last_values, batch)
                logger.debug(f"Flushed {len(batch)} sensor updates")
            except Exception as e:
                logger.error(f"Error flushing sensor updates: {e}")
