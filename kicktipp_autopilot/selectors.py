"""Alle CSS-Selektoren an einer Stelle.

Beide Seiten sind fremde Websites, deren Layout sich jederzeit ändern kann.
Wenn der Bot plötzlich nichts mehr findet, ist fast immer eine Konstante aus
dieser Datei betroffen — und nur diese Datei muss angefasst werden.

Bitte bei jeder Prüfung/Anpassung das Datum in der jeweiligen Sektion mitpflegen.
"""


class Predicd:
    """Selektoren für predicd.com.

    Zuletzt gegen die Live-Seite verifiziert: 09.08.2026 (Liga 4331).

    Aufbau der Fixtures-Sektion:
        div.carousel-inner
          └── span#matchDayCarouselItem    (3 Stück, id mehrfach vergeben)
                └── div.carousel-item      (trägt bei der aktiven Folie "active")
                      └── tr.tr-body       (1 Zeile je Spiel, je 9 Stück)

    Genau eine Folie trägt zusätzlich die Klasse "active"; sie entspricht dem
    Spieltag, der in MATCHDAY_LABEL steht. Die folgenden Folien sind die
    Spieltage danach (+1, +2).
    """

    MATCHDAY_LABEL = "#matchdayNumber"  # Text: "1. Spieltag"
    CAROUSEL_ITEMS = "div.carousel-inner div.carousel-item"
    ACTIVE_CLASS = "active"
    MATCH_ROW = "tr.tr-body"

    # Innerhalb einer Zeile:
    TEAM_NAME = "div#teamname"  # 2 Treffer: [Heim, Gast]
    # Die Scores stehen base64-kodiert im Attribut "meta-info".
    SCORE_META = "span[id^='predResult_'] span.of-meta"
    SCORE_ATTR = "meta-info"


class Kicktipp:
    """Selektoren für kicktipp.de.

    Zuletzt gegen die Live-Seite verifiziert: 09.08.2026 (Tippabgabe-Seite
    einer Gruppe mit offenem Spieltag).

    Aufbau einer Spielzeile (tr.datarow), 6 Zellen:
        [0] col0  Anstoß      "28.08.26 20:30"
        [1] col1  Heimteam    "FC Bayern München"
        [2] col2  Gastteam    "VfB Stuttgart"
        [3] col3  Tendenz     "3 - 9 - 9"
        [4] col4  Tippfelder  (2 Eingabefelder)
        [5] col5  Quoten

    Die erste tr.datarow ist eine Kopfzeile ohne Zellen und wird dadurch
    automatisch übersprungen, dass keine Teamnamen gelesen werden können.
    """

    EMAIL_INPUT = 'input#kennung[type="email"]'
    PASSWORD_INPUT = "#passwort"
    SUBMIT_BUTTON = 'button[name="submitbutton"][type="submit"]'

    MATCH_ROW = "tr.datarow"
    HOME_TEAM_CELL = "td.nw.cell.col1"
    AWAY_TEAM_CELL = "td.nw.cell.col2"
    TIP_INPUTS = "input[id^='spieltippForms'][type='text']"

    # Enthält NICHT immer eine Zahl: bei K.-o.-Runden steht dort "Finale",
    # "Halbfinale" usw. Genau daran ist das Altskript gescheitert — deshalb ist
    # die Spieltagnummer nur noch ein Hinweis, kein Abbruchkriterium.
    #
    # In Gruppen mit mehreren Wettbewerben trägt der Titel zusätzlich ein vom
    # Gruppenadmin vergebenes Kürzel: "8. Spieltag - CL" gegenüber
    # "8. Spieltag" (verifiziert am 10.08.2026 an einer Bundesliga+CL-Gruppe).
    MATCHDAY_TITLE = "div.prevnextTitle"

    # Die Spieltagsauswahl im Aufklappmenü. Jeder Eintrag verlinkt einen
    # `spieltagIndex`; die Nummerierung ist die der *Gruppe* und stimmt in
    # gemischten Gruppen nicht mit der angezeigten Spieltagnummer überein
    # (Index 25 = "8. Spieltag - CL"). Der aktive Eintrag trägt "active-true".
    MATCHDAY_OPTIONS = "div.dropdowncontent div.menu div.level0"
    MATCHDAY_OPTION_ACTIVE = "active-true"
    MATCHDAY_OPTION_BONUS = "bonusoption"

    # Terminspalte einer Spielzeile. Nur die erste Zeile eines Anstoßblocks
    # trägt einen Wert, die Folgezeilen sind leer.
    KICKOFF_CELL = "td.kicktipp-time"

    COOKIE_BUTTON = (
        ".message-component.message-button.no-children.focusable"
        ".action_button.sp_choice_type_11"
    )
    COOKIE_IFRAME_ID_PREFIX = "sp_message_iframe_"
