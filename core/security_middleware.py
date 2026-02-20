"""Complete security validation for custom API providers."""

import ipaddress
import socket
from urllib.parse import urlparse
from typing import Optional


class SecurityMiddleware:
    """Complete security validation for custom API providers."""
    
    MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10MB
    TIMEOUT_SECONDS = 30
    MAX_REDIRECTS = 5
    ALLOWED_SCHEMES = ['https']
    BLOCKED_HOSTNAMES = ['127.0.0.1', 'localhost', '0.0.0.0', '::1']
    
    def validate_url(self, url: str) -> tuple[bool, Optional[str]]:
        """
        Validate URL is safe.
        
        Args:
            url: URL to validate
            
        Returns:
            (is_valid, error_message)
        """
        try:
            parsed = urlparse(url)
            
            # Check scheme
            if parsed.scheme not in self.ALLOWED_SCHEMES:
                return False, f"Scheme {parsed.scheme} not allowed (only HTTPS)"
            
            # Check hostname exists
            if not parsed.hostname:
                return False, "No hostname in URL"
            
            # Check blocked hostnames
            if parsed.hostname.lower() in self.BLOCKED_HOSTNAMES:
                return False, f"Hostname {parsed.hostname} is blocked"
            
            # Check private IPv4
            if self._is_private_ipv4(parsed.hostname):
                return False, f"Hostname {parsed.hostname} is private IPv4"
            
            # Check private IPv6
            if self._is_private_ipv6(parsed.hostname):
                return False, f"Hostname {parsed.hostname} is private IPv6"
            
            # DNS rebinding protection: resolve and check
            resolved_ip = self._resolve_hostname(parsed.hostname)
            if resolved_ip:
                if self._is_private_ipv4(resolved_ip) or self._is_private_ipv6(resolved_ip):
                    return False, f"Hostname {parsed.hostname} resolves to private IP {resolved_ip}"
            
            return True, None
        except Exception as e:
            return False, f"URL validation error: {e}"
    
    def _is_private_ipv4(self, hostname: str) -> bool:
        """Check if hostname is private IPv4."""
        try:
            ip = ipaddress.IPv4Address(hostname)
            return ip.is_private or ip.is_loopback or ip.is_link_local
        except (ValueError, ipaddress.AddressValueError):
            return False
    
    def _is_private_ipv6(self, hostname: str) -> bool:
        """Check if hostname is private IPv6."""
        try:
            ip = ipaddress.IPv6Address(hostname)
            return ip.is_private or ip.is_loopback or ip.is_link_local
        except (ValueError, ipaddress.AddressValueError):
            return False
    
    def _resolve_hostname(self, hostname: str) -> Optional[str]:
        """Resolve hostname to IP (for DNS rebinding protection)."""
        try:
            # Resolve to IP
            ip = socket.gethostbyname(hostname)
            return ip
        except (socket.gaierror, socket.herror, OSError):
            return None
    
    def validate_redirect(self, redirect_url: str, redirect_count: int) -> tuple[bool, Optional[str]]:
        """
        Validate redirect URL and check redirect limit.
        
        Args:
            redirect_url: URL to redirect to
            redirect_count: Current redirect count
            
        Returns:
            (is_valid, error_message)
        """
        if redirect_count >= self.MAX_REDIRECTS:
            return False, f"Max redirects ({self.MAX_REDIRECTS}) exceeded"
        
        return self.validate_url(redirect_url)
    
    def validate_response_size(self, content_length: Optional[int]) -> tuple[bool, Optional[str]]:
        """
        Validate response size.
        
        Args:
            content_length: Content-Length header value
            
        Returns:
            (is_valid, error_message)
        """
        if content_length and content_length > self.MAX_RESPONSE_SIZE:
            return False, f"Response size {content_length} exceeds max {self.MAX_RESPONSE_SIZE}"
        return True, None
