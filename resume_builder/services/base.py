"""Base service classes and exceptions for resume builder."""

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Optional


class ServiceError(Exception):
    """Base exception for service errors."""

    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ServiceTimeoutError(ServiceError):
    """Raised when a service operation times out."""

    pass


class ServiceValidationError(ServiceError):
    """Raised when service configuration is invalid."""

    pass


class ServiceExecutionError(ServiceError):
    """Raised when service execution fails."""

    pass


class BaseService(ABC):
    """Abstract base class for LLM services."""

    def __init__(
        self,
        timeout_seconds: int = 300,
        max_retries: int = 2,
        retry_on_failure: bool = True,
    ):
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_on_failure = retry_on_failure
        self.logger = logging.getLogger(self.__class__.__name__)

    @abstractmethod
    def _validate_config(self) -> None:
        """Validate service configuration. Raises ServiceValidationError if invalid."""
        pass

    @abstractmethod
    def _execute(self, prompt: str, **kwargs: Any) -> str:
        """Execute the service call. Returns response string."""
        pass

    def complete(self, prompt: str, **kwargs: Any) -> str:
        """
        Execute prompt with retry logic.

        Args:
            prompt: The prompt to send to the LLM
            **kwargs: Additional arguments for the service

        Returns:
            Response string from the LLM

        Raises:
            ServiceError: If all retries fail
        """
        self._validate_config()

        last_error: Optional[Exception] = None
        attempts = self.max_retries + 1 if self.retry_on_failure else 1

        for attempt in range(1, attempts + 1):
            try:
                self.logger.debug(f"Attempt {attempt}/{attempts}")
                start_time = time.time()

                response = self._execute(prompt, **kwargs)

                elapsed = time.time() - start_time
                self.logger.info(f"Completed in {elapsed:.2f}s")

                return response

            except ServiceTimeoutError:
                last_error = ServiceTimeoutError(
                    f"Timeout after {self.timeout_seconds}s",
                    {"attempt": attempt, "timeout": self.timeout_seconds},
                )
                self.logger.warning(f"Attempt {attempt} timed out")

            except Exception as e:
                last_error = ServiceExecutionError(
                    f"Execution failed: {e}",
                    {"attempt": attempt, "error": str(e)},
                )
                self.logger.warning(f"Attempt {attempt} failed: {e}")

            if attempt < attempts:
                wait_time = 2**attempt
                self.logger.info(f"Retrying in {wait_time}s...")
                time.sleep(wait_time)

        raise last_error or ServiceExecutionError("All attempts failed")
