# AHC Preheat

Vorheizen für [Advanced Heating Control](https://community.home-assistant.io/t/advanced-heating-control/469873) (AHC):
Die Integration liest Zeitpläne, Komforttemperatur und Thermostate direkt aus deiner AHC-Automation,
lernt pro Raum, wie schnell er warm wird, und meldet AHC rechtzeitig „jetzt vorheizen“ –
damit es zum Beginn der Komfortzeit schon warm ist.

## Wie es funktioniert

- **Nächster Komfortbeginn** kommt aus dem `next_event` der AHC-Zeitpläne – ab dem ersten Tag, ohne Lernphase.
- **Zieltemperatur** ist die AHC-Komforttemperatur (Regler oder fester Wert).
- **Raumtemperatur** kommt aus dem AHC-Raumsensor, sonst aus den Thermostaten.
- **Vorlaufzeit** = Totzeit + (Ziel − Ist) / Aufheizrate + Puffer, gedeckelt auf die maximale Vorheizzeit.
- **Lernen:** Jedes Mal, wenn der Sollwert am Thermostat deutlich steigt, misst die Integration, nach wie vielen
  Minuten die Temperatur zu steigen beginnt (Totzeit) und wie viele °C pro Stunde der Raum schafft.
  Mit Außentemperatur lernt sie außerdem, dass es bei Kälte länger dauert.
  Bis zur ersten Messung gilt 1,5 °C/h und 10 min Totzeit.

## Installation

1. HACS → ⋮ → Benutzerdefinierte Repositories → URL dieses Repos, Typ **Integration**.
2. „AHC Preheat“ herunterladen, Home Assistant neu starten.
3. Einstellungen → Geräte & Dienste → Integration hinzufügen → **AHC Preheat**, pro Raum einmal:
   AHC-Automation wählen, optional Außentemperatur (Sensor oder `weather.*`).
4. In der AHC-Automation des Raums unter **Presence Detection → Presence Sensor** den neuen Sensor
   `binary_sensor.vorheizen_<raum>_vorheizen` eintragen und **Presence Reaction On/Off Time** auf 0 setzen.
   AHC heizt dann auf Komfort, wenn der Zeitplan an ist **oder** vorgeheizt wird.

## Entitäten pro Raum

| Entität | Bedeutung |
|---|---|
| Vorheizen | an = jetzt vorheizen (für AHC) |
| Vorheiz-Start | wann das nächste Vorheizen beginnt |
| Vorlaufzeit | berechnete Minuten vor Komfortbeginn |
| Aufheizrate | gelernte °C pro Stunde (Attribut: Totzeit) |
| Messungen | Anzahl gelernter Aufheizvorgänge (max. 30) |
| Gelerntes zurücksetzen | Lernstand des Raums löschen |

## Grenzen

- Nutzt AHC einen *Schedule Selector* mit mehreren Zeitplänen, zählt der früheste Start aller Zeitpläne.
- Liest die Blueprint-Eingaben über ein internes HA-Attribut der Automation; ändert HA das, muss die Integration angepasst werden.

## Tests

```bash
python3 -m unittest discover -s tests -p "test_model.py"   # ohne HA
pytest tests/test_integration.py                             # braucht pytest-homeassistant-custom-component
```
