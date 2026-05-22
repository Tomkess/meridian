import typer
from typing import Optional

app = typer.Typer(
    name="meridian",
    help="Navigate your codebase with purpose.",
    no_args_is_help=True,
)


@app.command()
def status():
    """Show full feature dashboard with lifecycle states and Databricks job health."""
    typer.echo("meridian status — coming soon")


@app.command()
def new(idea: str = typer.Argument(..., help="Idea text to capture")):
    """Quick-capture a new idea and map it to a goal."""
    typer.echo(f"Capturing idea: {idea}")


@app.command()
def enrich(
    feature_id: str = typer.Argument(..., help="Feature ID (e.g. feat-007)"),
    source: str = typer.Argument(..., help="Path to file or URL"),
):
    """Ingest a PDF, URL, or image into a feature's research corpus."""
    typer.echo(f"Enriching {feature_id} with {source}")


@app.command()
def close(
    feature_id: str = typer.Argument(..., help="Feature ID"),
    status: str = typer.Option(..., help="New status: done | in-production | abandoned | blocked"),
):
    """Transition a feature's lifecycle state."""
    typer.echo(f"Closing {feature_id} → {status}")


@app.command("sync-jobs")
def sync_jobs():
    """Auto-link Databricks jobs to specs by name convention."""
    typer.echo("Syncing Databricks jobs — coming soon")


@app.command()
def index():
    """Rebuild the LanceDB vector index from all specs and summaries."""
    typer.echo("Rebuilding index — coming soon")


@app.command()
def transition(
    from_merge: str = typer.Option(..., help="Branch name that was merged"),
):
    """Auto-transition features to in-production after a merge."""
    typer.echo(f"Transitioning features from merged branch: {from_merge}")


if __name__ == "__main__":
    app()
