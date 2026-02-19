"""Rate limiter for API requests."""

import time
from typing import Optional, Dict
from collections import deque
from threading import Lock


class RateLimiter:
    """Rate limiter to prevent exceeding API rate limits."""
    
    def __init__(self, requests_per_minute: int = 60, requests_per_hour: int = 2000):
        """
        Initialize rate limiter.
        
        Args:
            requests_per_minute: Maximum requests per minute
            requests_per_hour: Maximum requests per hour
        """
        self.requests_per_minute = requests_per_minute
        self.requests_per_hour = requests_per_hour
        
        # Track request timestamps
        self.minute_requests = deque()  # Timestamps of requests in last minute
        self.hour_requests = deque()    # Timestamps of requests in last hour
        
        # Thread safety
        self.lock = Lock()
        
        # Rate limit info from API headers
        self.rate_limit_info = {
            'used': 0,
            'remaining': requests_per_minute,
            'limit': requests_per_minute,
            'reset_time': None
        }
    
    def wait_if_needed(self) -> float:
        """
        Wait if necessary to avoid exceeding rate limits.
        
        Returns:
            Time waited in seconds
        """
        with self.lock:
            now = time.time()
            wait_time = 0.0
            
            # Clean old requests outside time windows
            self._clean_old_requests(now)
            
            # Check minute limit
            if len(self.minute_requests) >= self.requests_per_minute:
                # Wait until oldest request is 60 seconds old
                oldest = self.minute_requests[0]
                wait_until = oldest + 60.0
                if wait_until > now:
                    wait_time = wait_until - now
                    time.sleep(wait_time)
                    now = time.time()
                    self._clean_old_requests(now)
            
            # Check hour limit
            if len(self.hour_requests) >= self.requests_per_hour:
                # Wait until oldest request is 3600 seconds old
                oldest = self.hour_requests[0]
                wait_until = oldest + 3600.0
                if wait_until > now:
                    wait_time = max(wait_time, wait_until - now)
                    time.sleep(wait_time)
                    now = time.time()
                    self._clean_old_requests(now)
            
            return wait_time
    
    def record_request(self):
        """Record that a request was made."""
        with self.lock:
            now = time.time()
            self.minute_requests.append(now)
            self.hour_requests.append(now)
    
    def update_from_headers(self, headers: Dict):
        """
        Update rate limit info from API response headers.
        
        Args:
            headers: Response headers dictionary
        """
        with self.lock:
            # Parse rate limit headers (case-insensitive)
            header_dict = {k.lower(): v for k, v in headers.items()}
            
            if 'x-ratelimit-used' in header_dict:
                try:
                    self.rate_limit_info['used'] = int(header_dict['x-ratelimit-used'])
                except (ValueError, TypeError):
                    pass
            
            if 'x-ratelimit-remaining' in header_dict:
                try:
                    self.rate_limit_info['remaining'] = int(header_dict['x-ratelimit-remaining'])
                except (ValueError, TypeError):
                    pass
            
            if 'x-ratelimit-limit' in header_dict:
                try:
                    self.rate_limit_info['limit'] = int(header_dict['x-ratelimit-limit'])
                except (ValueError, TypeError):
                    pass
            
            if 'x-ratelimit-reset' in header_dict:
                try:
                    reset_seconds = int(header_dict['x-ratelimit-reset'])
                    self.rate_limit_info['reset_time'] = time.time() + reset_seconds
                except (ValueError, TypeError):
                    pass
    
    def get_status(self) -> Dict:
        """
        Get current rate limit status.
        
        Returns:
            Dictionary with rate limit information
        """
        with self.lock:
            now = time.time()
            self._clean_old_requests(now)
            
            return {
                'requests_last_minute': len(self.minute_requests),
                'requests_last_hour': len(self.hour_requests),
                'limit_per_minute': self.requests_per_minute,
                'limit_per_hour': self.requests_per_hour,
                'remaining_per_minute': max(0, self.requests_per_minute - len(self.minute_requests)),
                'remaining_per_hour': max(0, self.requests_per_hour - len(self.hour_requests)),
                'api_used': self.rate_limit_info['used'],
                'api_remaining': self.rate_limit_info['remaining'],
                'api_limit': self.rate_limit_info['limit'],
                'api_reset_time': self.rate_limit_info['reset_time']
            }
    
    def _clean_old_requests(self, now: float):
        """Remove requests older than time windows."""
        # Remove requests older than 60 seconds
        while self.minute_requests and (now - self.minute_requests[0]) > 60.0:
            self.minute_requests.popleft()
        
        # Remove requests older than 3600 seconds
        while self.hour_requests and (now - self.hour_requests[0]) > 3600.0:
            self.hour_requests.popleft()
    
    def should_wait(self) -> bool:
        """
        Check if we should wait before making a request.
        
        Returns:
            True if we should wait
        """
        with self.lock:
            now = time.time()
            self._clean_old_requests(now)
            
            # Check if we're close to limits (use 80% threshold)
            minute_threshold = int(self.requests_per_minute * 0.8)
            hour_threshold = int(self.requests_per_hour * 0.8)
            
            if len(self.minute_requests) >= minute_threshold:
                return True
            
            if len(self.hour_requests) >= hour_threshold:
                return True
            
            # Check API headers if available
            if self.rate_limit_info['remaining'] is not None:
                remaining = self.rate_limit_info['remaining']
                limit = self.rate_limit_info['limit']
                if limit > 0 and remaining / limit < 0.2:  # Less than 20% remaining
                    return True
            
            return False
