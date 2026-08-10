"""Schnittstelle für Vorhersagequellen.

Aktuell gibt es nur predicd. Die Schnittstelle hält die Tür für weitere Quellen
offen (Vergleich, Fallback, eigenes Modell), ohne dass der Rest des Codes
angefasst werden muss.
"""

from __future__ import annotations

from typing import Protocol

from ..models import Prediction


class PredictionSource(Protocol):
    """Liefert Vorhersagen für einen Spieltag einer Liga."""

    name: str

    def get_predictions(
        self, league_id: int, matchday: int | None = None
    ) -> list[Prediction]:
        """Vorhersagen laden.

        Args:
            league_id: ID der Liga bei der Quelle.
            matchday:  Spieltagnummer; None = der aktuell anstehende Spieltag.

        Raises:
            PredictionError: Abruf oder Dekodierung fehlgeschlagen.
        """
        ...
