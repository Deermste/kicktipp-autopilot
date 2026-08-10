"""Tests der Namensnormalisierung."""

import pytest

from kicktipp_autopilot.matching.normalize import normalize


class TestNormalisierungVereinheitlicht:
    """Paare, die predicd und Kicktipp unterschiedlich schreiben.

    Diese Fälle dürfen *keinen* Alias brauchen — Gründungsjahre und
    Rechtsformen tragen nichts zur Unterscheidung bei.
    """

    @pytest.mark.parametrize(
        "predicd_name, kicktipp_name",
        [
            ("TSG Hoffenheim", "1899 Hoffenheim"),
            ("Bayer Leverkusen", "Bayer 04 Leverkusen"),
            ("1. FSV Mainz 05", "FSV Mainz 05"),
            ("1. FC Heidenheim", "1. FC Heidenheim 1846"),
            # Diese drei fehlten in der alten NAME_MAP und rutschten
            # unübersetzt durch — die Normalisierung löst sie automatisch.
            ("SV Elversberg", "SV 07 Elversberg"),
            ("SC Paderborn", "SC Paderborn 07"),
            ("FC Schalke 04", "Schalke 04"),
        ],
    )
    def test_gleicher_schluessel(self, predicd_name: str, kicktipp_name: str) -> None:
        assert normalize(predicd_name) == normalize(kicktipp_name)


class TestKeineFalschenTreffer:
    """Verschiedene Vereine müssen verschieden bleiben.

    Der gefährlichste Fehler wäre eine Normalisierung, die zwei echte Vereine
    zusammenfallen lässt — dann landet ein Tipp beim falschen Spiel.
    """

    @pytest.mark.parametrize(
        "eins, zwei",
        [
            ("Manchester United", "Manchester City"),
            ("Borussia Dortmund", "Borussia M'Gladbach"),
            ("Real Madrid", "Atletico Madrid"),
            ("1. FC Köln", "Viktoria Köln"),
            ("FC Bayern München", "Werder Bremen"),
            ("Bayer Leverkusen", "Bayer Uerdingen"),
        ],
    )
    def test_bleiben_unterschiedlich(self, eins: str, zwei: str) -> None:
        assert normalize(eins) != normalize(zwei)


class TestUmlauteUndAkzente:
    @pytest.mark.parametrize(
        "name, erwartet",
        [
            ("1. FC Köln", "koeln"),
            ("FC Bayern München", "bayern muenchen"),
            ("Fenerbahçe", "fenerbahce"),
        ],
    )
    def test_umschrift(self, name: str, erwartet: str) -> None:
        assert normalize(name) == erwartet

    def test_leerer_name(self) -> None:
        assert normalize("") == ""

    def test_nur_rauschen_bleibt_erhalten(self) -> None:
        """Wenn die Filter alles verschlucken, darf kein leerer Schlüssel entstehen."""
        assert normalize("FC 05") != ""
