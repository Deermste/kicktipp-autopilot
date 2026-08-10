"""Der Ablauf: Vorhersagen holen, zuordnen, anzeigen, absenden.

Hier steht, *was* passiert; in `cli.py` steht nur noch, wie man es aufruft.
Die Trennung ist nötig, weil `interactive.py` denselben Ablauf braucht und ein
gegenseitiger Import mit der Kommandozeile ein Zyklus wäre.

Grundregel wie überall: **Lesen ist der Normalfall, Schreiben braucht eine
ausdrückliche Ansage.** Ohne `submit=True` wird nichts abgesendet.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from rich.console import Console
from rich.table import Table

from .config import LEAGUES, Credentials, GroupConfig, LeagueRef
from .errors import AutopilotError, MappingError, NotDrawnError, SubmissionError
from .matching.matcher import MatchReport, TeamMatcher, load_aliases
from .models import Prediction
from .sources.predicd import PredicdSource
from .targets.base import TippTarget
from .targets.kicktipp import KicktippBrowser
from .targets.kicktipp_http import KicktippHttp

console = Console()
log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5


def _league_name(league_id: int) -> str:
    for name, value in LEAGUES.items():
        if value == league_id:
            return name
    return str(league_id)


# ── Ausgaben ────────────────────────────────────────────────────────────


def render_predictions(predictions: list[Prediction], league_id: int) -> None:
    """Reine Vorhersageliste (ohne Kicktipp-Abgleich)."""
    matchday = predictions[0].matchday if predictions else None
    title = f"{_league_name(league_id)}"
    if matchday:
        title += f" · Spieltag {matchday}"

    table = Table(title=title, header_style="bold")
    table.add_column("Anstoß", style="dim")
    table.add_column("Heim")
    table.add_column("Gast")
    table.add_column("Tipp", justify="center", style="bold")

    for prediction in predictions:
        table.add_row(
            prediction.kickoff or "—",
            prediction.home_team,
            prediction.away_team,
            f"{prediction.home_score}:{prediction.away_score}",
        )
    console.print(table)


def render_plan(
    report: MatchReport,
    group: str,
    existing: dict[str, str],
    title: str = "",
    pending_ids: set[str | None] | None = None,
) -> None:
    """Zeigt, was eingetragen würde — inklusive der Problemfälle."""
    heading = f"Tippabgabe · {group}"
    if title:
        heading += f" · {title}"

    table = Table(title=heading, header_style="bold")
    table.add_column("Heim")
    table.add_column("Gast")
    table.add_column("Tipp", justify="center", style="bold")
    table.add_column("Liga", style="dim")
    table.add_column("Status")

    for match in report.matched:
        status = existing.get(str(match.fixture), "[green]wird eingetragen[/green]")
        if match.method == "fuzzy":
            status += f" [yellow](unscharf {match.confidence:.0%})[/yellow]"
        table.add_row(
            match.fixture.home_team,
            match.fixture.away_team,
            f"{match.prediction.home_score}:{match.prediction.away_score}",
            match.prediction.league or "—",
            status,
        )

    offen = pending_ids or set()
    for fixture in report.unmatched_fixtures:
        status = (
            "[dim]noch nicht ausgelost[/dim]"
            if fixture.tip_id in offen
            else "[red]keine Vorhersage[/red]"
        )
        table.add_row(fixture.home_team, fixture.away_team, "—", "—", status)

    for fixture, candidates in report.ambiguous:
        table.add_row(
            fixture.home_team,
            fixture.away_team,
            "—",
            ", ".join(sorted({p.league or "?" for p in candidates})),
            "[red]mehrdeutig — nicht geraten[/red]",
        )

    console.print(table)

    # Bei mehreren Ligen ist der ungenutzte Rest der Normalfall: Auf der Seite
    # steht nur ein Wettbewerb, die Vorhersagen des anderen bleiben zwangsläufig
    # übrig. Deshalb nur auf Wunsch anzeigen.
    if report.unused_predictions and log.isEnabledFor(logging.DEBUG):
        console.print(
            "\n[dim]Nicht verwendete Vorhersagen "
            f"({len(report.unused_predictions)}): "
            + ", ".join(str(p) for p in report.unused_predictions)
            + "[/dim]"
        )


# ── Ergebnis je Gruppe ──────────────────────────────────────────────────

#  Mögliche Werte von GroupOutcome.status. Nur FEHLER zählt als gescheitert:
#  Ein Spieltag, der noch nicht ausgelost oder noch nicht offen ist, ist ein
#  Zustand der Welt und nichts, wogegen sich etwas tun ließe.
EINGETRAGEN = "eingetragen"
NICHTS_ZU_TUN = "nichts zu tun"
KEIN_SPIELTAG = "kein offener Spieltag"
NICHT_AUSGELOST = "noch nicht ausgelost"
VORSCHAU = "Vorschau"
FEHLER = "Fehler"


@dataclass
class GroupOutcome:
    """Was in einer Gruppe passiert ist.

    Braucht es, sobald mehrere Gruppen in einem Lauf drankommen: Ein einzelner
    Rückgabecode könnte nicht sagen, *welche* Gruppe getippt wurde und welche
    nur deshalb leer ausging, weil gerade kein Spieltag offen ist.
    """

    group: str
    status: str
    title: str = ""
    matched: int = 0
    fixtures: int = 0
    written: int = 0
    message: str = ""

    @property
    def failed(self) -> bool:
        return self.status == FEHLER


def render_summary(outcomes: list[GroupOutcome]) -> None:
    """Sammelübersicht am Ende eines Mehrgruppenlaufs."""
    farbe = {
        EINGETRAGEN: "green",
        VORSCHAU: "cyan",
        NICHTS_ZU_TUN: "dim",
        KEIN_SPIELTAG: "dim",
        NICHT_AUSGELOST: "dim",
        FEHLER: "red",
    }

    table = Table(title="Zusammenfassung", header_style="bold")
    table.add_column("Gruppe", no_wrap=True)
    table.add_column("Spieltag", style="dim", no_wrap=True)
    table.add_column("erkannt", justify="right", no_wrap=True)
    table.add_column("getippt", justify="right", no_wrap=True)
    # Die vollständige Meldung stand bereits unter der jeweiligen Gruppe; hier
    # zählt der schnelle Überblick, deshalb eine Zeile je Gruppe statt eines
    # umgebrochenen Absatzes.
    table.add_column("Status", no_wrap=True, overflow="ellipsis")

    for outcome in outcomes:
        stil = farbe.get(outcome.status, "")
        status = f"[{stil}]{outcome.status}[/{stil}]" if stil else outcome.status
        if outcome.message:
            status += f" [dim]— {outcome.message.splitlines()[0]}[/dim]"
        table.add_row(
            outcome.group,
            outcome.title or "—",
            f"{outcome.matched}/{outcome.fixtures}" if outcome.fixtures else "—",
            str(outcome.written) if outcome.written else "—",
            status,
        )

    console.print()
    console.print(table)


# ── Abläufe ─────────────────────────────────────────────────────────────


def run_predictions_only(leagues: list[LeagueRef], matchday: int | None) -> int:
    """Nur die Vorhersagen anzeigen — je angeforderter Liga eine Tabelle.

    Hier filtert `--matchday` noch die Vorhersagen selbst: Ohne Kicktipp gibt
    es keinen Spieltagindex einer Gruppe, auf den er sich beziehen könnte.
    """
    source = PredicdSource()
    gesamt = 0
    for league in leagues:
        predictions = source.get_predictions(league.predicd_id, matchday)
        render_predictions(predictions, league.predicd_id)
        gesamt += len(predictions)

    console.print(
        f"\n[green]{gesamt} Vorhersagen geladen.[/green] "
        "Kein Kicktipp-Abgleich (--group fehlt)."
    )
    return 0


def make_target(
    credentials: Credentials, use_browser: bool, headless: bool
) -> TippTarget:
    """Wählt den Transportweg: HTTP (Standard) oder Browser (Rückfallebene)."""
    if use_browser:
        return KicktippBrowser(credentials, headless=headless)
    return KicktippHttp(credentials)


def run_groups(
    credentials: Credentials,
    runs: list[GroupConfig],
    matchday: int | None = None,
    submit: bool = False,
    overwrite: bool = False,
    use_browser: bool = False,
    headless: bool = True,
    allow_partial: bool = False,
    target: TippTarget | None = None,
    source: PredicdSource | None = None,
    require_fixtures: bool | None = None,
) -> int:
    """Arbeitet eine oder mehrere Gruppen in **einer** Sitzung ab.

    Ein Codepfad für beides: Der Einzelgruppenaufruf ist der Sonderfall mit
    einem Element in `runs`. So können die Abläufe nicht auseinanderlaufen.

    `target` und `source` sind für das interaktive Menü gedacht, das erst eine
    Vorschau und danach die Abgabe fährt: Beides läuft dann über dieselbe
    angemeldete Sitzung und denselben Vorhersage-Cache — abgesendet wird
    garantiert das, was in der Vorschau stand.

    `require_fixtures` entscheidet, ob eine Gruppe ohne offenen Spieltag ein
    Fehler ist. Standard ist „ja, wenn genau eine Gruppe genannt wurde": Dort
    ist ein Tippfehler im Gruppennamen die näherliegende Ursache. Kommen die
    Gruppen dagegen aus der config.toml, ist „gerade nichts tippbar" der
    Normalzustand.

    Rückgabe: 0, wenn keine Gruppe gescheitert ist, sonst 1.
    """
    if not runs:
        raise MappingError("Keine Gruppe angegeben.")

    source = source or PredicdSource()
    mehrere = len(runs) > 1
    if require_fixtures is None:
        require_fixtures = not mehrere

    # Vorhersagen je Gruppe zusammenstellen. `PredicdSource` merkt sich die
    # abgerufenen Seiten, deshalb kostet dieselbe Liga in mehreren Gruppen
    # keinen zweiten Abruf.
    def vorhersagen(leagues: list[LeagueRef]) -> list[Prediction]:
        gesammelt: list[Prediction] = []
        for league in leagues:
            gesammelt.extend(source.get_window(league))
        return gesammelt

    fremde_sitzung = target is not None
    outcomes: list[GroupOutcome] = []

    def durchlauf(kicktipp: TippTarget) -> None:
        if not fremde_sitzung:
            kicktipp.login()

        for position, run in enumerate(runs, start=1):
            if mehrere:
                console.rule(f"[bold]{run.name}[/bold]  ({position}/{len(runs)})")

            # Auch eine ausgefallene Vorhersagequelle darf nur diese eine
            # Gruppe kosten, nicht den ganzen Lauf.
            try:
                predictions = vorhersagen(run.leagues)
            except AutopilotError as error:
                console.print(f"\n[red]Fehler ({run.name}):[/red] {error}")
                outcomes.append(GroupOutcome(run.name, FEHLER, message=str(error)))
                continue

            outcomes.append(
                _mit_wiederholung(
                    kicktipp,
                    run,
                    predictions,
                    matchday=matchday,
                    submit=submit,
                    overwrite=overwrite,
                    allow_partial=allow_partial,
                    require_fixtures=require_fixtures,
                )
            )

    if fremde_sitzung:
        assert target is not None
        durchlauf(target)
    else:
        with make_target(credentials, use_browser, headless) as kicktipp:
            durchlauf(kicktipp)

    if mehrere:
        render_summary(outcomes)

    gescheitert = [o for o in outcomes if o.failed]
    if gescheitert:
        # Bei einer einzelnen Gruppe stand die Meldung gerade darüber; eine
        # Bilanz „1 von 1" wäre nur Lärm.
        if mehrere:
            console.print(
                f"\n[red]{len(gescheitert)} von {len(outcomes)} Gruppen "
                "nicht abgearbeitet.[/red]"
            )
        return 1
    return 0


def _mit_wiederholung(
    target: TippTarget,
    run: GroupConfig,
    predictions: list[Prediction],
    *,
    matchday: int | None,
    submit: bool,
    overwrite: bool,
    allow_partial: bool,
    require_fixtures: bool,
) -> GroupOutcome:
    """Eine Gruppe abarbeiten; Netzfehler wiederholen, Denkfehler nicht.

    Wiederholt wird ausschließlich bei `SubmissionError` — also wenn Kicktipp
    nicht erreichbar war, die Sitzung ablief oder das Absenden fehlschlug. Eine
    `MappingError` (fehlende Liga, unbekanntes Team, noch nicht ausgelost)
    fällt beim zweiten Versuch genauso aus; sie wird sofort gemeldet.

    Ein Fehler in einer Gruppe beendet den Lauf nicht: Die übrigen Gruppen
    sind davon unberührt und sollen trotzdem getippt werden.
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return run_one_group(
                target,
                run.name,
                predictions,
                run.leagues,
                matchday=matchday,
                submit=submit,
                overwrite=overwrite,
                allow_partial=allow_partial,
                require_fixtures=require_fixtures,
            )
        except SubmissionError as error:
            if attempt >= MAX_ATTEMPTS:
                console.print(f"\n[red]Fehler ({run.name}):[/red] {error}")
                return GroupOutcome(run.name, FEHLER, message=str(error))
            console.print(
                f"[yellow]Versuch {attempt}/{MAX_ATTEMPTS} fehlgeschlagen:[/yellow] "
                f"{error}\nNeuer Versuch in {RETRY_DELAY_SECONDS} Sekunden …"
            )
            time.sleep(RETRY_DELAY_SECONDS)
            # Die abgelaufene Sitzung ist der wahrscheinlichste Grund — und
            # der einzige, gegen den sich vor dem nächsten Versuch etwas tun
            # lässt. Scheitert auch das, greift die nächste Runde der Schleife.
            try:
                target.login()
            except AutopilotError as neu:
                log.debug("Erneute Anmeldung fehlgeschlagen: %s", neu)
        except NotDrawnError as zu_frueh:
            # Kein Fehler, sondern zu früh — deshalb weder rot noch im
            # Rückgabecode. Die Meldung erklärt sich selbst.
            console.print(f"\n[yellow]{run.name}:[/yellow] {zu_frueh}")
            return GroupOutcome(run.name, NICHT_AUSGELOST)
        except AutopilotError as error:
            console.print(f"\n[red]Fehler ({run.name}):[/red] {error}")
            return GroupOutcome(run.name, FEHLER, message=str(error))

    # Unerreichbar: Die Schleife kehrt in jedem Zweig zurück.
    raise SubmissionError(f"{run.name}: Abgabe fehlgeschlagen.")


def run_one_group(
    target: TippTarget,
    group: str,
    predictions: list[Prediction],
    leagues: list[LeagueRef],
    *,
    matchday: int | None = None,
    submit: bool = False,
    overwrite: bool = False,
    allow_partial: bool = False,
    require_fixtures: bool = True,
) -> GroupOutcome:
    """Eine Gruppe zuordnen, anzeigen und — auf Wunsch — absenden.

    `target` ist bereits geöffnet und angemeldet; die Sitzung gehört dem
    Aufrufer, damit mehrere Gruppen sie teilen können.
    """
    console.print(
        f"[dim]{len(predictions)} Vorhersagen aus "
        f"{len(leagues)} Liga(en): {', '.join(l.slug for l in leagues)}[/dim]"
    )

    page = target.load_page(group, matchday, require_fixtures=require_fixtures)

    # Bei mehreren Gruppen ist „gerade nichts tippbar" der Normalzustand und
    # kein Fehler — in einer Gruppe läuft nun einmal nicht ständig ein
    # Spieltag. Beim Einzelaufruf hat `load_page` schon vorher abgebrochen,
    # denn dort ist ein Tippfehler im Gruppennamen die näherliegende Ursache.
    if not page.fixtures:
        console.print(f"[dim]{group}: kein offener Spieltag — übersprungen.[/dim]")
        return GroupOutcome(group, KEIN_SPIELTAG, title=page.title)

    # Noch nicht ausgeloste Paarungen sind kein Konfigurationsfehler,
    # sondern schlicht zu früh. Ohne diese Unterscheidung würde die
    # Fehlersuche in die falsche Richtung laufen.
    pending = page.pending_fixtures
    if pending and len(pending) == len(page.fixtures):
        raise NotDrawnError(
            f"Kicktipp hat die Paarungen für {page.title or 'diesen Spieltag'} "
            f"noch nicht gesetzt — alle {len(pending)} Spiele stehen als "
            "„unbekannt“ in der Tabelle. Das ist kein Fehler in der "
            "Konfiguration; sobald ausgelost ist, funktioniert der Lauf. "
            "Nichts abgesendet."
        )

    report = TeamMatcher(load_aliases([l.slug for l in leagues])).match(
        page.fixtures, predictions
    )

    if report.is_empty:
        raise MappingError(
            f"Kein einziges der {len(page.fixtures)} Spiele auf "
            f"{page.title or 'der Seite'} konnte zugeordnet werden. "
            "Vermutlich gehört dieser Spieltag zu einem Wettbewerb, der "
            f"nicht konfiguriert ist (geladen: {', '.join(l.slug for l in leagues)}). "
            "Ligen einer Gruppe stehen in config.toml; --list-matchdays "
            "zeigt, welche Spieltage die Gruppe kennt."
        )

    # Welcher Wettbewerb hier tatsächlich läuft, ergibt sich daraus, welche
    # Vorhersagen gepasst haben — nicht aus der Beschriftung der Seite.
    erkannt = sorted({m.prediction.league or "?" for m in report.matched})
    console.print(
        f"[dim]{page.title or 'Spieltag'} · erkannt als "
        f"{', '.join(erkannt)} ({len(report.matched)} von "
        f"{len(page.fixtures)} Spielen)[/dim]"
    )

    # Was tatsächlich geschrieben würde — bereits getippte Spiele bleiben
    # unangetastet, sofern nicht --overwrite gesetzt ist.
    changes: dict[str, tuple[int, int]] = {}
    existing: dict[str, str] = {}
    for match in report.matched:
        values = page.tip_of(match.fixture)
        if any(values) and not overwrite:
            existing[str(match.fixture)] = (
                f"[blue]bereits getippt ({values[0] or '?'}:{values[1] or '?'})[/blue]"
            )
            continue
        if any(values):
            existing[str(match.fixture)] = (
                f"[yellow]überschreibt {values[0]}:{values[1]}[/yellow]"
            )
        assert match.fixture.tip_id is not None
        changes[match.fixture.tip_id] = (
            match.prediction.home_score,
            match.prediction.away_score,
        )

    offene_ids = {f.tip_id for f in pending}
    luecken = [f for f in report.unmatched_fixtures if f.tip_id not in offene_ids]

    render_plan(report, group, existing, page.title, offene_ids)

    ergebnis = GroupOutcome(
        group,
        VORSCHAU,
        title=page.title,
        matched=len(report.matched),
        fixtures=len(page.fixtures),
    )

    if not submit:
        hinweis = f", {len(pending)} noch nicht ausgelost" if pending else ""
        console.print(
            f"\n[green]Dry-Run ({target.name}):[/green] {len(report.matched)} zugeordnet, "
            f"{len(changes)} einzutragen, "
            f"{len(report.matched) - len(changes)} bereits getippt, "
            f"{len(luecken)} ohne Vorhersage, "
            f"{len(report.ambiguous)} mehrdeutig{hinweis}. "
            "[bold]Nichts abgesendet.[/bold] Zum Eintragen: --submit"
        )
        ergebnis.written = len(changes)
        return ergebnis

    # Lücken sind ein Warnsignal, kein Detail: Auf einer Seite steht genau
    # ein Wettbewerb, also müssen alle Spiele zuzuordnen sein. Bleibt etwas
    # übrig, fehlt vermutlich eine Liga in der Konfiguration — dann lieber
    # gar nichts abschicken als einen halben Spieltag.
    # Noch nicht ausgeloste Spiele zählen nicht als Lücke: Für sie gibt es
    # nichts nachzutragen, und sie können auch keinen falschen Tipp
    # erzeugen. Sonst blockierte eine halb ausgeloste Runde alles Übrige.
    if (luecken or report.ambiguous) and not allow_partial:
        offen = [str(f) for f in luecken]
        offen += [f"{f} (mehrdeutig)" for f, _ in report.ambiguous]
        raise MappingError(
            f"{len(offen)} von {len(page.fixtures)} Spielen ohne "
            "eindeutige Vorhersage: " + "; ".join(offen) + ". "
            f"Geladen waren: {', '.join(l.slug for l in leagues)}. "
            "Fehlt eine Liga in config.toml, oder braucht ein Team einen "
            "Alias in matching/aliases/? Nichts abgesendet. "
            "Zum Absenden der übrigen Tipps: --allow-partial"
        )

    if not changes:
        console.print(
            "\n[yellow]Nichts einzutragen[/yellow] — alle zugeordneten Spiele "
            "sind bereits getippt. Nichts abgesendet. "
            "(Zum Ersetzen: --overwrite)"
        )
        ergebnis.status = NICHTS_ZU_TUN
        return ergebnis

    after = target.submit(page, changes)

    # Gegenlesen: Wurde wirklich gespeichert, was gewollt war?
    abweichungen = [
        match
        for match in report.matched
        if match.fixture.tip_id in changes
        and after.tip_of(match.fixture)
        != (str(match.prediction.home_score), str(match.prediction.away_score))
    ]
    if abweichungen:
        raise SubmissionError(
            "Nach dem Absenden stimmen "
            f"{len(abweichungen)} Tipps nicht mit der Vorgabe überein: "
            + ", ".join(str(m.fixture) for m in abweichungen)
        )

    console.print(
        f"\n[green]{len(changes)} Tipps eingetragen, abgesendet und "
        f"gegengelesen.[/green] ({len(report.matched) - len(changes)} unverändert gelassen)"
    )
    ergebnis.status = EINGETRAGEN
    ergebnis.written = len(changes)
    return ergebnis
