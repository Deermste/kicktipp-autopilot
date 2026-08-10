"""Das Menü hinter `kicktipp -i`.

Der Ablauf ist bewusst derselbe wie auf der Kommandozeile — nur die Auswahl
kommt aus Pfeiltasten statt aus Argumenten. Vor dem Absenden steht **immer**
die Vorschau und danach eine Rückfrage; abgeschickt wird genau das, was in der
Vorschau stand (dieselbe Sitzung, dieselben Vorhersagen).

Kein Menü ohne Terminal: Ein Timer aus Phase 5 würde sonst an einer Rückfrage
hängen bleiben, ohne dass jemand es merkt.
"""

from __future__ import annotations

import argparse
import sys

from .config import Credentials, GroupConfig, all_configured_groups
from .errors import ConfigError
from .runner import console, make_target, run_groups
from .sources.predicd import PredicdSource


def _questionary():
    """`questionary` erst laden, wenn es gebraucht wird.

    So bleibt der ganze übrige Autopilot lauffähig, wenn die Abhängigkeit
    fehlt — und die Meldung sagt, was zu tun ist, statt einen Traceback zu
    zeigen.
    """
    try:
        import questionary
    except ImportError as exc:  # pragma: no cover — hängt an der Installation
        raise ConfigError(
            "Für das Menü fehlt das Paket questionary.\n"
            "Nachinstallieren:  pip install questionary\n"
            "Ohne Menü geht es weiter mit:  kicktipp --all-groups"
        ) from exc
    return questionary


def choose_groups(groups: list[GroupConfig]) -> list[GroupConfig]:
    """Mehrfachauswahl über die Gruppen aus der config.toml."""
    questionary = _questionary()

    auswahl = questionary.checkbox(
        "Welche Gruppen sollen getippt werden?",
        choices=[
            questionary.Choice(
                title=f"{group.name}  —  {', '.join(l.slug for l in group.leagues) or 'bundesliga'}",
                value=group.name,
                checked=True,
            )
            for group in groups
        ],
        instruction="(Leertaste wählt aus, Enter bestätigt)",
    ).ask()

    # `ask()` gibt bei Strg-C None zurück — das ist ein Abbruch, keine leere
    # Auswahl, und darf nicht als „nichts tippen" durchgehen.
    if auswahl is None:
        raise KeyboardInterrupt

    gewaehlt = set(auswahl)
    return [group for group in groups if group.name in gewaehlt]


def confirm_submit(anzahl: int) -> bool:
    questionary = _questionary()
    antwort = questionary.confirm(
        f"Diese Tipps in {anzahl} Gruppe(n) jetzt bei Kicktipp eintragen?",
        default=False,
    ).ask()
    if antwort is None:
        raise KeyboardInterrupt
    return bool(antwort)


def run_interactive(
    credentials: Credentials,
    args: argparse.Namespace,
    use_browser: bool = False,
    headless: bool = True,
) -> int:
    """Auswählen, Vorschau zeigen, nachfragen, absenden."""
    if not sys.stdin.isatty():
        raise ConfigError(
            "Das Menü (-i) braucht ein Terminal. Für Skripte und Timer: "
            "kicktipp --all-groups [--submit]"
        )

    # Dieselbe Quelle wie --all-groups: Was in der config.toml steht, ist
    # ausdrücklich gewollt und hat seine Wettbewerbe hinterlegt.
    gewaehlt = choose_groups(all_configured_groups())
    if not gewaehlt:
        console.print("[dim]Keine Gruppe ausgewählt — nichts zu tun.[/dim]")
        return 0

    # Sitzung und Vorhersagen einmal für Vorschau *und* Abgabe: kein zweiter
    # Login, kein zweiter predicd-Abruf, und vor allem keine Chance, dass sich
    # zwischen Anzeige und Absenden etwas ändert.
    source = PredicdSource()
    with make_target(credentials, use_browser, headless) as kicktipp:
        kicktipp.login()

        code = run_groups(
            credentials=credentials,
            runs=gewaehlt,
            submit=False,
            overwrite=args.overwrite,
            allow_partial=args.allow_partial,
            target=kicktipp,
            source=source,
            # Wie bei --all-groups: Die Gruppen stehen in der config.toml, ein
            # gerade nicht tippbarer Spieltag ist dort kein Fehler.
            require_fixtures=False,
        )

        if not confirm_submit(len(gewaehlt)):
            console.print("\n[dim]Nichts abgesendet.[/dim]")
            return code

        return run_groups(
            credentials=credentials,
            runs=gewaehlt,
            submit=True,
            overwrite=args.overwrite,
            allow_partial=args.allow_partial,
            target=kicktipp,
            source=source,
            # Wie bei --all-groups: Die Gruppen stehen in der config.toml, ein
            # gerade nicht tippbarer Spieltag ist dort kein Fehler.
            require_fixtures=False,
        )
