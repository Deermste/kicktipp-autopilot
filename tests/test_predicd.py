"""Tests des predicd-Parsers — ohne Netzwerkzugriff.

Grundlage ist ein gespeicherter Abzug der Ligaseite 4331 vom 09.08.2026.
Wenn predicd das Layout ändert, schlagen diese Tests fehl, ohne dass ein
falscher Tipp im Live-Konto landet.
"""

from collections import Counter
from pathlib import Path

import pytest

from kicktipp_autopilot.config import resolve_league_ref
from kicktipp_autopilot.errors import PredictionError
from kicktipp_autopilot.sources.predicd import (
    PredicdSource,
    decode_score,
    parse,
    parse_matchday_label,
)

FIXTURE = Path(__file__).parent / "fixtures" / "predicd_4331.html"
BUNDESLIGA = resolve_league_ref("bundesliga")


@pytest.fixture(scope="module")
def html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def predictions(html: str):
    return parse(html)


class TestDecodeScore:
    """Die Kodierung ist linear: 1760 -> 0, +256 je Tor."""

    @pytest.mark.parametrize(
        "meta_info, expected",
        [
            ("//4yADAAMgA2ADAAOAAwADkABuA=", 0),
            ("//4yADAAMgA2ADAAOAAwADkAB+A=", 1),
            ("//4yADAAMgA2ADAAOAAwADkACeA=", 3),
        ],
    )
    def test_bekannte_werte(self, meta_info: str, expected: int) -> None:
        assert decode_score(meta_info) == expected

    def test_unsinn_wirft_klaren_fehler(self) -> None:
        with pytest.raises(PredictionError, match="Format geändert"):
            decode_score("nicht-base64!!")


class TestMatchdayLabel:
    @pytest.mark.parametrize(
        "text, expected",
        [("1. Spieltag", 1), ("17. Spieltag", 17), ("Achtelfinale", None), ("", None)],
    )
    def test_parsen(self, text: str, expected: int | None) -> None:
        assert parse_matchday_label(text) == expected


class TestParse:
    def test_drei_spieltage_mit_je_neun_spielen(self, predictions) -> None:
        """Die Seite liefert ein Karussell mit drei Spieltagen.

        Genau diese Eigenschaft hat das Altskript übersehen: Ohne Scoping
        landen 27 Spiele aus drei Spieltagen in einem Topf.
        """
        verteilung = Counter(p.matchday for p in predictions)
        assert len(predictions) == 27
        assert verteilung == {1: 9, 2: 9, 3: 9}

    def test_aktiver_spieltag_ist_der_erste(self, predictions) -> None:
        assert min(p.matchday for p in predictions) == 1

    def test_bekannte_paarung_mit_korrektem_ergebnis(self, predictions) -> None:
        spiel = next(
            p for p in predictions if p.home_team == "FC Bayern München" and p.matchday == 1
        )
        assert (spiel.away_team, spiel.home_score, spiel.away_score) == (
            "VfB Stuttgart",
            3,
            1,
        )

    def test_anstosszeit_wird_gelesen(self, predictions) -> None:
        spiel = next(p for p in predictions if p.home_team == "FC Bayern München")
        assert spiel.kickoff == "28.08. 20:30"

    def test_scores_sind_ints_und_plausibel(self, predictions) -> None:
        for p in predictions:
            assert isinstance(p.home_score, int)
            assert 0 <= p.home_score <= 9, p
            assert 0 <= p.away_score <= 9, p

    def test_keine_leeren_teamnamen(self, predictions) -> None:
        assert all(p.home_team and p.away_team for p in predictions)

    def test_layoutwechsel_wirft_klaren_fehler(self) -> None:
        with pytest.raises(PredictionError, match="Spieltag-Folien"):
            parse("<html><body>komplett anderes Layout</body></html>")


class TestCache:
    """Dieselbe Liga in mehreren Gruppen kostet nur einen Abruf.

    Ohne den Cache holte ein Lauf über vier Gruppen die Bundesliga-Seite
    dreimal — dieselbe Antwort, dreimal Last auf beiden Seiten.
    """

    def test_zweiter_abruf_geht_nicht_ins_netz(self, monkeypatch, html: str) -> None:
        import kicktipp_autopilot.sources.predicd as modul

        zaehler: list[int] = []

        class _Antwort:
            text = html

            def raise_for_status(self) -> None:
                pass

        def _get(url, **kwargs):
            zaehler.append(1)
            return _Antwort()

        monkeypatch.setattr(modul.httpx, "get", _get)

        quelle = PredicdSource()
        erst = quelle.get_window(BUNDESLIGA)
        zweit = quelle.get_window(BUNDESLIGA)

        assert zaehler == [1], "Die Ligaseite wurde mehrfach geholt."
        assert erst == zweit

    def test_cache_gibt_keine_geteilte_liste_heraus(self, monkeypatch, html: str) -> None:
        """Wer die Liste des einen Laufs verändert, darf den nächsten nicht treffen."""
        import kicktipp_autopilot.sources.predicd as modul

        class _Antwort:
            text = html

            def raise_for_status(self) -> None:
                pass

        monkeypatch.setattr(modul.httpx, "get", lambda url, **kwargs: _Antwort())

        quelle = PredicdSource()
        erst = quelle.get_window(BUNDESLIGA)
        erst.clear()

        assert quelle.get_window(BUNDESLIGA), "Der Cache wurde von außen geleert."
