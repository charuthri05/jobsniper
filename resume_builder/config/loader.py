"""Configuration loader for resume builder."""

import logging
from pathlib import Path
from typing import Optional

import yaml

from resume_builder.config.models import Config

DEFAULT_CONFIG_PATHS = [
    Path("config.yaml"),
    Path("config/default.yaml"),
]


def load_config(
    config_path: Optional[Path] = None,
    base_dir: Optional[Path] = None,
) -> Config:
    """
    Load configuration from YAML file.

    Args:
        config_path: Explicit path to config file. If None, searches default locations.
        base_dir: Base directory for resolving relative paths. Defaults to cwd.

    Returns:
        Validated Config object

    Raises:
        FileNotFoundError: If no config file found
        ValueError: If config validation fails
    """
    base_dir = base_dir or Path.cwd()
    logger = logging.getLogger(__name__)

    if config_path:
        search_paths = [config_path]
    else:
        search_paths = [base_dir / p for p in DEFAULT_CONFIG_PATHS]

    config_file: Optional[Path] = None
    for path in search_paths:
        if path.exists():
            config_file = path
            break

    if not config_file:
        searched = ", ".join(str(p) for p in search_paths)
        raise FileNotFoundError(f"No config file found. Searched: {searched}")

    logger.debug(f"Loading config from: {config_file}")

    with open(config_file) as f:
        raw_config = yaml.safe_load(f)

    if raw_config is None:
        raw_config = {}

    config = Config(**raw_config)
    logger.info(f"Loaded config: {config.app_name} v{config.version}")

    return config


def setup_logging(config: Config) -> None:
    """Configure logging based on config settings."""
    log_config = config.logging

    level = getattr(logging, log_config.level.upper(), logging.INFO)

    handlers: list[logging.Handler] = [logging.StreamHandler()]

    if log_config.file:
        handlers.append(logging.FileHandler(log_config.file))

    logging.basicConfig(
        level=level,
        format=log_config.format,
        handlers=handlers,
        force=True,
    )
