"""
Shared Rich console instance and common UI helpers for the Admin CLI.
"""
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.prompt import Prompt, Confirm
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich import box

console = Console()

BRAND = "[bold cyan]ZIA TRADER[/bold cyan]"

ROLES = ["admin", "operator", "reader", "guest"]


def header(title: str) -> None:
    console.print(Panel(f"[bold white]{title}[/bold white]", style="cyan", box=box.DOUBLE))


def banner() -> None:
    art = Text()
    art.append("╔══════════════════════════════════════════╗\n", style="cyan")
    art.append("║      ", style="cyan")
    art.append("ZIA TRADER  —  ADMIN CONSOLE", style="bold yellow")
    art.append("      ║\n", style="cyan")
    art.append("╚══════════════════════════════════════════╝", style="cyan")
    console.print(art)


def success(msg: str) -> None:
    console.print(f"[bold green]✔[/bold green]  {msg}")


def error(msg: str) -> None:
    console.print(f"[bold red]✖[/bold red]  {msg}")


def warn(msg: str) -> None:
    console.print(f"[bold yellow]⚠[/bold yellow]  {msg}")


def info(msg: str) -> None:
    console.print(f"[bold blue]ℹ[/bold blue]  {msg}")


def divider() -> None:
    console.print("[dim]──────────────────────────────────────────[/dim]")


def pause() -> None:
    Prompt.ask("\n[dim]Pressione Enter para continuar[/dim]")


def menu(title: str, options: list[tuple[str, str]]) -> str:
    """Render a numbered menu and return the chosen key (e.g. '1')."""
    console.print()
    header(title)
    for key, label in options:
        style = "bold red" if key == "0" else "bold cyan"
        console.print(f"  [{style}][{key}][/{style}]  {label}")
    console.print()
    return Prompt.ask("[bold white]Opção[/bold white]").strip()


def confirm(msg: str) -> bool:
    return Confirm.ask(f"[yellow]{msg}[/yellow]")


def make_table(*columns: str, title: str = "") -> Table:
    t = Table(title=title, box=box.SIMPLE_HEAVY, border_style="cyan",
              header_style="bold white", show_lines=True)
    for col in columns:
        t.add_column(col, style="white")
    return t


def progress_bar(description: str, total: int = 100) -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=40),
        TextColumn("[bold white]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )
