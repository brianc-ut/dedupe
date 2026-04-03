from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    MofNCompleteColumn,
    TextColumn,
    TimeElapsedColumn,
)

from .hasher import group_by_hash
from .metadata import extract_metadata_batch
from .mover import execute_cleanup, execute_move
from .planner import build_plan, read_plan, write_plan
from .scanner import scan_sources
from .selector import select_best

app = typer.Typer(help="Photo and video deduplication tool.")
console = Console()


def _progress(*columns, **kwargs) -> Progress:
    return Progress(*columns, console=console, **kwargs)


@app.command()
def plan(
    source: Annotated[list[str], typer.Option("--source", help="Comma-separated glob patterns")] = [],
    output: Annotated[str, typer.Option("--output", help="Path to write plan YAML")] = "",
    metadata_provider: Annotated[str, typer.Option("--metadata-provider")] = "auto",
    include_hidden: bool = False,
):
    """Scan sources, find duplicates, and write a YAML plan."""
    if not source:
        console.print("[red]Error: at least one --source is required[/red]")
        raise typer.Exit(1)
    if not output:
        console.print("[red]Error: --output is required[/red]")
        raise typer.Exit(1)

    # Stage 1: Scan
    with _progress(SpinnerColumn(), TextColumn("{task.description}"),
                   TimeElapsedColumn(), transient=True) as progress:
        task = progress.add_task("Scanning sources...", total=None)
        files, archives, warnings = scan_sources(source, include_hidden=include_hidden)
        progress.update(task, description=f"Scanned — {len(files)} media files, {len(archives)} archives")

    for w in warnings:
        console.print(f"[yellow]{w}[/yellow]")
    console.print(f"Found [bold]{len(files)}[/bold] media files, [bold]{len(archives)}[/bold] archives")

    # Stage 2: Hash
    with _progress(SpinnerColumn(), TextColumn("{task.description}"),
                   BarColumn(), MofNCompleteColumn(),
                   TimeElapsedColumn(), transient=True) as progress:
        task = progress.add_task("Hashing files...", total=len(files))
        groups = group_by_hash(
            files,
            progress_callback=lambda _: progress.advance(task),
        )
    selected = [select_best(g) for g in groups]
    dup_count = sum(1 for s in selected if s.duplicates)
    console.print(f"Found [bold]{dup_count}[/bold] duplicate groups")

    # Stage 3: Metadata (parallel Python + single batch exiftool)
    best_paths = [sel.best.path for sel in selected]
    with _progress(SpinnerColumn(), TextColumn("{task.description}"),
                   BarColumn(), MofNCompleteColumn(),
                   TimeElapsedColumn(), transient=True) as progress:
        task = progress.add_task("Extracting metadata...", total=len(best_paths))
        metadata = extract_metadata_batch(
            best_paths,
            provider=metadata_provider,
            progress_callback=lambda _: progress.advance(task),
        )

    plan_data = build_plan(sources=source, selected=selected,
                           metadata=metadata, archives=archives)
    write_plan(plan_data, output)
    console.print(f"[green]Plan written to {output}[/green]")

    if warnings:
        raise typer.Exit(1)


@app.command()
def move(
    plan_path: Annotated[str, typer.Option("--plan", help="Path to plan YAML")] = "",
    dest: Annotated[str, typer.Option("--dest", help="Destination directory")] = "",
    flatten: bool = False,
    confirm: bool = False,
):
    """Apply plan: move best copies to destination directory. Defaults to dry run."""
    if not plan_path:
        console.print("[red]Error: --plan is required[/red]")
        raise typer.Exit(1)
    if not dest:
        console.print("[red]Error: --dest is required[/red]")
        raise typer.Exit(1)

    plan_data = read_plan(plan_path)
    dry_run = True

    if confirm:
        response = typer.prompt("Type 'confirm' to execute real moves")
        if response.strip().lower() != "confirm":
            console.print("[yellow]Confirmation not received. Running as dry run.[/yellow]")
        else:
            dry_run = False

    if dry_run:
        console.print("[yellow]DRY RUN — no files will be moved[/yellow]")

    result = execute_move(plan_data, dest=dest, dry_run=dry_run, flatten=flatten)

    for item in result["planned"]:
        prefix = "Would move" if dry_run else "Moved"
        console.print(f"  {prefix}: {item['from']} → {item['to']}")

    for w in result["warnings"]:
        console.print(f"[yellow]{w}[/yellow]")

    total = len(result["planned"])
    if dry_run:
        console.print(f"\n[bold]Dry run complete. {total} file(s) would be moved.[/bold]")
        console.print("Re-run with [bold]--confirm[/bold] to execute.")
    else:
        console.print(f"\n[green]Move complete. {total} file(s) moved.[/green]")

    if result["warnings"]:
        raise typer.Exit(1)


@app.command()
def cleanup(
    plan_path: Annotated[str, typer.Option("--plan", help="Path to plan YAML")] = "",
    trash: Annotated[str, typer.Option("--trash", help="Trash directory for duplicate extras")] = "",
    confirm: bool = False,
):
    """Apply plan: move duplicate extras to trash directory. Defaults to dry run."""
    if not plan_path:
        console.print("[red]Error: --plan is required[/red]")
        raise typer.Exit(1)
    if not trash:
        console.print("[red]Error: --trash is required[/red]")
        raise typer.Exit(1)

    plan_data = read_plan(plan_path)
    dry_run = True

    if confirm:
        response = typer.prompt("Type 'confirm' to execute real moves")
        if response.strip().lower() != "confirm":
            console.print("[yellow]Confirmation not received. Running as dry run.[/yellow]")
        else:
            dry_run = False

    if dry_run:
        console.print("[yellow]DRY RUN — no files will be moved[/yellow]")

    result = execute_cleanup(plan_data, trash=trash, dry_run=dry_run)

    for item in result["planned"]:
        prefix = "Would move" if dry_run else "Moved"
        console.print(f"  {prefix}: {item['from']} → {item['to']}")

    for skip in result["skipped_archive_members"]:
        console.print(f"  [dim]Skipped archive member (cannot move loose): {skip}[/dim]")

    for w in result["warnings"]:
        console.print(f"[yellow]{w}[/yellow]")

    total = len(result["planned"])
    if dry_run:
        console.print(f"\n[bold]Dry run complete. {total} duplicate(s) would be moved to trash.[/bold]")
        console.print("Re-run with [bold]--confirm[/bold] to execute.")
    else:
        console.print(f"\n[green]Cleanup complete. {total} duplicate(s) moved to trash.[/green]")

    if result["warnings"]:
        raise typer.Exit(1)
