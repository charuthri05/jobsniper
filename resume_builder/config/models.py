"""Configuration models using Pydantic."""

import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class ClaudeCLIConfig(BaseModel):
    """Claude CLI provider configuration."""

    enabled: bool = True
    mode: str = "print"
    timeout_seconds: int = 300
    retry_on_failure: bool = True
    max_retries: int = 2
    add_dir_flag: str = "--add-dir"


class AnthropicAPIConfig(BaseModel):
    """Anthropic API provider configuration."""

    enabled: bool = False
    api_key: Optional[str] = None
    default_model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 8000
    temperature: float = 0.0

    @field_validator("api_key", mode="before")
    @classmethod
    def load_api_key(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return os.environ.get("RESUME_BUILDER_ANTHROPIC_API_KEY")
        return v


class OpenAIConfig(BaseModel):
    """OpenAI API provider configuration."""

    enabled: bool = False
    api_key: Optional[str] = None
    default_model: str = "gpt-4o"
    max_tokens: int = 8000
    temperature: float = 0.0

    @field_validator("api_key", mode="before")
    @classmethod
    def load_api_key(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return os.environ.get("RESUME_BUILDER_OPENAI_API_KEY")
        return v


class PerplexityConfig(BaseModel):
    """Perplexity API provider configuration."""

    enabled: bool = False
    api_key: Optional[str] = None
    default_model: str = "llama-3.1-sonar-large-128k-online"
    max_tokens: int = 8000

    @field_validator("api_key", mode="before")
    @classmethod
    def load_api_key(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return os.environ.get("RESUME_BUILDER_PERPLEXITY_API_KEY")
        return v


class ExperienceInputs(BaseModel):
    """Experience file paths."""

    current: str = "experience/linq_work_experience.md"
    previous: str = "experience/applogic_work_experience.md"


class InputsConfig(BaseModel):
    """Input file paths configuration."""

    job_description: str = "job-description.md"
    resume_template: str = "resume_template/jakes_resume.tex"
    experience: ExperienceInputs = Field(default_factory=ExperienceInputs)
    projects: str = "projects/all_projects_impact.md"


class OutputArtifacts(BaseModel):
    """Output artifact names."""

    plan: str = "resume_plan.md"
    feedback: str = "review_feedback.md"
    latex: str = "resume.tex"


class OutputConfig(BaseModel):
    """Output configuration."""

    base_dir: str = "output"
    folder_format: str = "{company}_{role}"
    pdf_name: str = "Siddartha_Kodaboina_Resume.pdf"
    artifacts: OutputArtifacts = Field(default_factory=OutputArtifacts)


class LaTeXConfig(BaseModel):
    """LaTeX compilation configuration."""

    compiler: str = "pdflatex"
    compile_twice: bool = True
    clean_aux_files: bool = True
    aux_extensions: list[str] = Field(
        default_factory=lambda: [".aux", ".log", ".out", ".toc", ".fls", ".fdb_latexmk"]
    )


class StageConfig(BaseModel):
    """Individual stage configuration."""

    name: str
    description: str
    output_file: str


class StagesConfig(BaseModel):
    """All stages configuration."""

    planner: StageConfig = Field(
        default_factory=lambda: StageConfig(
            name="Stage 1: Planner",
            description="Analyzes JD and creates rewrite plan",
            output_file="resume_plan.md",
        )
    )
    reviewer: StageConfig = Field(
        default_factory=lambda: StageConfig(
            name="Stage 2: Reviewer",
            description="Validates plan and provides feedback",
            output_file="review_feedback.md",
        )
    )
    executor: StageConfig = Field(
        default_factory=lambda: StageConfig(
            name="Stage 3: Executor",
            description="Generates final LaTeX from plan + feedback",
            output_file="resume.tex",
        )
    )


class EducationDates(BaseModel):
    """Education dates (protected)."""

    masters: str = "Aug 2023 - May 2025"
    bachelors: str = "Jun 2017 -- May 2021"


class EmploymentDates(BaseModel):
    """Employment dates (protected)."""

    linq: str = "Aug 2025 -- Present"
    applogic: str = "Jul 2021 -- Jul 2023"


class ProtectedContent(BaseModel):
    """Content that should never be modified."""

    name: str = "Siddartha Kodaboina"
    email: str = "stevesiddu49@gmail.com"
    phone: str = "(669) 649-2373"
    linkedin: str = "https://www.linkedin.com/in/siddartha-kodaboina/"
    github: str = "https://github.com/Siddartha-Kodaboina"
    education_dates: EducationDates = Field(default_factory=EducationDates)
    employment_dates: EmploymentDates = Field(default_factory=EmploymentDates)


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file: Optional[str] = None


class Config(BaseModel):
    """Root configuration model."""

    app_name: str = "Resume Builder"
    version: str = "0.1.0"
    active_provider: str = "claude_cli"

    claude_cli: ClaudeCLIConfig = Field(default_factory=ClaudeCLIConfig)
    anthropic_api: AnthropicAPIConfig = Field(default_factory=AnthropicAPIConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    perplexity: PerplexityConfig = Field(default_factory=PerplexityConfig)

    inputs: InputsConfig = Field(default_factory=InputsConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    latex: LaTeXConfig = Field(default_factory=LaTeXConfig)
    stages: StagesConfig = Field(default_factory=StagesConfig)
    protected_content: ProtectedContent = Field(default_factory=ProtectedContent)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    def get_input_path(self, key: str, base_dir: Optional[Path] = None) -> Path:
        """Get absolute path for an input file."""
        base = base_dir or Path.cwd()
        if key == "job_description":
            return base / self.inputs.job_description
        elif key == "resume_template":
            return base / self.inputs.resume_template
        elif key == "experience_current":
            return base / self.inputs.experience.current
        elif key == "experience_previous":
            return base / self.inputs.experience.previous
        elif key == "projects":
            return base / self.inputs.projects
        raise ValueError(f"Unknown input key: {key}")
