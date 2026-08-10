"""Zuordnung von Vorhersagen zu Kicktipp-Spielen.

Leitgedanke: **nie stillschweigend raten.** Lieber ein Spiel als „nicht
zuordenbar" melden, als einen falschen Tipp einzutragen — ein falscher Tipp
fällt erst auf, wenn die Punkte fehlen.

Zugeordnet wird immer über die *Paarung* (Heim und Gast müssen beide passen),
nie über ein einzelnes Team. Damit ist die Zuordnung auch dann eindeutig, wenn
die Spieltagnummer nicht lesbar ist — genau der Fall, an dem das Altskript
gescheitert ist.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from ..models import Fixture, MatchResult, Prediction, dedupe_predictions
from .normalize import normalize

log = logging.getLogger(__name__)

ALIAS_DIR = Path(__file__).parent / "aliases"

# Ab dieser Ähnlichkeit gilt ein Team als erkannt. Bewusst hoch angesetzt:
# lieber eine Meldung zu viel als ein falscher Tipp.
DEFAULT_CUTOFF = 0.85

# "29.01.25 20:55" / "29.01. 20:55" -> (Tag, Monat)
_DAY_MONTH_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.")


def load_aliases(league: str | Iterable[str] = "bundesliga") -> dict[str, str]:
    """Lädt die Alias-Tabellen einer oder mehrerer Ligen (Quellname -> Kicktipp-Name).

    Mehrere Ligen werden zu einer Tabelle verschmolzen. Das ist zulässig, weil
    die Schlüssel Vereinsnamen sind: Derselbe Verein heißt bei predicd in jedem
    Wettbewerb gleich. Widersprüchliche Einträge wären ein Pflegefehler und
    werden deshalb gemeldet statt still überschrieben.
    """
    leagues = [league] if isinstance(league, str) else list(league)
    merged: dict[str, str] = {}
    origin: dict[str, str] = {}

    for slug in leagues:
        path = ALIAS_DIR / f"{slug}.json"
        if not path.exists():
            log.debug("Keine Alias-Datei für %r — arbeite nur mit Normalisierung.", slug)
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, value in data.items():
            if key.startswith("_"):
                continue
            if key in merged and merged[key] != value:
                log.warning(
                    "Widersprüchlicher Alias für %r: %r (%s) gegen %r (%s). "
                    "Der zuerst geladene gilt.",
                    key, merged[key], origin[key], value, slug,
                )
                continue
            merged[key] = value
            origin[key] = slug

    return merged


@dataclass
class MatchReport:
    """Ergebnis eines Zuordnungslaufs."""

    matched: list[MatchResult] = field(default_factory=list)
    unmatched_fixtures: list[Fixture] = field(default_factory=list)
    unused_predictions: list[Prediction] = field(default_factory=list)
    #  Paarungen, zu denen mehrere widersprüchliche Vorhersagen passen. Sie
    #  werden bewusst *nicht* zugeordnet — im Zweifel lieber gar kein Tipp.
    ambiguous: list[tuple[Fixture, list[Prediction]]] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.matched

    @property
    def has_gaps(self) -> bool:
        """Gibt es Spiele auf der Seite, für die kein Tipp feststeht?"""
        return bool(self.unmatched_fixtures or self.ambiguous)


def _day_month(text: str | None) -> tuple[int, int] | None:
    match = _DAY_MONTH_RE.search(text or "")
    return (int(match.group(1)), int(match.group(2))) if match else None


def _narrow_by_kickoff(
    fixture: Fixture, candidates: list[Prediction]
) -> list[Prediction]:
    """Grenzt mehrere Kandidaten über das Spieldatum ein.

    Verglichen wird nur **Tag und Monat**, nicht die Uhrzeit: Kicktipps
    Terminspalte ist der *Tipptermin* und liegt teils einige Minuten vor dem
    Anpfiff, den predicd nennt. Dieselbe Paarung am selben Kalendertag in zwei
    Wettbewerben gibt es nicht — als Unterscheidungsmerkmal reicht das Datum.

    Lässt sich nichts eingrenzen, kommen alle Kandidaten unverändert zurück;
    entschieden wird dann gegen die Zuordnung.
    """
    target = _day_month(fixture.kickoff)
    if target is None:
        return candidates
    narrowed = [p for p in candidates if _day_month(p.kickoff) == target]
    return narrowed or candidates


class TeamMatcher:
    """Ordnet Vorhersagen den Spielen einer Kicktipp-Seite zu."""

    def __init__(
        self, aliases: dict[str, str] | None = None, cutoff: float = DEFAULT_CUTOFF
    ) -> None:
        self._aliases = aliases or {}
        self._cutoff = cutoff

    def _key(self, name: str) -> str:
        """Alias anwenden (falls vorhanden), dann normalisieren."""
        return normalize(self._aliases.get(name.strip(), name))

    def match(
        self, fixtures: list[Fixture], predictions: list[Prediction]
    ) -> MatchReport:
        report = MatchReport()
        # Auch hier noch einmal: Beim Zusammenwerfen mehrerer Ligen können
        # Doppelungen entstehen, die eine einzelne Quelle nicht hatte.
        remaining = dedupe_predictions(predictions)

        # ── Durchgang 1: exakte Paarungen nach Alias + Normalisierung ─────
        # Bewusst eine Liste je Schlüssel: Dieselbe Paarung kann in zwei
        # Wettbewerben vorkommen (Bayern gegen Dortmund gibt es in der
        # Bundesliga wie im Pokal). Ein Dict würde die eine Vorhersage
        # stillschweigend mit der anderen überschreiben — und damit womöglich
        # einen falschen Tipp eintragen.
        index: dict[tuple[str, str], list[Prediction]] = {}
        for prediction in remaining:
            key = (self._key(prediction.home_team), self._key(prediction.away_team))
            index.setdefault(key, []).append(prediction)

        still_open: list[Fixture] = []
        for fixture in fixtures:
            key = (self._key(fixture.home_team), self._key(fixture.away_team))
            candidates = [p for p in index.get(key, []) if p in remaining]

            if len(candidates) > 1:
                candidates = _narrow_by_kickoff(fixture, candidates)
            if len(candidates) > 1:
                log.warning(
                    "%s passt auf %d widersprüchliche Vorhersagen (%s) — "
                    "nicht zugeordnet.",
                    fixture,
                    len(candidates),
                    ", ".join(sorted({p.league or "?" for p in candidates})),
                )
                report.ambiguous.append((fixture, candidates))
                continue

            if candidates:
                prediction = candidates[0]
                # Die Alias-Schlüssel sind Namen der *Quelle* (predicd), nicht
                # die von Kicktipp — also gegen die Vorhersage prüfen.
                method = (
                    "alias"
                    if prediction.home_team in self._aliases
                    or prediction.away_team in self._aliases
                    else "exact"
                )
                report.matched.append(
                    MatchResult(fixture=fixture, prediction=prediction, method=method)
                )
                remaining.remove(prediction)
            else:
                still_open.append(fixture)

        # ── Durchgang 2: Ähnlichkeitssuche für den Rest ───────────────────
        for fixture in still_open:
            prediction, score = self._best_fuzzy_match(fixture, remaining)
            if prediction is None:
                report.unmatched_fixtures.append(fixture)
                continue
            report.matched.append(
                MatchResult(
                    fixture=fixture,
                    prediction=prediction,
                    method="fuzzy",
                    confidence=score,
                )
            )
            log.warning(
                "Unscharfe Zuordnung (%.0f%%): %s → %s. "
                "Bitte Alias in matching/aliases/ ergänzen.",
                score * 100,
                fixture,
                prediction,
            )
            remaining.remove(prediction)

        report.unused_predictions = remaining
        return report

    def _best_fuzzy_match(
        self, fixture: Fixture, candidates: list[Prediction]
    ) -> tuple[Prediction | None, float]:
        """Sucht die ähnlichste Paarung.

        Beide Teams müssen den Schwellwert erreichen. Liegen zwei Kandidaten
        gleichauf, gilt die Zuordnung als mehrdeutig und wird verworfen.
        """
        home_key = self._key(fixture.home_team)
        away_key = self._key(fixture.away_team)

        scored: list[tuple[float, Prediction]] = []
        for prediction in candidates:
            home_ratio = SequenceMatcher(
                None, home_key, self._key(prediction.home_team)
            ).ratio()
            away_ratio = SequenceMatcher(
                None, away_key, self._key(prediction.away_team)
            ).ratio()
            # Das schwächere der beiden Teams entscheidet.
            scored.append((min(home_ratio, away_ratio), prediction))

        if not scored:
            return None, 0.0

        scored.sort(key=lambda item: item[0], reverse=True)
        best_score, best_prediction = scored[0]

        if best_score < self._cutoff:
            return None, best_score

        if len(scored) > 1 and abs(scored[1][0] - best_score) < 1e-9:
            log.warning(
                "Mehrdeutige Zuordnung für %s — verworfen statt geraten.", fixture
            )
            return None, best_score

        return best_prediction, best_score
