"""
connection_pool.py – HTTP connection pool, retry policy, and reconnection manager.

Provides optimized HTTP communication with llama-server:
- ConnectionPool: Reuses persistent HTTP connections with keep-alive
- RetryPolicy: Exponential backoff for 503 (busy) responses
- ReconnectionManager: Auto-reconnect on connection loss

Uses http.client for persistent connections consistent with the existing backend.
"""
from __future__ import annotations

import http.client
import json
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from .logger import get_logger

logger = get_logger("connection_pool")


# ── Connection Pool ───────────────────────────────────────────────────────────


class ConnectionPool:
    """
    HTTP connection pool for llama-server communication.

    Maintains a pool of persistent HTTP connections with keep-alive support.
    When the pool is exhausted, callers queue until a connection is released.

    Args:
        base_url: Base URL of the llama-server (e.g., "http://127.0.0.1:8080")
        max_connections: Maximum number of concurrent connections (default 4)
        keep_alive: Whether to use persistent connections (default True)
        timeout: Default connection timeout in seconds (default 600)
    """

    def __init__(
        self,
        base_url: str,
        max_connections: int = 4,
        keep_alive: bool = True,
        timeout: int = 600,
    ):
        self._base_url = base_url
        self._max_connections = max_connections
        self._keep_alive = keep_alive
        self._timeout = timeout

        # Parse host and port from base_url
        self._host, self._port = self._parse_url(base_url)

        # Pool of available connections
        self._available: deque[http.client.HTTPConnection] = deque()
        # Count of connections currently checked out
        self._checked_out: int = 0
        # Lock for thread-safe pool access
        self._lock = threading.Lock()
        # Condition for waiting when pool is exhausted
        self._available_condition = threading.Condition(self._lock)

        logger.info(
            f"ConnectionPool initialized: {base_url}, "
            f"max_connections={max_connections}, keep_alive={keep_alive}"
        )

    @staticmethod
    def _parse_url(base_url: str) -> tuple[str, int]:
        """Extract host and port from a base URL string."""
        url = base_url.replace("http://", "").replace("https://", "")
        if ":" in url:
            host, port_str = url.split(":", 1)
            # Remove any trailing path
            port_str = port_str.split("/", 1)[0]
            return host, int(port_str)
        return url.split("/", 1)[0], 80

    @property
    def base_url(self) -> str:
        """The base URL this pool connects to."""
        return self._base_url

    @property
    def max_connections(self) -> int:
        """Maximum number of connections in the pool."""
        return self._max_connections

    @property
    def active_connections(self) -> int:
        """Number of connections currently checked out (in use)."""
        with self._lock:
            return self._checked_out

    @property
    def available_connections(self) -> int:
        """Number of idle connections available in the pool."""
        with self._lock:
            return len(self._available)

    def get_connection(self, timeout: float | None = None) -> http.client.HTTPConnection:
        """
        Acquire a connection from the pool.

        If the pool is exhausted (all connections checked out), this method
        blocks until a connection becomes available or the timeout expires.

        Args:
            timeout: Max seconds to wait for a connection. None = wait forever.

        Returns:
            An HTTPConnection ready for use.

        Raises:
            TimeoutError: If timeout expires while waiting for a connection.
        """
        with self._available_condition:
            deadline = time.time() + timeout if timeout is not None else None

            while True:
                # Try to get an existing idle connection
                if self._available:
                    conn = self._available.popleft()
                    self._checked_out += 1
                    logger.debug(
                        f"Connection acquired from pool "
                        f"(active={self._checked_out}, idle={len(self._available)})"
                    )
                    return conn

                # Create a new connection if under the limit
                if self._checked_out < self._max_connections:
                    conn = self._create_connection()
                    self._checked_out += 1
                    logger.debug(
                        f"New connection created "
                        f"(active={self._checked_out}, idle={len(self._available)})"
                    )
                    return conn

                # Pool exhausted — wait for a release
                if deadline is not None:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        raise TimeoutError(
                            f"Timed out waiting for connection "
                            f"(max={self._max_connections}, active={self._checked_out})"
                        )
                    self._available_condition.wait(timeout=remaining)
                else:
                    self._available_condition.wait()

    def release(self, conn: http.client.HTTPConnection) -> None:
        """
        Return a connection to the pool.

        If keep-alive is enabled, the connection is returned to the idle pool.
        Otherwise, it is closed.

        Args:
            conn: The connection to release back to the pool.
        """
        with self._available_condition:
            self._checked_out = max(0, self._checked_out - 1)

            if self._keep_alive and self._is_connection_alive(conn):
                self._available.append(conn)
                logger.debug(
                    f"Connection released to pool "
                    f"(active={self._checked_out}, idle={len(self._available)})"
                )
            else:
                # Connection is dead or keep-alive disabled — close it
                try:
                    conn.close()
                except Exception:
                    pass
                logger.debug(
                    f"Connection closed on release "
                    f"(active={self._checked_out}, idle={len(self._available)})"
                )

            # Notify any waiting threads
            self._available_condition.notify()

    def pre_warm(self) -> None:
        """
        Pre-warm the KV cache by sending an empty prompt with n_predict=1.

        This should be called after llama-server reports ready on its health
        endpoint. It sends a minimal request to initialize the KV cache so
        that subsequent requests start faster.
        """
        logger.info("Pre-warming KV cache...")
        payload = {
            "prompt": "",
            "n_predict": 1,
            "temperature": 0.0,
            "cache_prompt": True,
        }

        conn = None
        try:
            conn = self.get_connection(timeout=30)
            body = json.dumps(payload).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "Connection": "keep-alive",
            }
            conn.request("POST", "/completion", body=body, headers=headers)
            response = conn.getresponse()
            # Read and discard the response body
            response.read()
            logger.info(
                f"KV cache pre-warm complete (status={response.status})"
            )
        except Exception as e:
            logger.warn(f"KV cache pre-warm failed: {e}")
        finally:
            if conn is not None:
                self.release(conn)

    def close_all(self) -> None:
        """Close all idle connections in the pool."""
        with self._lock:
            while self._available:
                conn = self._available.popleft()
                try:
                    conn.close()
                except Exception:
                    pass
            logger.info("All idle connections closed")

    def _create_connection(self) -> http.client.HTTPConnection:
        """Create a new HTTP connection to the server."""
        conn = http.client.HTTPConnection(
            self._host, self._port, timeout=self._timeout
        )
        return conn

    @staticmethod
    def _is_connection_alive(conn: http.client.HTTPConnection) -> bool:
        """Check if a connection is still usable."""
        try:
            # A connection is considered alive if its socket exists
            return conn.sock is not None
        except Exception:
            return False


# ── Retry Policy ──────────────────────────────────────────────────────────────


class RetryPolicy:
    """
    Exponential backoff retry policy for 503 (busy) responses.

    Retries a request function with delays of 1s, 2s, 4s (doubling each time)
    for a maximum of 3 attempts before raising the error.

    Args:
        max_retries: Maximum number of retry attempts (default 3)
        initial_delay: Initial delay in seconds before first retry (default 1.0)
        backoff_factor: Multiplier for each subsequent delay (default 2.0)
        retryable_statuses: HTTP status codes that trigger a retry (default [503])
    """

    MAX_RETRIES = 3
    INITIAL_DELAY = 1.0
    BACKOFF_FACTOR = 2.0

    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        backoff_factor: float = 2.0,
        retryable_statuses: list[int] | None = None,
    ):
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.backoff_factor = backoff_factor
        self.retryable_statuses = retryable_statuses or [503]

    def execute_with_retry(self, request_fn: Callable[[], Any]) -> Any:
        """
        Execute a request function with retry on retryable errors.

        The request_fn should raise `RetryableError` with the HTTP status code
        when a retryable response is received, or return the result on success.

        Args:
            request_fn: A callable that performs the HTTP request and returns
                        the result. Should raise RetryableError for 503 responses.

        Returns:
            The result from request_fn on success.

        Raises:
            RetryableError: If all retry attempts are exhausted.
            Exception: Any non-retryable error from request_fn.
        """
        delay = self.initial_delay
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                result = request_fn()
                if attempt > 0:
                    logger.info(
                        f"Request succeeded on attempt {attempt + 1} "
                        f"after {self.max_retries} retries"
                    )
                return result
            except RetryableError as e:
                last_error = e
                if attempt < self.max_retries:
                    logger.warn(
                        f"Retryable error (status={e.status_code}), "
                        f"attempt {attempt + 1}/{self.max_retries + 1}, "
                        f"retrying in {delay:.1f}s..."
                    )
                    time.sleep(delay)
                    delay *= self.backoff_factor
                else:
                    logger.error(
                        f"All {self.max_retries + 1} attempts exhausted "
                        f"(last status={e.status_code})"
                    )

        # All retries exhausted
        raise last_error  # type: ignore[misc]

    def get_delay_sequence(self) -> list[float]:
        """Return the sequence of delays that would be used for retries."""
        delays = []
        delay = self.initial_delay
        for _ in range(self.max_retries):
            delays.append(delay)
            delay *= self.backoff_factor
        return delays


class RetryableError(Exception):
    """
    Exception indicating a retryable HTTP error.

    Raised when the server returns a status code that should trigger a retry
    (e.g., 503 Service Unavailable when llama-server is busy).
    """

    def __init__(self, message: str, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


# ── Reconnection Manager ─────────────────────────────────────────────────────


class ReconnectionManager:
    """
    Auto-reconnect on connection loss.

    Polls the server health endpoint at regular intervals until the server
    becomes available again or the maximum wait time is exceeded.

    Args:
        poll_interval: Seconds between health check polls (default 5)
        max_wait: Maximum seconds to wait for reconnection (default 60)
    """

    POLL_INTERVAL = 5  # seconds
    MAX_WAIT = 60  # seconds

    def __init__(
        self,
        poll_interval: int = 5,
        max_wait: int = 60,
    ):
        self.poll_interval = poll_interval
        self.max_wait = max_wait

    def wait_for_server(self, health_url: str) -> bool:
        """
        Poll the health endpoint until the server responds or timeout.

        Args:
            health_url: Full URL to the health endpoint
                        (e.g., "http://127.0.0.1:8080/health")

        Returns:
            True if the server became available within max_wait seconds.
            False if the timeout was reached without a successful response.
        """
        logger.info(
            f"Waiting for server at {health_url} "
            f"(poll every {self.poll_interval}s, max {self.max_wait}s)..."
        )
        start_time = time.time()
        attempts = 0

        while (time.time() - start_time) < self.max_wait:
            attempts += 1
            if self._check_health(health_url):
                elapsed = time.time() - start_time
                logger.info(
                    f"Server reconnected after {elapsed:.1f}s "
                    f"({attempts} attempts)"
                )
                return True

            # Calculate remaining time to avoid overshooting max_wait
            elapsed = time.time() - start_time
            remaining = self.max_wait - elapsed
            if remaining <= 0:
                break

            # Sleep for poll_interval or remaining time, whichever is shorter
            sleep_time = min(self.poll_interval, remaining)
            time.sleep(sleep_time)

        elapsed = time.time() - start_time
        logger.error(
            f"Server reconnection timed out after {elapsed:.1f}s "
            f"({attempts} attempts)"
        )
        return False

    @staticmethod
    def _check_health(health_url: str) -> bool:
        """
        Check if the server health endpoint responds successfully.

        Args:
            health_url: Full URL to the health endpoint.

        Returns:
            True if the server responds with a 2xx status code.
        """
        try:
            req = urllib.request.Request(health_url, method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                return 200 <= resp.status < 300
        except Exception:
            return False


# ── Factory helpers ───────────────────────────────────────────────────────────


def create_pool_for_agent(base_url: str, timeout: int = 600) -> ConnectionPool:
    """
    Create a connection pool sized for agent use (max 2 connections).

    Per requirement 1.3: agent connections limited to 2 persistent connections.

    Args:
        base_url: Base URL of the llama-server.
        timeout: Connection timeout in seconds.

    Returns:
        A ConnectionPool configured for agent use.
    """
    return ConnectionPool(
        base_url=base_url,
        max_connections=2,
        keep_alive=True,
        timeout=timeout,
    )


def create_pool_general(base_url: str, timeout: int = 600) -> ConnectionPool:
    """
    Create a general-purpose connection pool (max 4 connections).

    Per requirement 13.1: up to 4 concurrent connections per server endpoint.

    Args:
        base_url: Base URL of the llama-server.
        timeout: Connection timeout in seconds.

    Returns:
        A ConnectionPool configured for general use.
    """
    return ConnectionPool(
        base_url=base_url,
        max_connections=4,
        keep_alive=True,
        timeout=timeout,
    )
