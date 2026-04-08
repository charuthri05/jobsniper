"""Pipeline orchestrator for the 3-stage resume builder."""

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from resume_builder.config import Config, load_config, setup_logging
from resume_builder.stages import ExecutorStage, PlannerStage, ReviewerStage, StageResult
from resume_builder.utils import (
    JDMetadata,
    check_pdflatex_available,
    compile_latex,
    create_output_folder,
    parse_jd,
)


@dataclass
class PipelineResult:
    """Result of the full pipeline execution."""

    success: bool
    output_dir: Optional[Path] = None
    plan_file: Optional[Path] = None
    feedback_file: Optional[Path] = None
    latex_file: Optional[Path] = None
    pdf_file: Optional[Path] = None
    total_seconds: float = 0.0
    stage_times: dict[str, float] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


class Orchestrator:
    """Orchestrates the 3-stage resume building pipeline."""

    def __init__(
        self,
        config: Optional[Config] = None,
        base_dir: Optional[Path] = None,
        console: Optional[Console] = None,
    ):
        self.base_dir = base_dir or Path.cwd()
        self.config = config or load_config(base_dir=self.base_dir)
        self.console = console or Console()

        setup_logging(self.config)

    def run(
        self,
        jd_path: Optional[Path] = None,
        output_dir: Optional[Path] = None,
        stage: Optional[int] = None,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> PipelineResult:
        """
        Run the resume building pipeline.

        Args:
            jd_path: Path to job description (defaults to config value)
            output_dir: Custom output directory
            stage: Run specific stage only (1, 2, or 3)
            dry_run: Preview without saving files
            verbose: Enable verbose output

        Returns:
            PipelineResult with all outputs and timing
        """
        start_time = time.time()
        errors = []
        stage_times = {}

        # Parse JD
        jd_path = jd_path or (self.base_dir / self.config.inputs.job_description)
        self.console.print(f"[dim]Loading JD:[/dim] {jd_path}")

        try:
            jd_metadata = parse_jd(jd_path)
        except Exception as e:
            return PipelineResult(
                success=False,
                errors=[f"Failed to parse JD: {e}"],
                total_seconds=time.time() - start_time,
            )

        self.console.print(f"[dim]Company:[/dim] {jd_metadata.company}")
        self.console.print(f"[dim]Role:[/dim] {jd_metadata.role}")

        # Create/find output directory
        if output_dir:
            output_dir = Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
        else:
            output_base = self.base_dir / self.config.output.base_dir
            output_dir = create_output_folder(
                company=jd_metadata.company,
                role=jd_metadata.role,
                base_dir=output_base,
                folder_format=self.config.output.folder_format,
            )

        self.console.print(f"[dim]Output:[/dim] {output_dir}\n")

        if dry_run:
            self.console.print("[yellow]DRY RUN - No files will be saved[/yellow]\n")

        result = PipelineResult(
            success=True,
            output_dir=output_dir,
        )

        # Run stages
        stages_to_run = [stage] if stage else [1, 2, 3]

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=self.console,
        ) as progress:

            # Stage 1: Planner
            if 1 in stages_to_run:
                task = progress.add_task("Stage 1: Planner", total=None)
                stage_result = self._run_planner(jd_metadata, output_dir, dry_run)
                progress.remove_task(task)

                stage_times["planner"] = stage_result.elapsed_seconds
                if stage_result.success:
                    result.plan_file = stage_result.output_file
                    self.console.print(f"[green]✓[/green] Stage 1: Planner ({stage_result.elapsed_seconds:.1f}s)")
                else:
                    errors.append(f"Planner failed: {stage_result.output}")
                    result.success = False
                    result.errors = errors
                    result.total_seconds = time.time() - start_time
                    result.stage_times = stage_times
                    return result

            # Stage 2: Reviewer
            if 2 in stages_to_run:
                task = progress.add_task("Stage 2: Reviewer", total=None)
                stage_result = self._run_reviewer(jd_metadata, output_dir, dry_run)
                progress.remove_task(task)

                stage_times["reviewer"] = stage_result.elapsed_seconds
                if stage_result.success:
                    result.feedback_file = stage_result.output_file
                    self.console.print(f"[green]✓[/green] Stage 2: Reviewer ({stage_result.elapsed_seconds:.1f}s)")
                else:
                    errors.append(f"Reviewer failed: {stage_result.output}")
                    result.success = False
                    result.errors = errors
                    result.total_seconds = time.time() - start_time
                    result.stage_times = stage_times
                    return result

            # Stage 3: Executor
            if 3 in stages_to_run:
                task = progress.add_task("Stage 3: Executor", total=None)
                stage_result = self._run_executor(jd_metadata, output_dir, dry_run)
                progress.remove_task(task)

                stage_times["executor"] = stage_result.elapsed_seconds
                if stage_result.success:
                    result.latex_file = stage_result.output_file
                    self.console.print(f"[green]✓[/green] Stage 3: Executor ({stage_result.elapsed_seconds:.1f}s)")
                else:
                    errors.append(f"Executor failed: {stage_result.output}")
                    result.success = False
                    result.errors = errors
                    result.total_seconds = time.time() - start_time
                    result.stage_times = stage_times
                    return result

            # PDF Compilation
            if 3 in stages_to_run and result.latex_file and not dry_run:
                task = progress.add_task("Compiling PDF", total=None)
                pdf_result = self._compile_pdf(result.latex_file, output_dir)
                progress.remove_task(task)

                stage_times["pdf"] = pdf_result.get("elapsed", 0)
                if pdf_result.get("success"):
                    result.pdf_file = pdf_result.get("pdf_path")
                    self.console.print(f"[green]✓[/green] PDF compiled ({stage_times['pdf']:.1f}s)")
                else:
                    # PDF compilation failure is a warning, not fatal
                    self.console.print(f"[yellow]![/yellow] PDF compilation: {pdf_result.get('error', 'failed')}")

        result.total_seconds = time.time() - start_time
        result.stage_times = stage_times
        result.errors = errors

        return result

    def _run_planner(
        self,
        jd_metadata: JDMetadata,
        output_dir: Path,
        dry_run: bool,
    ) -> StageResult:
        """Run Stage 1: Planner."""
        planner = PlannerStage(
            config=self.config,
            output_dir=output_dir,
            jd_metadata=jd_metadata,
        )
        return planner.execute(base_dir=self.base_dir)

    def _run_reviewer(
        self,
        jd_metadata: JDMetadata,
        output_dir: Path,
        dry_run: bool,
    ) -> StageResult:
        """Run Stage 2: Reviewer."""
        reviewer = ReviewerStage(
            config=self.config,
            output_dir=output_dir,
            jd_metadata=jd_metadata,
        )
        return reviewer.execute(base_dir=self.base_dir)

    def _run_executor(
        self,
        jd_metadata: JDMetadata,
        output_dir: Path,
        dry_run: bool,
    ) -> StageResult:
        """Run Stage 3: Executor."""
        executor = ExecutorStage(
            config=self.config,
            output_dir=output_dir,
            jd_metadata=jd_metadata,
        )
        return executor.execute(base_dir=self.base_dir)

    def _compile_pdf(self, latex_file: Path, output_dir: Path) -> dict:
        """Compile LaTeX to PDF."""
        start = time.time()

        available, _ = check_pdflatex_available()
        if not available:
            return {
                "success": False,
                "error": "pdflatex not installed",
                "elapsed": time.time() - start,
            }

        pdf_name = self.config.output.pdf_name.replace(".pdf", "")
        result = compile_latex(
            tex_file=latex_file,
            output_dir=output_dir,
            output_name=pdf_name,
            compile_twice=self.config.latex.compile_twice,
            clean_aux=self.config.latex.clean_aux_files,
            aux_extensions=self.config.latex.aux_extensions,
        )

        return {
            "success": result.success,
            "pdf_path": result.pdf_path,
            "error": result.errors[0] if result.errors else None,
            "elapsed": time.time() - start,
        }

    def print_summary(self, result: PipelineResult) -> None:
        """Print a summary of the pipeline execution."""
        if result.success:
            summary = "[bold green]✓ Resume generated successfully![/bold green]\n\n"
            summary += f"[dim]Output folder:[/dim] {result.output_dir}\n\n"
            summary += "[dim]Files created:[/dim]\n"

            if result.plan_file:
                summary += f"  • {result.plan_file.name} (Stage 1: Planner)\n"
            if result.feedback_file:
                summary += f"  • {result.feedback_file.name} (Stage 2: Reviewer)\n"
            if result.latex_file:
                summary += f"  • {result.latex_file.name} (Stage 3: Executor)\n"
            if result.pdf_file:
                summary += f"  • {result.pdf_file.name} (Final PDF)\n"

            summary += f"\n[dim]Total time:[/dim] {result.total_seconds:.1f}s"

            self.console.print(Panel(summary, border_style="green"))
        else:
            summary = "[bold red]✗ Pipeline failed[/bold red]\n\n"
            summary += "[dim]Errors:[/dim]\n"
            for error in result.errors:
                summary += f"  • {error}\n"

            if result.output_dir:
                summary += f"\n[dim]Partial output:[/dim] {result.output_dir}"

            self.console.print(Panel(summary, border_style="red"))
