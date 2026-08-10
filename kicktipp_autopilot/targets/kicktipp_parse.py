"""Parsen der Kicktipp-Seiten — reines HTML→Objekte, ohne Netzwerk und Browser.

Diese Datei ist bewusst frei von httpx und Selenium: Beide Transportwege
(`kicktipp_http.py` und `kicktipp.py`) benutzen denselben Parser. Das hält die
Auswertung an einer Stelle und macht sie offline testbar — was besonders zählt,
weil genau dieser Teil bestimmt, welche Werte später ins Live-Konto geschrieben
werden.

Aufbau des Tippformulars (verifiziert am 09.08.2026):

    form#tippabgabeForm  (POST auf /<gruppe>/tippabgabe)
      ├── tipperId, tippsaisonId, spieltagIndex, bonus   (versteckt)
      ├── spieltippForms[<id>].tippAbgegeben             (versteckt, "true")
      ├── spieltippForms[<id>].heimTipp / .gastTipp      (Textfelder)
      └── fragetippForms[<id>].antwortIds[<antwort>]     (Sonderfragen, <select>)

Die `<id>` ist dieselbe Zahl, die im DOM als `spieltippForms_<id>_heimTipp`
auftaucht — deshalb funktioniert dieser Parser für beide Wege.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from ..models import Fixture
from ..selectors import Kicktipp as S

FORM_SELECTOR = "form#tippabgabeForm"

# spieltippForms[1503034386].heimTipp  ->  1503034386 / heimTipp
_TIP_FIELD_RE = re.compile(r"spieltippForms\[(\d+)\]\.(heimTipp|gastTipp)")

# Tendenzspalte "3 - 9 - 9" und Anstoßzeit "28.08.26 20:30"
_TENDENCY_RE = re.compile(r"[\d\s\-–]+")
_DATE_RE = re.compile(r"\d{1,2}\.\d{1,2}\.\d{2,4}")

# Platzhalter für Paarungen, die noch nicht ausgelost sind. Kicktipp legt den
# Spielplan trotzdem schon an — mit Platzhalternamen und einem Sammeltermin.
# Verifiziert am 10.08.2026 an einer Champions-League-Gruppe: alle 17 Spieltage
# von "1. Spieltag" bis "Finale" waren angelegt, jede Zeile trug "unbekannt".
PLACEHOLDER_TEAM_NAMES = {"unbekannt"}


def is_placeholder(name: str) -> bool:
    return name.strip().casefold() in PLACEHOLDER_TEAM_NAMES

# Pfade, die auf der Übersicht verlinkt sind, aber keine Tippgruppen sind.
NON_GROUP_PATHS = {
    "info", "impressum", "datenschutz", "agb", "kontakt", "hilfe", "faq",
    "profil", "abmelden", "anmelden", "registrieren", "news", "shop",
    "tippspiel-erstellen", "widgets", "app", "blog", "presse", "jobs",
    "spielregeln", "sitemap", "login", "logout",
}


@dataclass
class MatchdayOption:
    """Ein Eintrag aus der Spieltagsauswahl.

    `index` ist der `spieltagIndex` aus der URL — die Zählung der *Gruppe*.
    In Gruppen mit mehreren Wettbewerben ist sie durchlaufend über alle
    Wettbewerbe hinweg und damit ungleich der angezeigten Spieltagnummer:
    Index 25 trägt das Label "8. Spieltag - CL".
    """

    index: int
    label: str
    active: bool = False

    @property
    def competition(self) -> str | None:
        return _competition_of(self.label)


@dataclass
class TippabgabePage:
    """Der ausgewertete Zustand einer Tippabgabe-Seite."""

    fixtures: list[Fixture] = field(default_factory=list)
    #  tip_id -> (Heimtipp, Gasttipp); leere Strings bedeutet "noch nicht getippt"
    existing_tips: dict[str, tuple[str, str]] = field(default_factory=dict)
    #  Vollständiger Formularrumpf, so wie ihn der Browser abschicken würde
    form_fields: dict[str, str] = field(default_factory=dict)
    matchday: int | None = None
    action: str = ""
    #  Voller Titel der Seite, z. B. "8. Spieltag - CL" oder "Finale"
    title: str = ""
    #  Wettbewerbskürzel aus dem Titel, z. B. "CL". None bei nur einem Wettbewerb.
    competition: str | None = None
    #  Alle wählbaren Spieltage der Gruppe (ohne den Bonus-Tab)
    matchdays: list[MatchdayOption] = field(default_factory=list)

    def tip_of(self, fixture: Fixture) -> tuple[str, str]:
        return self.existing_tips.get(fixture.tip_id or "", ("", ""))

    def is_tipped(self, fixture: Fixture) -> bool:
        return any(self.tip_of(fixture))

    @property
    def pending_fixtures(self) -> list[Fixture]:
        """Spiele, deren Paarung Kicktipp noch nicht kennt.

        Sie sind von einer fehlenden Vorhersage zu unterscheiden: Hier fehlt
        nicht die Quelle, sondern die Auslosung. Kein Konfigurationsproblem
        und nichts, was sich durch einen Alias beheben ließe.
        """
        return [
            fixture
            for fixture in self.fixtures
            if is_placeholder(fixture.home_team) and is_placeholder(fixture.away_team)
        ]


def parse_title(html: str | BeautifulSoup) -> str:
    """Der Titel der Spieltagsauswahl, z. B. "8. Spieltag - CL"."""
    soup = _soup(html)
    title = soup.select_one(S.MATCHDAY_TITLE)
    return title.get_text(" ", strip=True) if title is not None else ""


def parse_matchday(html: str | BeautifulSoup) -> int | None:
    """Spieltagnummer der Seite — nur ein Hinweis, kein Sicherheitskriterium.

    Bei K.-o.-Runden steht dort "Finale" oder "Achtelfinale", also keine Zahl.
    Genau daran ist das Altskript gescheitert.

    Achtung: Das ist die *angezeigte* Nummer, nicht der `spieltagIndex` aus der
    URL. In Gruppen mit mehreren Wettbewerben laufen die beiden auseinander.
    """
    match = re.search(r"\d+", parse_title(html))
    return int(match.group()) if match else None


def _competition_of(label: str) -> str | None:
    """"8. Spieltag - CL" -> "CL"; "8. Spieltag" -> None.

    Das Kürzel vergibt der Gruppenadmin frei, es ist also kein verlässlicher
    Liganame — nur ein Anhaltspunkt für die Ausgabe. Welche Vorhersage zu
    welchem Spiel gehört, entscheidet weiterhin allein die Paarung.
    """
    _, separator, suffix = label.partition(" - ")
    return suffix.strip() or None if separator else None


def parse_competition(html: str | BeautifulSoup) -> str | None:
    return _competition_of(parse_title(html))


def parse_matchday_options(html: str | BeautifulSoup) -> list[MatchdayOption]:
    """Liest die wählbaren Spieltage aus dem Aufklappmenü.

    Der Bonus-Eintrag fällt heraus: Er ist kein Spieltag, sondern ein eigener
    Reiter mit den Sonderfragen.
    """
    soup = _soup(html)
    options: list[MatchdayOption] = []
    seen: set[int] = set()

    for entry in soup.select(S.MATCHDAY_OPTIONS):
        classes = set(entry.get("class") or [])
        if S.MATCHDAY_OPTION_BONUS in classes:
            continue
        link = entry.find("a", href=True)
        if link is None:
            continue
        match = re.search(r"spieltagIndex=(\d+)", link["href"])
        if not match:
            continue
        index = int(match.group(1))
        if index in seen:
            continue
        seen.add(index)
        options.append(
            MatchdayOption(
                index=index,
                label=link.get_text(" ", strip=True),
                active=S.MATCHDAY_OPTION_ACTIVE in classes,
            )
        )

    return options


def parse_fixtures(html: str | BeautifulSoup) -> list[Fixture]:
    """Liest die Spielpaarungen.

    Angesetzt wird am **Tippfeld**, nicht an Klassennamen: Im ausgelieferten
    HTML tragen die Zeilen gar keine Klassen — `datarow` und `col1`/`col2`
    ergänzt erst JavaScript im Browser. Ein Parser, der sich darauf stützt,
    funktioniert deshalb nur im Browser.

    Sonderfragen ("Wer wird Deutscher Meister?") stehen in denselben
    Tabellenzeilen, tragen aber `fragetippForms`-Felder statt
    `spieltippForms`. Sie fallen dadurch strukturell heraus — nicht erst
    dadurch, dass die Zuordnung fehlschlägt.
    """
    soup = _soup(html)
    kickoffs = _kickoff_by_row(soup)
    fixtures: list[Fixture] = []
    seen: set[str] = set()

    for element in soup.select("input[name^='spieltippForms']"):
        match = _TIP_FIELD_RE.fullmatch(element.get("name", ""))
        if not match:
            continue
        tip_id = match.group(1)
        if tip_id in seen:
            continue

        row = element.find_parent("tr")
        if row is None:
            continue

        teams = _team_names(row)
        if len(teams) < 2:
            continue

        seen.add(tip_id)
        fixtures.append(
            Fixture(
                home_team=teams[0],
                away_team=teams[1],
                tip_id=tip_id,
                kickoff=kickoffs.get(id(row)),
            )
        )

    return fixtures


def _kickoff_by_row(soup: BeautifulSoup) -> dict[int, str]:
    """Ordnet jeder Spielzeile ihre Anstoßzeit zu.

    Kicktipp schreibt die Zeit nur in die **erste** Zeile eines Anstoßblocks;
    die Folgezeilen haben eine leere Terminzelle. Der zuletzt gesehene Wert
    wird deshalb weitergereicht — je Tabelle getrennt, damit die Zeiten der
    Spieltabelle nicht in die Tabelle der Sonderfragen überlaufen.

    Die Zuordnung läuft über *alle* Zeilen, nicht nur über tippbare: Ist die
    erste Zeile eines Blocks bereits angepfiffen (und damit ohne Tippfelder),
    steht die Uhrzeit trotzdem nur dort.
    """
    kickoffs: dict[int, str] = {}

    for table in soup.find_all("table"):
        current = ""
        for row in table.find_all("tr"):
            cell = row.select_one(S.KICKOFF_CELL)
            if cell is None:
                continue
            text = cell.get_text(" ", strip=True)
            if text:
                current = text
            if current:
                kickoffs[id(row)] = current

    return kickoffs


def _team_names(row: Tag) -> list[str]:
    """Ermittelt Heim- und Gastnamen einer Spielzeile.

    Inhaltlich statt über Spaltennummern, damit eine zusätzliche Spalte bei
    Kicktipp nicht sofort alles bricht. Aussortiert werden: Anstoßzeit,
    Quoten, die Eingabezelle sowie die Tendenzspalte ("3 - 9 - 9").
    """
    names: list[str] = []

    for cell in row.find_all("td"):
        classes = set(cell.get("class") or [])
        if classes & {"kicktipp-time", "quoten", "kicktipp-tippabgabe"}:
            continue
        if cell.find(["input", "select"]) is not None:
            continue

        text = cell.get_text(" ", strip=True)
        if not text:
            continue
        if _TENDENCY_RE.fullmatch(text) or _DATE_RE.match(text):
            continue

        names.append(text)

    return names


def parse_existing_tips(html: str | BeautifulSoup) -> dict[str, tuple[str, str]]:
    """Liest die bereits abgegebenen Tipps je Spiel-ID."""
    soup = _soup(html)
    tips: dict[str, list[str]] = {}

    for element in soup.select("input[name^='spieltippForms']"):
        match = _TIP_FIELD_RE.fullmatch(element.get("name", ""))
        if not match:
            continue
        tip_id, which = match.group(1), match.group(2)
        slot = tips.setdefault(tip_id, ["", ""])
        slot[0 if which == "heimTipp" else 1] = (element.get("value") or "").strip()

    return {tip_id: (values[0], values[1]) for tip_id, values in tips.items()}


def parse_form_fields(html: str | BeautifulSoup) -> dict[str, str]:
    """Liest **alle** Formularfelder mit ihren aktuellen Werten.

    Grundlage für den Absende-Rumpf. Kicktipp verarbeitet das Formular als
    Ganzes: Fehlt ein Feld im POST, gilt es als geleert. Würde man nur die
    geänderten Tipps senden, verlöre man alle übrigen Tipps und die Antworten
    auf die Sonderfragen.
    """
    soup = _soup(html)
    form = soup.select_one(FORM_SELECTOR)
    if form is None:
        return {}

    fields: dict[str, str] = {}

    for element in form.find_all(["input", "textarea"]):
        name = element.get("name")
        if not name:
            continue
        input_type = (element.get("type") or "text").lower()
        if input_type in {"checkbox", "radio"} and not element.has_attr("checked"):
            continue
        fields[name] = element.get("value") or ""

    for select in form.find_all("select"):
        name = select.get("name")
        if not name:
            continue
        chosen = select.find("option", selected=True)
        if chosen is None:
            chosen = select.find("option")  # Browser wählt sonst die erste
        fields[name] = (chosen.get("value") or "") if chosen else ""

    # Der Name des angeklickten Buttons gehört zum Rumpf dazu.
    button = form.find("button", attrs={"name": True})
    if button is not None:
        fields[button["name"]] = button.get("value") or ""

    return fields


def parse_page(html: str) -> TippabgabePage:
    """Wertet eine Tippabgabe-Seite vollständig aus."""
    soup = _soup(html)
    form = soup.select_one(FORM_SELECTOR)
    title = parse_title(soup)
    return TippabgabePage(
        fixtures=parse_fixtures(soup),
        existing_tips=parse_existing_tips(soup),
        form_fields=parse_form_fields(soup),
        matchday=parse_matchday(soup),
        action=(form.get("action") if form else "") or "",
        title=title,
        competition=_competition_of(title),
        matchdays=parse_matchday_options(soup),
    )


def build_submit_body(
    page: TippabgabePage, changes: dict[str, tuple[int, int]]
) -> dict[str, str]:
    """Baut den POST-Rumpf: alles unverändert übernehmen, nur `changes` setzen.

    Args:
        page:    Zustand der geladenen Seite.
        changes: tip_id -> (Heimtore, Gasttore).
    """
    body = dict(page.form_fields)

    for tip_id, (home_score, away_score) in changes.items():
        body[f"spieltippForms[{tip_id}].heimTipp"] = str(home_score)
        body[f"spieltippForms[{tip_id}].gastTipp"] = str(away_score)
        body[f"spieltippForms[{tip_id}].tippAbgegeben"] = "true"

    return body


def parse_groups(html: str, base_url: str = "https://www.kicktipp.de") -> list[str]:
    """Liest die Tippgruppen aus der Übersichtsseite."""
    soup = _soup(html)
    groups: list[str] = []

    for link in soup.find_all("a", href=True):
        href = link["href"]
        if href.startswith("http") and not href.startswith(base_url):
            continue
        parts = [part for part in urlparse(href).path.split("/") if part]
        if parts and parts[0] not in NON_GROUP_PATHS and parts[0] not in groups:
            groups.append(parts[0])

    return groups


# ── Hilfsfunktionen ─────────────────────────────────────────────────────


def _soup(html: str | BeautifulSoup) -> BeautifulSoup:
    return html if isinstance(html, BeautifulSoup) else BeautifulSoup(html, "html.parser")


def _tip_id_of_row(row: Tag) -> str | None:
    for element in row.select("input[name^='spieltippForms']"):
        match = _TIP_FIELD_RE.fullmatch(element.get("name", ""))
        if match:
            return match.group(1)
    return None


def _cell_text(row: Tag, selector: str) -> str:
    cell = row.select_one(selector)
    return cell.get_text(strip=True) if cell else ""
