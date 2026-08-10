"""Konfiguration aus .env (Zugangsdaten) und config.toml (Gruppen und Ligen).

Bewusst getrennt: In der `.env` stehen ausschließlich Geheimnisse, sie bleibt
daher aus jeder Weitergabe heraus. Welche Gruppe welche Wettbewerbe tippt, ist
kein Geheimnis, ändert sich aber pro Saison — das gehört in eine eigene,
lesbare Datei.
"""

from __future__ import annotations

import logging
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from .errors import ConfigError

log = logging.getLogger(__name__)

CONFIG_FILENAME = "config.toml"

# predicd-Liga-IDs (URL: predicd.com/de/football/league/<ID>/)
LEAGUES: dict[str, int] = {
    "bundesliga": 4331,
    "bundesliga2": 4399,
    "liga3": 4639,
    "dfb-pokal": 4485,
    "champions-league": 4480,
    "europa-league": 4481,
    "conference-league": 5071,
    "premier-league": 4328,
    "serie-a": 4332,
    "la-liga": 4335,
    "ligue-1": 4334,
    "nations-league": 4490,
    "wm": 4429,
}

DEFAULT_LEAGUE_ID = LEAGUES["bundesliga"]


@dataclass(frozen=True)
class Credentials:
    email: str
    password: str
    group: str


def load_credentials(
    group_override: str | None = None, require_group: bool = True
) -> Credentials:
    """Lädt die Kicktipp-Zugangsdaten aus der .env-Datei.

    Wirft ConfigError mit einer konkreten Handlungsanweisung, wenn etwas fehlt —
    nie einen stillen Standardwert einsetzen.

    Args:
        group_override: Gruppenname, der Vorrang vor der .env hat.
        require_group:  False für Abläufe, die keine Gruppe brauchen
                        (etwa das Auflisten der eigenen Gruppen).
    """
    load_dotenv()

    email = os.getenv("KICKTIPP_EMAIL")
    password = os.getenv("KICKTIPP_PASSWORD")
    group = group_override or os.getenv("KICKTIPP_GROUP") or ""

    required: list[tuple[str, str | None]] = [
        ("KICKTIPP_EMAIL", email),
        ("KICKTIPP_PASSWORD", password),
    ]
    if require_group:
        required.append(("KICKTIPP_GROUP", group))

    missing = [name for name, value in required if not value]
    if missing:
        hint = "\nVorlage: cp example.env .env"
        if "KICKTIPP_GROUP" in missing:
            hint += (
                "\nKICKTIPP_GROUP ist der Teil aus der URL "
                "kicktipp.de/DEIN-GRUPPENNAME/tippabgabe."
                "\nDeine Gruppen anzeigen: python -m kicktipp_autopilot --list-groups"
            )
        raise ConfigError(
            "Folgende Angaben fehlen in der .env-Datei: " + ", ".join(missing) + "." + hint
        )

    assert email and password  # durch die Prüfung oben garantiert
    return Credentials(email=email, password=password, group=group)


def resolve_league(value: str | int | None) -> int:
    """Übersetzt einen Liga-Namen oder eine ID in eine predicd-Liga-ID."""
    if value is None:
        return DEFAULT_LEAGUE_ID
    if isinstance(value, int):
        return value
    if value.isdigit():
        return int(value)

    key = value.strip().lower()
    if key in LEAGUES:
        return LEAGUES[key]

    raise ConfigError(
        f"Unbekannte Liga: {value!r}. "
        f"Bekannte Namen: {', '.join(sorted(LEAGUES))} "
        "— oder direkt eine numerische predicd-Liga-ID angeben."
    )


@dataclass(frozen=True)
class LeagueRef:
    """Eine Liga mit Name *und* ID.

    Der Slug wird gebraucht, sobald mehrere Ligen im Spiel sind: Er bestimmt
    die Alias-Datei (`matching/aliases/<slug>.json`) und beschriftet die
    Herkunft jeder Vorhersage. `resolve_league` allein gibt nur die Zahl
    zurück und verliert genau diese Information.
    """

    slug: str
    predicd_id: int

    def __str__(self) -> str:
        return self.slug


def _slug_for(league_id: int) -> str:
    for name, value in LEAGUES.items():
        if value == league_id:
            return name
    return str(league_id)


def resolve_league_ref(value: str | int) -> LeagueRef:
    league_id = resolve_league(value)
    return LeagueRef(slug=_slug_for(league_id), predicd_id=league_id)


def resolve_leagues(values: list[str] | None) -> list[LeagueRef]:
    """Übersetzt CLI-Angaben in Liga-Referenzen.

    Erlaubt sind Mehrfachangaben und Kommalisten, also sowohl
    `--league bundesliga --league champions-league` als auch
    `--league bundesliga,champions-league`. Doppelte Nennungen fallen weg,
    die Reihenfolge bleibt erhalten.
    """
    if not values:
        return []

    refs: list[LeagueRef] = []
    for value in values:
        for part in str(value).split(","):
            part = part.strip()
            if not part:
                continue
            ref = resolve_league_ref(part)
            if ref not in refs:
                refs.append(ref)
    return refs


@dataclass(frozen=True)
class GroupConfig:
    """Was in `config.toml` über eine Tippgruppe hinterlegt ist."""

    name: str
    leagues: list[LeagueRef] = field(default_factory=list)


# Verzeichnis, in dem das Paket liegt — dort steht auch die config.toml.
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def config_path(explicit: str | Path | None = None) -> Path:
    """Wo die config.toml gesucht wird: erst im Arbeitsverzeichnis, dann beim Paket.

    Der zweite Ort ist nötig, damit ein Aufruf aus einem beliebigen
    Verzeichnis nicht stillschweigend ohne Konfiguration läuft und
    stattdessen auf Bundesliga zurückfällt — eine gemischte Gruppe würde dann
    unerklärlich scheitern. Dasselbe Problem löst python-dotenv für die .env
    auf die gleiche Weise.
    """
    if explicit:
        return Path(explicit)

    lokal = Path.cwd() / CONFIG_FILENAME
    if lokal.exists():
        return lokal
    return PROJECT_ROOT / CONFIG_FILENAME


def load_group_config(path: str | Path | None = None) -> dict[str, GroupConfig]:
    """Liest `config.toml`, falls vorhanden.

    Eine fehlende Datei ist **kein Fehler**: Ohne sie verhält sich der
    Autopilot wie bisher und tippt die über `--league` gewählte Liga. Erst wer
    mehrere Wettbewerbe in einer Gruppe hat, braucht sie.

    Format::

        [[gruppen]]
        name  = "bl-cl-1"
        ligen = ["bundesliga", "champions-league"]
    """
    file = config_path(path)
    if not file.exists():
        log.debug("Keine %s gefunden — es gilt die Liga aus --league.", file)
        return {}

    try:
        data = tomllib.loads(file.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{file} ist kein gültiges TOML: {exc}") from exc

    entries = data.get("gruppen", [])
    if not isinstance(entries, list):
        raise ConfigError(
            f"{file}: 'gruppen' muss eine Liste von [[gruppen]]-Abschnitten sein."
        )

    groups: dict[str, GroupConfig] = {}
    for position, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ConfigError(f"{file}: Eintrag {position} ist kein [[gruppen]]-Abschnitt.")

        name = str(entry.get("name") or "").strip()
        if not name:
            raise ConfigError(f"{file}: Eintrag {position} hat kein 'name'-Feld.")
        if name in groups:
            raise ConfigError(f"{file}: Gruppe {name!r} ist mehrfach eingetragen.")

        raw = entry.get("ligen", [])
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            raise ConfigError(
                f"{file}: 'ligen' bei Gruppe {name!r} muss eine Liste sein, "
                'z. B. ligen = ["bundesliga", "champions-league"].'
            )

        try:
            leagues = resolve_leagues([str(item) for item in raw])
        except ConfigError as exc:
            raise ConfigError(f"{file}, Gruppe {name!r}: {exc}") from exc

        groups[name] = GroupConfig(name=name, leagues=leagues)

    return groups


def all_configured_groups(path: str | Path | None = None) -> list[GroupConfig]:
    """Alle Gruppen aus `config.toml` — die Grundlage von `--all-groups` und `-i`.

    Bewusst nicht die Gruppen des Kontos: Dort stehen auch abgelaufene
    Saisons, und ohne `[[gruppen]]`-Eintrag wäre nicht bekannt, welche
    Wettbewerbe eine Gruppe tippt. Was hier steht, ist ausdrücklich gewollt.
    """
    groups = load_group_config(path)
    if not groups:
        raise ConfigError(
            "Dafür braucht es [[gruppen]]-Einträge in der config.toml — sonst "
            "ist nicht bekannt, welche Gruppen es gibt und welche Wettbewerbe "
            "sie tippen.\n"
            "Vorlage:        cp example.config.toml config.toml\n"
            "Eigene Gruppen: kicktipp --list-groups"
        )
    return list(groups.values())


def leagues_for(
    group: str, cli_leagues: list[str] | None, groups: dict[str, GroupConfig] | None = None
) -> list[LeagueRef]:
    """Welche Ligen für eine Gruppe gelten.

    Vorrang: ausdrückliche `--league`-Angabe → Eintrag aus `config.toml` →
    Bundesliga als Vorgabe.
    """
    explicit = resolve_leagues(cli_leagues)
    if explicit:
        return explicit

    entry = (groups if groups is not None else load_group_config()).get(group)
    if entry and entry.leagues:
        return entry.leagues

    return [resolve_league_ref("bundesliga")]
