# Kicktipp Autopilot — Entwicklungsplan

> Stand: 09.08.2026 · Basis: `BL-Tipp.py` (434 Zeilen, Einzeldatei)
> Ziel: von „funktioniert bei mir am Spieltag" zu „läuft zuverlässig, mehrere Gruppen, mehrere Ligen, automatisch".

---

## TL;DR — empfohlene Reihenfolge

| Phase | Inhalt | Aufwand | Warum in dieser Reihenfolge |
|-------|--------|---------|------------------------------|
| **0** | Absicherung & Hygiene | ~30 Min | Verhindert, dass Zugangsdaten leaken, sobald das Repo wächst |
| **1** | Verlässlicher Kern (Browser raus, echtes Matching, Dry-Run) | 1–2 Tage | **Das Wichtigste.** Alles Weitere verstärkt sonst nur bestehende Fehler |
| **2** | Kicktipp ohne Browser + Modulstruktur | 1–2 Tage | Voraussetzung für Tests, Scheduling und Multi-Liga |
| **3** | Mehrere Gruppen & Ligen (Config + Alias-System) | 2–3 Tage | Dein Hauptwunsch — braucht aber Phase 1+2 als Fundament |
| **4** ✅ | Benutzeroberfläche | 1 Tag (CLI) | Erst sinnvoll, wenn es mehrere Gruppen/Ligen zum Auswählen gibt |
| **5** | Automatisches Timing | 1–2 Tage | Zuletzt: unbeaufsichtigt darf nur laufen, was nachweislich stimmt |

**Kernaussage:** Der größte Hebel ist nicht die UI, sondern **Selenium loswerden**. Das ist verifiziert möglich (siehe Befunde) und macht das Projekt schneller, testbar und überhaupt erst automatisierbar.

---

## Befunde aus der Ist-Analyse

Alles Folgende wurde am 09.08.2026 gegen die Live-Seiten geprüft, nicht vermutet:

### 1. predicd braucht keinen Browser ✅ *(verifiziert)*
Die Seite ist **vollständig server-seitig gerendert**. Ein einfacher `curl`-Abruf enthält alle Daten; alle 27 Spiele ließen sich rein mit `re`/String-Parsing korrekt dekodieren — identische Ergebnisse wie der Selenium-Lauf.

→ **Selenium ist für predicd komplett überflüssig.** Ersparnis: ~10 s Ladezeit pro Lauf, keine ChromeDriver-Versionsdrift, offline testbar.

### 2. Die Seite enthält 3 Spieltage, nicht 1 ⚠️ *(latenter Bug)*
Im statischen HTML stehen **27 Spiele** (Spieltag 1, 2 und 3). Der Selenium-Lauf hat nur 9 gesehen — vermutlich, weil zum Abfragezeitpunkt erst ein Teil gerendert war. Das ist **Zufall, kein Design**: Bei anderem Timing landen Tipps für Spieltag 2 und 3 in der Liste.

→ Vorhersagen müssen **explizit auf einen Spieltag eingegrenzt** werden.

### 3. Das Team-Mapping ist bereits jetzt unvollständig ⚠️
In den Live-Daten stehen **SC Paderborn, SV Elversberg, FC Schalke 04** — alle drei fehlen in `NAME_MAP` und werden stillschweigend unübersetzt durchgereicht. Im Testlauf sichtbar: diese drei erschienen unverändert, während andere korrekt übersetzt wurden.

→ Unbekannte Namen dürfen **nicht still durchrutschen**. Für CL/EM/WM (36+ europäische bzw. Nationalmannschaftsnamen) skaliert eine handgepflegte Liste ohnehin nicht.

### 4. Die Spieltag-Prüfung ist der eigentliche Abbruchgrund ⚠️
Der Testlauf scheiterte an `Spieltag stimmt nicht überein! Predicd: 1, Kicktipp: None` — der Selektor `div.prevnextTitle` lieferte nichts. Eine **Zahl** als einziges Sicherheitskriterium ist zu spröde: Ein geänderter Selektor legt den ganzen Bot lahm, obwohl die Spielpaarungen eindeutig zuzuordnen wären.

### 5. predicd bietet 65 Ligen — Multi-Liga ist realistisch ✅
Auszug der relevanten IDs (URL-Schema: `predicd.com/de/football/league/<ID>/`):

| ID | Liga | ID | Liga |
|----|------|----|------|
| 4331 | 1. Bundesliga | 4480 | **Champions League** |
| 4399 | 2. Bundesliga | 4481 | Europa League |
| 4639 | 3. Liga | 5071 | Europa Conference League |
| 4485 | DFB-Pokal | 4490 | Nations League |
| 4328 | Premier League | 4429 | **Weltmeisterschaft** |
| 4332 | Serie A | 4503 | Klub-WM |
| 4335 | Primera División | 5204 | Frauen-Bundesliga |

→ CL, WM und weitere Ligen sind vorhanden. Ob die **Tabellenstruktur** bei K.-o.-Formaten (CL-Playoffs, WM-Gruppenphase) identisch ist, muss pro Wettbewerb einmal geprüft werden — Annahme, kein verifizierter Fakt.

### 6. Weitere strukturelle Schwächen
- **Retry wiederholt alles:** Schlägt die Abgabe fehl, werden auch die Vorhersagen neu geladen (3× im Testlauf) — unnötige Last und Zeit.
- **Kein Dry-Run:** Das Skript schreibt sofort ins Live-Konto. Es gibt keine Möglichkeit, vorher zu sehen, was es tun würde.
- **`sys.exit()` mitten in der Logik** verhindert Wiederverwendung als Bibliothek/Modul.
- **Breite `except Exception`-Blöcke** verschlucken echte Fehler und melden sie als Zeilen-Warnung.
- **Kicktipp läuft absichtlich sichtbar** (`headless=False`) — blockiert unbeaufsichtigten Betrieb.
- **Selektoren über die Datei verstreut** — bei jeder Layout-Änderung Suchspiel.
- **Keine Tests, keine `requirements.txt`, keine `.gitignore`.**

---

## Zielbild

```
kicktipp_autopilot/
├── config.py          # config.toml + .env laden, validieren
├── models.py          # Match, Prediction, Fixture (Dataclasses)
├── sources/
│   ├── base.py        # Interface: get_predictions(league, matchday)
│   └── predicd.py     # HTTP + Parser (kein Browser)
├── targets/
│   ├── base.py        # Interface: login, read_fixtures, submit
│   └── kicktipp.py    # HTTP bevorzugt, Selenium als Fallback
├── matching/
│   ├── normalize.py   # "1. FC Köln" → "fc koeln"
│   ├── aliases/       # bundesliga.json, champions_league.json, …
│   └── matcher.py     # Fuzzy-Zuordnung + Konfliktbehandlung
├── cli.py             # Kommandozeile & interaktive Auswahl
└── scheduler.py       # Deadline-Ermittlung, systemd-Anbindung

tests/
└── fixtures/          # gespeicherte HTML-Seiten für Offline-Tests
```

**Leitprinzipien**
1. **Nie stillschweigend raten.** Unklare Zuordnung → abbrechen oder nachfragen, nie „irgendwas eintragen".
2. **Lesen ist harmlos, Schreiben braucht Bestätigung.** Dry-Run ist der Normalfall beim Entwickeln.
3. **Kicktipp ist die Wahrheit.** Welche Spiele anstehen und bis wann getippt werden kann, sagt Kicktipp — nicht predicd, nicht ein externer Spielplan.
4. **Alles offline testbar.** Gespeicherte HTML-Fixtures statt Live-Abrufe in Tests.

---

## Phase 0 — Absicherung & Hygiene

**Warum zuerst:** `.env` enthält jetzt echte Zugangsdaten und ist durch nichts geschützt. Sobald daraus ein Git-Repo wird, ist das Passwort in der Historie.

- [ ] `.gitignore` anlegen: `.env`, `.venv/`, `__pycache__/`, `*.log`, `state/`
- [ ] `requirements.txt` mit gepinnten Versionen (`selenium==4.46.0`, `python-dotenv==1.2.2`)
- [ ] `example.env` bereinigen (Platzhalter `sfsdfvsd` raus)
- [ ] Kicktipp-Passwort rotieren (wurde im Klartext geteilt)
- [ ] README: Hinweis auf `python3-pip`/`python3-venv` unter Debian/Ubuntu/Pop!_OS; ChromeDriver-Abschnitt streichen (Selenium Manager erledigt das seit 4.6 selbst)

**Fertig wenn:** `git init && git add -A && git status` zeigt keine `.env`.

---

## Phase 1 — Verlässlicher Kern ⭐ *wichtigste Phase*

**Warum:** Ein Bot, der unbeaufsichtigt in ein Live-Konto schreibt, muss vorher nachweislich das Richtige tun. Jede Zeile UI und Scheduling auf einem wackligen Kern vervielfacht nur den Schaden.

### 1.1 predicd ohne Browser
- [ ] Abruf per `httpx`, Parsing mit `selectolax` oder `BeautifulSoup` (statt Regex — wartbarer)
- [ ] `decode_score_part` übernehmen (funktioniert), aber mit Fehlerbehandlung + Testfällen
- [ ] **Spieltag-Zuordnung je Zeile** ermitteln, nicht global — die Seite enthält mehrere Spieltage
- [ ] Selenium-Import aus diesem Pfad vollständig entfernen

### 1.2 Zuordnung über Paarungen statt Spieltagnummer
- [ ] Kicktipp-Zeilen liefern Heim-/Auswärtsteam → Zuordnung über das **Team-Paar**
- [ ] Spieltagnummer nur noch als *Plausibilitätscheck* mit Warnung, nicht als Abbruchkriterium
- [ ] Abbruch nur, wenn Paarungen tatsächlich nicht zusammenpassen — mit klarer Diagnose („3 von 9 Spielen nicht zuordenbar: …")

### 1.3 Dry-Run
- [ ] `--dry-run` (Standard beim Entwickeln): zeigt Tabelle „Spiel → Tipp → Kicktipp-Feld", schreibt nichts
- [ ] `--submit` als bewusster Schalter fürs echte Absenden
- [ ] Ausgabe als Tabelle via `rich`

### 1.4 Robustes Team-Mapping
- [ ] Normalisierung: Kleinschreibung, Umlaute (`ö→oe`), Präfixe/Suffixe (`1.`, `FC`, `SV`, `VfL`, `04`) entfernen
- [ ] Alias-Datei pro Liga als JSON (aus `NAME_MAP` migrieren, **fehlende Teams ergänzen**)
- [ ] Fuzzy-Fallback (`rapidfuzz`) mit Schwellwert; darunter → Fehler statt Rateversuch
- [ ] `--learn`: fragt bei unbekannten Namen interaktiv nach und schreibt den Alias zurück

### 1.5 Fehlerbehandlung & Struktur
- [ ] Retry **nur** um die Abgabe, nicht um den kompletten Ablauf
- [ ] Eigene Exceptions (`PredictionError`, `SubmissionError`, `MappingError`) statt pauschalem `except Exception`
- [ ] `sys.exit()` nur in `main()`; Kernfunktionen geben Werte zurück oder werfen
- [ ] Alle CSS-Selektoren in ein `selectors.py`

**Fertig wenn:** `--dry-run` zeigt für Spieltag N genau die 9 richtigen Paarungen mit korrekten Tipps, ohne Browser, in unter 3 Sekunden — und meldet unbekannte Teams namentlich, statt sie durchzureichen.

---

## Phase 2 — Kicktipp ohne Browser + Module

- [ ] **Untersuchen:** Kicktipp-Login und Tippabgabe als reine Form-POSTs mit `httpx.Client` (Session-Cookies) — *ungeprüfte Annahme, muss verifiziert werden*
- [ ] Bei Erfolg: Selenium hinter dem `targets/base.py`-Interface als Fallback behalten, nicht löschen
- [ ] Cookie-Banner-Problem entfällt bei HTTP-Weg vollständig
- [ ] Session-Cookies zwischen Läufen speichern → kein Login bei jedem Durchlauf
- [ ] Modulstruktur wie im Zielbild aufziehen
- [ ] `pyproject.toml` + Entry Point → `kicktipp-autopilot` als Befehl
- [ ] **Tests:** HTML-Fixtures beider Seiten speichern, Parser offline testen (`pytest`)

**Fertig wenn:** Kompletter Durchlauf ohne Chrome; `pytest` läuft ohne Netzwerkzugriff durch.

> **Risiko:** Kicktipp könnte CSRF-Token, JS-Formulare oder Bot-Schutz einsetzen. Falls ja: Selenium bleibt für die Abgabe, headless. Das kostet Phase 5 nichts — headless läuft auch im Timer.

---

## Phase 3 — Mehrere Ligen je Gruppe ✅ *(umgesetzt am 10.08.2026)*

### Befunde aus der Ist-Analyse an einer echten Bundesliga+CL-Gruppe

1. **Kicktipp zeigt je Spieltag genau einen Wettbewerb**, nie einen gemischten
   Satz. Die Spielzeilen verraten aber nicht, welchen: Die Tabelle hat nur
   `tipptermin | heim | gast | punkteregel | tipp | quote`, keine
   Wettbewerbsspalte, kein `data`-Attribut.
2. **Der Spieltagtitel trägt ein Kürzel**: `„8. Spieltag - CL"` gegenüber
   `„8. Spieltag"`. Frei vom Gruppenadmin vergeben, also ein Anhaltspunkt für
   die Ausgabe — keine verlässliche Ligazuordnung.
3. **`spieltagIndex` ≠ angezeigte Spieltagnummer.** Index 25 trägt den Titel
   „8. Spieltag - CL". `load_page` verglich den Wunschwert gegen die *Nummer*
   und schickte ihn als *Index* — in gemischten Gruppen landete man damit auf
   der falschen Seite. Behoben: verglichen wird gegen das Formularfeld.
4. **predicd baut K.-o.-Wettbewerbe anders auf** als Ligen: Die CL-Seite liefert
   **zwei Folien mit identischem Inhalt** (beide `active`), 72 Spiele der
   gesamten Qualifikationsphase, Überschrift „Qualifikation" statt einer Nummer.
   Die Bundesliga-Seite hat unverändert drei verschiedene Folien.
5. **Latenter Bug im Matcher:** Der Paarungs-Index war ein Dict, zwei
   Vorhersagen mit gleicher Paarung überschrieben sich stillschweigend. Bei
   einer Liga folgenlos, bei einem gemischten Topf ein falscher Tipp.

### Umgesetzt
- [x] `config.toml` mit `[[gruppen]]` (Name + Ligenliste), `tomllib`, fehlende
      Datei ist kein Fehler; Vorrang CLI → config.toml → Bundesliga
- [x] `LeagueRef` (Slug + ID) — `resolve_league` warf den Namen weg, an dem die
      Alias-Datei hängt
- [x] `--league` mehrfach und kommasepariert; `--list-matchdays`;
      `--list-groups` zeigt die konfigurierten Ligen
- [x] Vorhersagen aller Ligen in einem Topf, Zuordnung über die Paarung — welcher
      Wettbewerb läuft, ergibt sich aus den Treffern statt aus einer Beschriftung
- [x] Fenster über *alle* Folien statt nur der aktiven, mit Deduplizierung
      (sonst wäre wegen Befund 4 jede CL-Paarung mehrdeutig)
- [x] Index auf Listen umgestellt, Mehrdeutigkeit über das Anstoßdatum
      aufgelöst, sonst gemeldet statt geraten (Befund 5)
- [x] Anstoßzeit wird gelesen und über Zeilenblöcke mitgeführt — zugleich die
      Vorarbeit für Phase 5.1
- [x] **Absende-Sperre:** Bleibt ein Spiel ohne eindeutigen Tipp, wird nichts
      geschrieben (`--allow-partial` hebt es auf). Der Dry-Run bricht nie ab.
- [x] `sk` als Vereinskürzel in die Normalisierung (belegt an
      „SK Sturm Graz"/„Sturm Graz"), `champions-league.json` angelegt
- [x] **Noch nicht ausgeloste Runden** werden als solche erkannt (Kicktipp legt
      den kompletten Spielplan vorab an und trägt überall „unbekannt" ein) und
      klar gemeldet statt der Konfiguration angelastet. Teilweise ausgeloste
      Runden blockieren die übrigen Tipps nicht.
- [x] 168 Offline-Tests, davon 36 neue gegen echte CL-Fixtures beider Seiten

### Offen
- [ ] **Alias-Datei CL vervollständigen.** Von 36 Teams der Ligaphase waren 11
      prüfbar, alle löst die Normalisierung ohne Alias. Die übrigen 25 sind erst
      prüfbar, wenn predicd die Ligaphase statt der Qualifikation zeigt.
- [ ] **Live-Abgabe auf einem CL-Spieltag.** Derzeit unmöglich: Die einzige
      tippbare Gruppe des Kontos ist reine Bundesliga, die gemischten Gruppen
      sind abgelaufene Saisons. Nachzuholen, sobald eine gemischte Gruppe für
      2026/27 offen ist.
- [ ] Pokal-/Turnierformate (DFB-Pokal, WM) je einmal verifizieren, bevor sie
      freigeschaltet werden. Der Pokal ist der Fall, in dem sich Paarungen mit
      der Bundesliga überschneiden können — die Mehrdeutigkeitserkennung ist
      dafür die Voraussetzung, aber nicht die ganze Lösung.
- [x] Mehrere Gruppen in einem Lauf — umgesetzt in Phase 4 als `--all-groups`.

---

## Phase 4 — Benutzeroberfläche ✅ *(umgesetzt am 10.08.2026)*

### Befunde aus dem ersten Sammellauf über alle vier Gruppen

1. **Der Rückgabecode war als Warnsignal wertlos.** Eine CL-Gruppe vor der
   Auslosung und zwei Gruppen abgelaufener Saisons ließen den ersten Lauf mit
   „1 von 4 Gruppen nicht abgearbeitet" enden — obwohl nichts kaputt war.
   Genau das wollte Phase 5.3 vermeiden: Wer täglich Fehlalarm bekommt, sieht
   den echten Fehler nicht mehr.
2. **„Kein offener Spieltag" lief in die Wiederholschleife.** `load_page` warf
   dafür einen `SubmissionError`; über vier Gruppen wären das drei Versuche à
   5 Sekunden pro pausierender Gruppe gewesen.
3. **Dieselbe Liga wurde je Gruppe neu geholt.** Drei der vier Gruppen tippen
   Bundesliga — ohne Cache dreimal dieselbe predicd-Seite.

### Umgesetzt
- [x] `--all-groups` arbeitet alle `[[gruppen]]` der config.toml ab: **eine**
      Anmeldung, ein predicd-Abruf je Wettbewerb, eine Zusammenfassung am Ende
- [x] `runner.py` herausgelöst — `cli.py` enthält nur noch Argumente und
      Verteilung; der Einzelaufruf ist derselbe Codepfad mit einer Gruppe
- [x] **Fehler bleiben lokal:** Was in einer Gruppe schiefgeht, wird dort
      gemeldet und in der Zusammenfassung wiederholt; die übrigen Gruppen
      laufen weiter. Rückgabecode 1 nur bei echten Fehlern
- [x] `NotDrawnError` als eigene Klasse — „noch nicht ausgelost" ist ein
      Zustand der Welt, kein Fehler (Befund 1)
- [x] Wiederholt wird nur bei `SubmissionError`, und nur mit vorheriger neuer
      Anmeldung; eine `MappingError` fällt beim zweiten Versuch genauso aus
- [x] Cache in `PredicdSource` für Seite *und* ausgewertetes Fenster (Befund 3)
- [x] Widersprüchliche Optionen (`--all-groups` mit `--matchday`, `--group`,
      `--league`) brechen vor dem ersten Netzzugriff mit Handlungsanweisung ab
- [x] `-i`: Gruppenauswahl per Pfeiltasten (`questionary`), Vorschau, Rückfrage
      mit Vorgabe *Nein*. Vorschau und Abgabe teilen sich Sitzung und
      Vorhersagen — abgesendet wird genau das Angezeigte
- [x] Das Menü verweigert sich ohne Terminal und verweist auf `--all-groups`
      (sonst bliebe ein Timer aus Phase 5 stumm an der Rückfrage hängen)
- [x] `--list-matchdays` versteht `--all-groups`
- [x] 198 Offline-Tests, davon 30 neue

### Bewusst anders als geplant
- **Ohne Argumente bleibt es beim Dry-Run** der `.env`-Gruppe; das Menü liegt
  auf `-i`. Ein Verhaltenswechsel je nach Umgebung hätte jedes Skript und
  jeden Timer aus Phase 5 zur Wette gemacht.
- **`--all-groups` statt `--all`.** `--all` bleibt für Phase 5 frei: alle
  Gruppen × alle offenen Spieltage, das braucht erst die Zustandsdatei.

### Offen
- [ ] Live-Abgabe über `--all-groups --submit`, sobald in mehr als einer Gruppe
      gleichzeitig ein Spieltag offen ist. Bisher geprüft: Vorschau über alle
      vier Gruppen, Abgabe in der einen Gruppe mit offenem Spieltag.
- [ ] 4.2, weiterhin optional: **TUI** (`textual`) als Dashboard mit Gruppen,
      Deadlines und letztem Lauf; **lokale Web-UI** (FastAPI + htmx) nur, wenn
      die Bedienung vom Handy aus dazukommen soll.

---

## Phase 5 — Automatisches Timing

**Warum zuletzt:** Unbeaufsichtigter Betrieb setzt voraus, dass Phase 1 nachweislich stimmt und Phase 2 ohne sichtbaren Browser läuft.

### 5.1 Deadline aus Kicktipp lesen
Kein externer Spielplan nötig — **Kicktipp kennt den Abgabeschluss selbst** und ist damit immer korrekt (auch bei Spielverlegungen).

- [ ] Deadline je Spiel/Spieltag aus der Tippabgabe-Seite parsen
- [ ] Regel: „X Stunden vor dem frühesten Anpfiff tippen" (konfigurierbar, Standard 12 h)
- [ ] Zusätzlich ein später Sicherheitslauf (z. B. 1 h vorher) für den Fall, dass predicd noch keine Daten hatte

### 5.2 Ausführung
- [ ] **systemd-User-Timer** (passend für Pop!_OS; überlebt Neustarts, `Persistent=true` holt verpasste Läufe nach) — cron ist die schlechtere Wahl, weil verpasste Läufe verloren gehen
- [ ] Täglicher Check-Lauf: „steht was an?" → wenn nein, sofort beenden
- [ ] Zustandsdatei: welcher Spieltag je Gruppe schon getippt wurde → **Idempotenz**, kein Doppel-Absenden
- [ ] Log-Datei mit Rotation

### 5.3 Rückmeldung
- [ ] Desktop-Benachrichtigung (`notify-send`) bei Erfolg/Fehler
- [ ] Optional Push aufs Handy (ntfy.sh o. ä.)
- [ ] **Wichtig:** Bei Fehlern laut sein. Ein still gescheiterter Bot ist schlimmer als gar keiner — man merkt es erst, wenn die Punkte fehlen.

**Fertig wenn:** Eine Woche lang ohne manuellen Eingriff korrekt getippt, mit Benachrichtigung nach jedem Lauf.

---

## Offene Entscheidungen

1. **Vorhersagequelle:** Bleibt predicd einzige Quelle, oder soll die Architektur mehrere Quellen zulassen (z. B. Vergleich/Fallback)? Das `sources/`-Interface hält beides offen — kostet jetzt nichts, spart später viel.
2. **Bei fehlender Vorhersage:** Spiel überspringen, Standardtipp (z. B. 1:1), oder ganzen Lauf abbrechen?
3. **Bereits abgegebene Tipps:** überschreiben oder unangetastet lassen? (Relevant, wenn du manuell nachbesserst.)
4. **Passwortspeicherung:** `.env` im Klartext beibehalten oder System-Keyring (`keyring`-Paket) nutzen? Bei unbeaufsichtigtem Betrieb ist Keyring unter Umständen unpraktisch.
5. **Veröffentlichung:** Soll das Repo öffentlich werden? Falls ja, Phase 0 zwingend vor dem ersten Commit.

---

## Risiken

| Risiko | Auswirkung | Gegenmaßnahme |
|--------|-----------|----------------|
| predicd ändert Layout | Bot fällt komplett aus | Selektoren zentral, Tests mit Fixtures, aussagekräftige Fehler statt stiller Falschdaten |
| predicd verschleiert Scores stärker | Dekodierung bricht | Dekodierung isolieren und testen; `decode_score_part` ist die verwundbarste Stelle |
| Kicktipp führt Bot-Schutz ein | Abgabe blockiert | Selenium-Fallback behalten, moderate Frequenz, keine parallelen Läufe |
| Falsche Team-Zuordnung | **Falsche Tipps im Live-Konto** | Kein Fuzzy-Match unter Schwellwert; im Zweifel abbrechen |
| Unbeaufsichtigter Fehlschlag | Spieltag verpasst | Benachrichtigungen + zweiter Sicherheitslauf vor Deadline |

---

## Nächster konkreter Schritt

Phasen 0–4 sind umgesetzt. Als Nächstes **Phase 5.1** — die Deadline je
Spieltag aus der Tippabgabe-Seite lesen. Die Vorarbeit steht: Die Anstoßzeit
wird bereits geparst und über die Zeilenblöcke mitgeführt, und `--all-groups`
liefert mit `GroupOutcome` genau die Angaben, die die Zustandsdatei für die
Idempotenz braucht (welche Gruppe, welcher Spieltag, wie viele Tipps).
