"""Weather-themed terminal dashboard built on rich.

Weather scale
  ☀  Sunny         combination passes
  ⛈  Thunderstorm  branches pass alone but fail together (interaction)
  🌧  Rain          a single branch fails on its own
  🌦  Showers       flaky: same tree, mixed outcomes
  🌫  Fog           textual merge conflict, not tested
  🌪  Tornado       infrastructure error (sandbox could not run)
  ❔  Uncharted     not run (budget exhausted)
"""

from __future__ import annotations

from typing import Any

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

WEATHER: dict[str, tuple] = {
    "pass": ("☀", "Sunny", "bold yellow"),
    "interaction": ("⛈", "Thunderstorm", "bold red"),
    "fail": ("🌧", "Rain", "red"),
    "flaky": ("🌦", "Showers", "magenta"),
    "conflict": ("🌫", "Fog", "grey62"),
    "error": ("🌪", "Tornado", "bold magenta"),
    "not_run": ("❔", "Uncharted", "dim"),
    "pending": ("…", "Forming", "cyan"),
}

VERDICT_WEATHER = {
    "interactions-found": ("⛈", "Storm warning", "bold red"),
    "no-failures-found": ("☀", "Clear skies", "bold green"),
    "inconclusive-budget": ("🌥", "Partly cloudy (budget ran out)", "bold yellow"),
    "base-failing": ("🌪", "Base is already broken", "bold magenta"),
}


def weather_key(status: str, size: int) -> str:
    if status == "fail":
        return "fail" if size <= 1 else "interaction"
    return status if status in WEATHER else "pending"


def weather_text(status: str, size: int) -> Text:
    icon, name, style = WEATHER[weather_key(status, size)]
    return Text(f"{icon} {name}", style=style)


class Dashboard:
    """Live progress view fed by Engine events."""

    def __init__(self, console: Console | None = None, title: str = "MergeWeather"):
        self.console = console or Console(stderr=True)
        self.title = title
        self.phase = "resolving refs"
        self.current = ""
        self.rows: dict[str, Any] = {}
        self.runs = 0
        self.max_runs = 0
        self.live: Live | None = None

    # engine callback
    def __call__(self, kind: str, **data) -> None:
        if kind == "phase":
            self.phase = data["name"]
        elif kind == "run_start":
            self.current = f"{data['combo'].id} (attempt {data['attempt']})"
        elif kind == "run":
            self.runs += 1
        elif kind == "combo":
            self.rows[data["combo"].id] = data["combo"]
            self.current = ""
        if self.live:
            self.live.update(self.render())

    def render(self):
        table = Table(box=box.SIMPLE_HEAVY, expand=False, header_style="bold")
        table.add_column("Combination", style="bold")
        table.add_column("Forecast")
        table.add_column("Runs", justify="right")
        table.add_column("Tree", style="dim")
        for rec in list(self.rows.values())[-14:]:
            table.add_row(
                rec.id, weather_text(rec.status, len(rec.branches)), str(len(rec.runs)), (rec.tree or "-")[:10]
            )
        status = Spinner(
            "dots",
            text=Text.assemble(
                ("  " + self.phase, "bold cyan"),
                (f"  ·  testing {self.current}" if self.current else "", "white"),
                (f"  ·  {self.runs}/{self.max_runs} runs" if self.max_runs else f"  ·  {self.runs} runs", "dim"),
            ),
        )
        return Panel(Group(status, table), title=f"[bold]🌤  {self.title}[/]", border_style="cyan")

    def __enter__(self):
        self.live = Live(self.render(), console=self.console, refresh_per_second=12, transient=True)
        self.live.__enter__()
        return self

    def __exit__(self, *exc):
        if self.live:
            self.live.__exit__(*exc)
            self.live = None


def print_summary(report: dict, console: Console, paths=()) -> None:
    icon, label, style = VERDICT_WEATHER.get(report["verdict"], ("?", report["verdict"], "bold"))
    [b["label"] for b in report["inputs"]["branches"]]

    branches = Table(title="Branch conditions", box=box.ROUNDED, title_style="bold")
    branches.add_column("Branch", style="bold")
    branches.add_column("Commit", style="dim")
    branches.add_column("Alone")
    branches.add_column("Involved in")
    by_id = {c["id"]: c for c in report["combinations"]}
    for b in report["inputs"]["branches"]:
        alone = by_id.get(b["label"])
        involved = [f["id"] for f in report["findings"] if b["label"] in f["branches"]]
        involved += [f"conflict:{c['combination']}" for c in report["conflicts"] if b["label"] in c["branches"]]
        branches.add_row(
            b["label"],
            b["commit"][:10],
            weather_text(alone["status"], 1) if alone else Text("❔ Uncharted", style="dim"),
            ", ".join(involved) or Text("—", style="dim"),
        )

    forecast = Table(title="Forecast by combination", box=box.ROUNDED, title_style="bold")
    forecast.add_column("Combination", style="bold")
    forecast.add_column("Weather")
    forecast.add_column("Runs", justify="right")
    forecast.add_column("Detail", overflow="fold")
    for c in report["combinations"]:
        detail = ""
        if c["status"] == "conflict":
            detail = "conflict in " + ", ".join(c["conflict_files"])
        elif c["fingerprints"] and c["status"] != "pass":
            detail = ", ".join(c["fingerprints"])
        forecast.add_row(c["id"], weather_text(c["status"], len(c["branches"])), str(len(c["runs"])), detail)

    console.print()
    console.print(
        Panel(
            Text(f"{icon}  {label}", style=style, justify="center"),
            title="[bold]MergeWeather forecast[/]",
            border_style=style.split()[-1],
        )
    )
    console.print(branches)
    console.print(forecast)
    for f in report["findings"]:
        k = weather_key("fail", len(f["branches"]))
        wicon, wname, wstyle = WEATHER[k]
        body = Text()
        body.append(f"{' + '.join(f['branches'])}\n", style="bold")
        body.append(f"{f['kind']} · {f['minimality']} · {f['stability']} · {f['fingerprint']}\n")
        if f["minimality_caveats"]:
            body.append("caveats: " + "; ".join(f["minimality_caveats"]) + "\n", style="yellow")
        for line in f["signature"]:
            body.append(f"  {line}\n", style="dim")
        console.print(Panel(body, title=f"[{wstyle}]{wicon} {f['id']} {wname}[/]", border_style=wstyle.split()[-1]))
    b = report["budget"]
    console.print(
        Text(
            f"Budget: {b['used_runs']}/{b['max_runs']} runs"
            + (f" · exhausted ({b['reason']})" if b["exhausted"] else "")
            + f" · sandbox: {report['isolation']['backend']}"
            + ("" if report["isolation"]["network_isolated"] else " (no network isolation)"),
            style="dim",
        )
    )
    for p in paths:
        console.print(Text(f"report → {p}", style="cyan"))
