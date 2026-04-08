"""Config module - Configuration loading and validation."""

from resume_builder.config.loader import load_config, setup_logging
from resume_builder.config.models import Config

__all__ = ["Config", "load_config", "setup_logging"]
