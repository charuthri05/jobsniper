"""Claude CLI service for LLM interactions."""

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from resume_builder.services.base import (
    BaseService,
    ServiceExecutionError,
    ServiceTimeoutError,
    ServiceValidationError,
)

# Try to import anthropic SDK for API key fallback
try:
    import anthropic
    HAS_ANTHROPIC_SDK = True
except ImportError:
    HAS_ANTHROPIC_SDK = False


def build_prompt(system: str, user: str) -> str:
    """
    Build a structured prompt combining system and user messages.

    Args:
        system: System prompt setting context and instructions
        user: User prompt with the actual request

    Returns:
        Combined prompt string
    """
    return f"System: {system}\n\nUser: {user}"


def extract_code_block(response: str, language: str = "") -> Optional[str]:
    """
    Extract content from a markdown code block.

    Args:
        response: Full response text
        language: Optional language identifier (e.g., 'latex', 'json')

    Returns:
        Content inside the code block, or None if not found
    """
    pattern = rf"```{language}\s*(.*?)\s*```"
    match = re.search(pattern, response, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


def extract_section(response: str, section_name: str) -> Optional[str]:
    """
    Extract a named section from structured output.

    Looks for patterns like:
    SECTION_NAME:
    content here...

    Args:
        response: Full response text
        section_name: Name of section to extract (e.g., 'LINQ_REWRITE_PLAN')

    Returns:
        Section content, or None if not found
    """
    pattern = rf"^{section_name}:\s*\n(.*?)(?=\n[A-Z_]+:|$)"
    match = re.search(pattern, response, re.MULTILINE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


class ClaudeCLIService(BaseService):
    """
    Claude CLI wrapper service.

    Uses `claude -p` for non-interactive prompt execution with OAuth authentication.
    Falls back to Anthropic API SDK when ANTHROPIC_API_KEY is set (for Docker/CI).
    $0 cost via Claude subscription (CLI mode), pay-per-use via API key.
    """

    def __init__(
        self,
        timeout_seconds: int = 300,
        max_retries: int = 2,
        retry_on_failure: bool = True,
        working_dir: Optional[Path] = None,
    ):
        super().__init__(timeout_seconds, max_retries, retry_on_failure)
        self.working_dir = working_dir or Path.cwd()
        self._claude_path: Optional[str] = None
        self._use_api_mode = False
        self._api_client: Optional[Any] = None

    def _validate_config(self) -> None:
        """Validate Claude CLI or API key is available."""
        # Check for API key first (preferred for Docker/headless)
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key and HAS_ANTHROPIC_SDK:
            self._use_api_mode = True
            self._api_client = anthropic.Anthropic(api_key=api_key)
            self.logger.info("Using Anthropic API mode (ANTHROPIC_API_KEY detected)")
            return

        # Fall back to Claude CLI
        claude_path = shutil.which("claude")
        if not claude_path:
            raise ServiceValidationError(
                "Neither ANTHROPIC_API_KEY nor Claude CLI found. "
                "Set ANTHROPIC_API_KEY or install CLI with: npm install -g @anthropic-ai/claude-code",
                {"checked_path": "claude", "api_key_set": bool(api_key)},
            )
        self._claude_path = claude_path
        self.logger.debug(f"Found Claude CLI at: {claude_path}")

    def _execute(self, prompt: str, **kwargs: Any) -> str:
        """
        Execute Claude with the given prompt (via API or CLI).

        Args:
            prompt: The prompt to send
            **kwargs:
                add_dirs: List of directories to grant file access (CLI only)
                model: Optional model override

        Returns:
            Response text from Claude
        """
        if self._use_api_mode:
            return self._execute_api(prompt, **kwargs)
        return self._execute_cli(prompt, **kwargs)

    def _execute_api(self, prompt: str, **kwargs: Any) -> str:
        """Execute via Anthropic API SDK."""
        model = kwargs.get("model", "claude-sonnet-4-20250514")

        try:
            message = self._api_client.messages.create(
                model=model,
                max_tokens=8192,
                messages=[{"role": "user", "content": prompt}],
            )

            response = message.content[0].text.strip()
            if not response:
                raise ServiceExecutionError(
                    "Anthropic API returned empty response",
                    {"message": message},
                )
            return response

        except anthropic.APITimeoutError:
            raise ServiceTimeoutError(
                f"Anthropic API timed out after {self.timeout_seconds}s",
                {"timeout": self.timeout_seconds},
            )
        except anthropic.APIError as e:
            raise ServiceExecutionError(
                f"Anthropic API error: {e}",
                {"error": str(e)},
            )

    def _execute_cli(self, prompt: str, **kwargs: Any) -> str:
        """Execute via Claude CLI."""
        cmd = [self._claude_path, "-p"]

        add_dirs = kwargs.get("add_dirs", [self.working_dir])
        for dir_path in add_dirs:
            cmd.extend(["--add-dir", str(dir_path)])

        self.logger.debug(f"Executing: {' '.join(cmd[:4])}...")

        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                cwd=str(self.working_dir),
            )

            if result.returncode != 0:
                stderr = result.stderr.strip() if result.stderr else "No error output"
                raise ServiceExecutionError(
                    f"Claude CLI failed with code {result.returncode}",
                    {"returncode": result.returncode, "stderr": stderr},
                )

            response = result.stdout.strip()
            if not response:
                raise ServiceExecutionError(
                    "Claude CLI returned empty response",
                    {"stdout": result.stdout, "stderr": result.stderr},
                )

            return response

        except subprocess.TimeoutExpired:
            raise ServiceTimeoutError(
                f"Claude CLI timed out after {self.timeout_seconds}s",
                {"timeout": self.timeout_seconds},
            )

    def complete_with_context(
        self,
        system_prompt: str,
        user_prompt: str,
        add_dirs: Optional[list[Path]] = None,
    ) -> str:
        """
        Convenience method combining system and user prompts.

        Args:
            system_prompt: System-level instructions
            user_prompt: User request
            add_dirs: Directories to grant file access

        Returns:
            Response text from Claude
        """
        full_prompt = build_prompt(system_prompt, user_prompt)
        kwargs = {}
        if add_dirs:
            kwargs["add_dirs"] = add_dirs
        return self.complete(full_prompt, **kwargs)
