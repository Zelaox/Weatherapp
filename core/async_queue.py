"""Async queue for sensor processing with concurrency limiting."""

import asyncio
from asyncio import Queue, Semaphore
from typing import Optional
from core.data_pipeline import DataPipeline
import logging

logger = logging.getLogger("WeatherApp.core.async_queue")


class AsyncSensorQueue:
    """Async queue for sensor processing with concurrency limiting."""
    
    def __init__(self, data_pipeline: DataPipeline, max_concurrent: int = 10):
        """
        Initialize async queue.
        
        Args:
            data_pipeline: Data pipeline instance
            max_concurrent: Maximum concurrent sensor fetches
        """
        self.data_pipeline = data_pipeline
        self.queue: Queue = Queue()
        self.semaphore = Semaphore(max_concurrent)
        self.running = False
        self._worker_task: Optional[asyncio.Task] = None
    
    def start(self):
        """Start queue worker."""
        if not self.running:
            self.running = True
            loop = asyncio.get_event_loop()
            self._worker_task = loop.create_task(self._worker())
            logger.info(f"Async sensor queue started (max concurrent: {self.semaphore._value})")
    
    def stop(self):
        """Stop queue worker."""
        self.running = False
        if self._worker_task:
            self._worker_task.cancel()
        logger.info("Async sensor queue stopped")
    
    async def enqueue(self, sensor_id: int):
        """
        Enqueue sensor for processing.
        
        Args:
            sensor_id: Sensor ID to process
        """
        await self.queue.put(sensor_id)
        logger.debug(f"Enqueued sensor {sensor_id}")
    
    async def _worker(self):
        """Worker coroutine that processes queued sensors."""
        while self.running:
            try:
                sensor_id = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                
                # Process with semaphore (concurrency limit)
                asyncio.create_task(self._process_with_limit(sensor_id))
                
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in queue worker: {e}")
    
    async def _process_with_limit(self, sensor_id: int):
        """Process sensor with concurrency limit."""
        async with self.semaphore:
            try:
                await self.data_pipeline.process_sensor(sensor_id)
            except Exception as e:
                # Log error but don't crash worker
                logger.error(f"Error processing sensor {sensor_id}: {e}")
            finally:
                self.queue.task_done()
