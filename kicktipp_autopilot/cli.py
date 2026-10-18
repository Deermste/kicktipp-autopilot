"""Kommandozeile des Autopiloten.

Hier steht nur, wie der Autopilot aufgerufen wird — der Ablauf selbst liegt in
`runner.py`, die Menüführung in `interactive.py`.

Grundregel: **Lesen ist der Normalfall, Schreiben braucht eine ausdrückliche
Ansage.** Ohne `--submit` wird nichts abgesendet.
"""

from __future__ import annotations

import argparse
import logging
import sys

from rich.logging import RichHandler
from rich.table import Table

from .config import (
    LEAGUES,
    Credentials,
    GroupConfig,
    all_configured_groups,
    leagues_for,
    load_credentials,
    load_group_config,
    with_strategies,
)
from .errors import AutopilotError, ConfigError
from .runner import console, make_target, run_groups, run_predictions_only

log = logging.getLogger(__name__)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        datefmt="%H:%M:%S",
        handlers=[RichHandler(console=console, show_path=verbose, rich_tracebacks=True)],
    )
    if not verbose:
        # Der HTTP-Client protokolliert sonst jede Anfrage auf INFO.
        logging.getLogger("httpx").setLevel(logging.WARNING)


# ── Gruppenauswahl ──────────────────────────────────────────────────────


def single_group(credentials: Credentials, cli_leagues: list[str] | None) -> list[GroupConfig]:
    """Die eine Gruppe aus `--group`/`.env` im selben Format wie `--all-groups`.

    Strategien kommen wie die Ligen aus dem config.toml-Eintrag der Gruppe,
    sofern es einen gibt; `--strategie` greift erst danach.
    """
    groups = load_group_config()
    entry = groups.get(credentials.group)
    return [
        GroupConfig(
            name=credentials.group,
            leagues=leagues_for(credentials.group, cli_leagues, groups=groups),
            strategies=entry.strategies if entry else (),
        )
    ]


# ── Auflistungen ────────────────────────────────────────────────────────


def run_list_groups(credentials: Credentials, use_browser: bool, headless: bool) -> int:
    with make_target(credentials, use_browser, headless) as kicktipp:
        kicktipp.login()
        groups = kicktipp.list_groups()

    if not groups:
        console.print("[yellow]Keine Tippgruppen gefunden.[/yellow]")
        return 1

    configured = load_group_config()
    table = Table(title="Deine Tippgruppen", header_style="bold")
    table.add_column("Gruppenname (für KICKTIPP_GROUP)")
    table.add_column("Ligen laut config.toml", style="dim")
    for group in groups:
        entry = configured.get(group)
        table.add_row(
            group,
            ", ".join(l.slug for l in entry.leagues) if entry else "—",
        )
    console.print(table)
    return 0


def run_list_matchdays(
    credentials: Credentials,
    groups: list[str],
    use_browser: bool,
    headless: bool,
) -> int:
    """Zeigt die Spieltage je Gruppe samt ihres `spieltagIndex`.

    In Gruppen mit mehreren Wettbewerben laufen Index und angezeigte Nummer
    auseinander — ohne diese Liste wäre `--matchday` ein Ratespiel.
    """
    with make_target(credentials, use_browser, headless) as kicktipp:
        kicktipp.login()
        # Ohne offenen Spieltag ist die Liste besonders nützlich — also nicht
        # daran scheitern, dass gerade nichts tippbar ist.
        pages = {
            group: kicktipp.load_page(group, require_fixtures=False)
            for group in groups
        }

    code = 0
    for group, page in pages.items():
        if not page.matchdays:
            console.print(
                f"[yellow]{group}: keine Spieltagsauswahl auf der Seite gefunden.[/yellow]"
            )
            code = 1
            continue

        table = Table(title=f"Spieltage · {group}", header_style="bold")
        table.add_column("--matchday", justify="right")
        table.add_column("Bezeichnung")
        table.add_column("Wettbewerb", style="dim")
        for option in page.matchdays:
            marker = " [green]← aktuell[/green]" if option.active else ""
            table.add_row(
                str(option.index), option.label + marker, option.competition or "—"
            )
        console.print(table)
    return code


# ── Argumente ───────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kicktipp-autopilot",
        description="Holt Spielvorhersagen und trägt sie bei Kicktipp ein.",
        epilog="Ohne --submit wird nichts abgesendet.",
    )
    parser.add_argument(
        "--league",
        action="append",
        default=None,
        help=(
            "Liganame oder predicd-ID. Mehrfach angebbar oder als Kommaliste, "
            "z. B. --league bundesliga,champions-league. Ohne Angabe gilt der "
            "Eintrag der Gruppe aus config.toml, sonst bundesliga. "
            "Siehe --list-leagues."
        ),
    )
    parser.add_argument(
        "--matchday", type=int, default=None,
        help=(
            "Spieltag der Gruppe (spieltagIndex, Standard: der aktuell "
            "anstehende). In Gruppen mit mehreren Wettbewerben ist das nicht "
            "die angezeigte Spieltagnummer — siehe --list-matchdays."
        ),
    )
    parser.add_argument(
        "--allow-partial", action="store_true",
        help=(
            "Auch dann absenden, wenn Spiele ohne eindeutige Vorhersage übrig "
            "bleiben (Standard: abbrechen, ohne etwas zu schreiben)."
        ),
    )
    parser.add_argument("--group", default=None, help="Kicktipp-Gruppe (überschreibt .env).")
    parser.add_argument(
        "--all-groups", action="store_true",
        help=(
            "Alle in der config.toml eingetragenen Gruppen nacheinander "
            "abarbeiten — eine Anmeldung, eine Zusammenfassung am Ende."
        ),
    )
    parser.add_argument(
        "-i", "--interactive", action="store_true",
        help=(
            "Gruppen im Menü auswählen, Vorschau ansehen und erst danach "
            "entscheiden, ob abgesendet wird."
        ),
    )
    parser.add_argument(
        "--submit", action="store_true",
        help="Tipps tatsächlich eintragen und absenden.",
    )
    parser.add_argument(
        "--strategie",
        action="append",
        default=None,
        metavar="NAME",
        help=(
            "Tippstrategie: favorit (Buchmacher-Favorit statt abweichender "
            "predicd-Tendenz), faustregel (Ergebnis 3:0 bei klarem Favoriten "
            "ab 65 %%, sonst 2:1, Remis 1:1) oder keine. Kommaliste möglich, "
            "z. B. --strategie favorit,faustregel. Gilt für alle Gruppen des "
            "Laufs und ersetzt den Eintrag 'strategie' aus config.toml."
        ),
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help="Auch bereits abgegebene Tipps überschreiben (Standard: unangetastet lassen).",
    )
    parser.add_argument(
        "--no-kicktipp", action="store_true",
        help="Nur Vorhersagen anzeigen, ohne Login bei Kicktipp.",
    )
    parser.add_argument("--list-groups", action="store_true", help="Eigene Tippgruppen auflisten.")
    parser.add_argument("--list-leagues", action="store_true", help="Bekannte Ligen auflisten.")
    parser.add_argument(
        "--list-matchdays", action="store_true",
        help="Spieltage der Gruppe mit ihrem spieltagIndex auflisten.",
    )
    parser.add_argument(
        "--browser", action="store_true",
        help="Über einen Browser statt über HTTP arbeiten (Rückfallebene, deutlich langsamer).",
    )
    parser.add_argument(
        "--show-browser", action="store_true",
        help="Browserfenster sichtbar machen (impliziert --browser).",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Ausführliche Ausgabe.")
    return parser


def check_combinations(args: argparse.Namespace) -> None:
    """Widersprüchliche Optionen abfangen — vor dem ersten Netzzugriff.

    Lieber sofort eine Meldung mit Handlungsanweisung als eine Anmeldung, die
    anschließend etwas anderes tut als gemeint.
    """
    if not args.all_groups:
        return

    if args.group:
        raise ConfigError(
            "--all-groups und --group schließen einander aus: Entweder alle "
            "Gruppen aus der config.toml oder genau die eine genannte."
        )
    if args.matchday is not None:
        raise ConfigError(
            "--all-groups und --matchday passen nicht zusammen: Der "
            "spieltagIndex zählt je Gruppe eigenständig durch und bedeutet in "
            "jeder Gruppe etwas anderes. Für einen bestimmten Spieltag die "
            "Gruppe einzeln aufrufen:  kicktipp --group NAME --matchday N"
        )
    if args.league:
        raise ConfigError(
            "--all-groups und --league passen nicht zusammen: --league würde "
            "die Wettbewerbe *jeder* Gruppe überschreiben. Welche Gruppe was "
            "tippt, steht in der config.toml."
        )
    if args.interactive:
        raise ConfigError(
            "--all-groups und --interactive schließen einander aus: Das Menü "
            "fragt die Gruppen ohnehin ab."
        )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _setup_logging(args.verbose)
    # Ein sichtbares Fenster setzt den Browserweg voraus.
    use_browser = args.browser or args.show_browser
    headless = not args.show_browser

    if args.list_leagues:
        table = Table(title="Bekannte Ligen", header_style="bold")
        table.add_column("Name")
        table.add_column("predicd-ID", justify="right")
        for name, league_id in sorted(LEAGUES.items()):
            table.add_row(name, str(league_id))
        console.print(table)
        return 0

    try:
        check_combinations(args)

        if args.list_groups:
            return run_list_groups(
                load_credentials(require_group=False), use_browser, headless
            )

        if args.no_kicktipp:
            # Ohne Kicktipp gibt es keine Gruppe und damit keine config.toml —
            # hier zählt allein --league, und --matchday filtert wie bisher
            # die Vorhersagen selbst.
            return run_predictions_only(
                leagues_for("", args.league, groups={}), args.matchday
            )

        # Bei --all-groups und im Menü kommen die Gruppen aus der config.toml;
        # eine KICKTIPP_GROUP in der .env wird dann nicht gebraucht.
        aus_config = args.all_groups or args.interactive
        credentials = load_credentials(args.group, require_group=not aus_config)

        if args.interactive:
            from .interactive import run_interactive

            return run_interactive(credentials, args, use_browser, headless)

        runs = with_strategies(
            all_configured_groups()
            if args.all_groups
            else single_group(credentials, args.league),
            args.strategie,
        )

        if args.list_matchdays:
            return run_list_matchdays(
                credentials, [run.name for run in runs], use_browser, headless
            )

        return run_groups(
            credentials=credentials,
            runs=runs,
            matchday=args.matchday,
            submit=args.submit,
            overwrite=args.overwrite,
            use_browser=use_browser,
            headless=headless,
            allow_partial=args.allow_partial,
        )

    except AutopilotError as error:
        console.print(f"\n[red]Fehler:[/red] {error}")
        return 1
    except KeyboardInterrupt:
        console.print("\nAbgebrochen.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
