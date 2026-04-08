#!/usr/bin/env python3
"""Resume Builder CLI - Automated JD-specific resume generation."""

import logging
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from resume_builder.config import load_config
from resume_builder.orchestrator import Orchestrator
from resume_builder.utils import check_pdflatex_available

app = typer.Typer(
    name="resume-builder",
    help="Generate JD-tailored resumes using a 3-stage LLM pipeline (Planner → Reviewer → Executor)",
    add_completion=False,
)

console = Console()

DEFAULT_JD_PATH = Path("job-description.md")
DEFAULT_CONFIG_PATH = Path("config.yaml")


@app.command()
def build(
    jd: Optional[Path] = typer.Option(
        None,
        "--jd",
        "-j",
        help="Path to job description markdown file",
    ),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.yaml file",
    ),
    stage: Optional[int] = typer.Option(
        None,
        "--stage",
        "-s",
        min=1,
        max=3,
        help="Run specific stage only (1=Planner, 2=Reviewer, 3=Executor)",
    ),
    output_dir: Optional[Path] = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Custom output directory (default: ./output/{company}_{role})",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-n",
        help="Preview changes without saving files",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose debug output",
    ),
) -> None:
    """
    Generate a JD-tailored resume using the 3-stage LLM pipeline.

    \b
    Stages:
      1. PLANNER  - Analyzes JD and creates rewrite plan
      2. REVIEWER - Validates plan and provides feedback
      3. EXECUTOR - Generates final LaTeX and compiles to PDF

    \b
    Example:
      python resume_build.py --jd ./job-description.md
      python resume_build.py --stage 1  # Run planner only
      python resume_build.py --dry-run  # Preview without saving
    """
    # Set logging level
    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    console.print(
        Panel.fit(
            "[bold blue]Resume Builder[/bold blue]\n"
            "[dim]3-Stage LLM Pipeline: Planner → Reviewer → Executor[/dim]",
            border_style="blue",
        )
    )

    # Load config
    try:
        cfg = load_config(config_path=config)
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)

    # Create orchestrator
    orchestrator = Orchestrator(config=cfg, console=console)

    # Run pipeline
    result = orchestrator.run(
        jd_path=jd,
        output_dir=output_dir,
        stage=stage,
        dry_run=dry_run,
        verbose=verbose,
    )

    # Print summary
    console.print()
    orchestrator.print_summary(result)

    if not result.success:
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Show version information."""
    from resume_builder import __version__

    console.print(f"[bold]resume-builder[/bold] version [cyan]{__version__}[/cyan]")
    console.print("[dim]3-Stage LLM Pipeline for JD-specific resume generation[/dim]")


@app.command()
def check() -> None:
    """Verify system requirements and configuration."""
    import shutil
    import subprocess

    console.print("[bold]System Check[/bold]\n")

    # Check Claude CLI
    claude_path = shutil.which("claude")
    if claude_path:
        try:
            version_result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            claude_version = version_result.stdout.strip()
            console.print(f"[green]✓[/green] Claude CLI: {claude_path} ({claude_version})")
        except Exception:
            console.print(f"[green]✓[/green] Claude CLI: {claude_path}")
    else:
        console.print("[red]✗[/red] Claude CLI: Not found")
        console.print("[dim]  Install: npm install -g @anthropic-ai/claude-code[/dim]")

    # Check pdflatex
    available, info = check_pdflatex_available()
    if available:
        console.print(f"[green]✓[/green] pdflatex: {info}")
    else:
        console.print(f"[yellow]![/yellow] pdflatex: {info}")
        console.print("[dim]  Install: brew install --cask mactex-no-gui[/dim]")

    # Check config file
    if DEFAULT_CONFIG_PATH.exists():
        console.print(f"[green]✓[/green] Config: {DEFAULT_CONFIG_PATH}")
    else:
        console.print(f"[yellow]![/yellow] Config: {DEFAULT_CONFIG_PATH} not found")

    # Check JD file
    if DEFAULT_JD_PATH.exists():
        console.print(f"[green]✓[/green] JD: {DEFAULT_JD_PATH}")
    else:
        console.print(f"[yellow]![/yellow] JD: {DEFAULT_JD_PATH} not found")

    # Check input files
    try:
        cfg = load_config()
        console.print("\n[bold]Input Files[/bold]\n")

        inputs = [
            ("Resume Template", cfg.inputs.resume_template),
            ("Linq Experience", cfg.inputs.experience.current),
            ("AppLogic Experience", cfg.inputs.experience.previous),
            ("Projects", cfg.inputs.projects),
        ]

        for name, path in inputs:
            full_path = Path(path)
            if full_path.exists():
                console.print(f"[green]✓[/green] {name}: {path}")
            else:
                console.print(f"[yellow]![/yellow] {name}: {path} not found")

    except Exception:
        pass


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":
    main()
