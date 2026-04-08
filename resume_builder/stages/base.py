"""Base stage class for the 3-stage LLM pipeline."""

import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from resume_builder.config import Config
from resume_builder.services import ClaudeCLIService


class StageResult:
    """Result from a stage execution."""

    def __init__(
        self,
        success: bool,
        output: str,
        output_file: Optional[Path] = None,
        elapsed_seconds: float = 0.0,
        metadata: Optional[dict] = None,
    ):
        self.success = success
        self.output = output
        self.output_file = output_file
        self.elapsed_seconds = elapsed_seconds
        self.metadata = metadata or {}


class BaseStage(ABC):
    """Abstract base class for pipeline stages."""

    stage_name: str = "Base Stage"
    stage_number: int = 0

    def __init__(self, config: Config, output_dir: Path):
        self.config = config
        self.output_dir = output_dir
        self.logger = logging.getLogger(self.__class__.__name__)

        self.service = ClaudeCLIService(
            timeout_seconds=config.claude_cli.timeout_seconds,
            max_retries=config.claude_cli.max_retries,
            retry_on_failure=config.claude_cli.retry_on_failure,
            working_dir=output_dir.parent,
        )

    @abstractmethod
    def build_system_prompt(self) -> str:
        """Build the system prompt for this stage."""
        pass

    @abstractmethod
    def build_user_prompt(self, **kwargs: Any) -> str:
        """Build the user prompt with context for this stage."""
        pass

    @abstractmethod
    def get_output_filename(self) -> str:
        """Get the output filename for this stage."""
        pass

    def execute(self, **kwargs: Any) -> StageResult:
        """
        Execute the stage.

        Args:
            **kwargs: Stage-specific arguments

        Returns:
            StageResult with output and metadata
        """
        self.logger.info(f"Starting {self.stage_name}")
        start_time = time.time()

        try:
            system_prompt = self.build_system_prompt()
            user_prompt = self.build_user_prompt(**kwargs)

            from resume_builder.services import build_prompt

            full_prompt = build_prompt(system_prompt, user_prompt)

            self.logger.debug("Sending prompt to Claude CLI...")
            response = self.service.complete(full_prompt)

            output_file = self.save_output(response)

            elapsed = time.time() - start_time
            self.logger.info(f"Completed {self.stage_name} in {elapsed:.2f}s")

            return StageResult(
                success=True,
                output=response,
                output_file=output_file,
                elapsed_seconds=elapsed,
                metadata={"stage": self.stage_name, "stage_number": self.stage_number},
            )

        except Exception as e:
            elapsed = time.time() - start_time
            self.logger.error(f"{self.stage_name} failed: {e}")

            return StageResult(
                success=False,
                output=str(e),
                elapsed_seconds=elapsed,
                metadata={
                    "stage": self.stage_name,
                    "stage_number": self.stage_number,
                    "error": str(e),
                },
            )

    def save_output(self, content: str) -> Path:
        """Save stage output to file."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        output_file = self.output_dir / self.get_output_filename()
        output_file.write_text(content)

        self.logger.info(f"Saved output to: {output_file}")
        return output_file

    def load_file(self, file_path: Path) -> str:
        """Load content from a file."""
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        return file_path.read_text()
