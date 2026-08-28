# In-Game Verifikationsleitfaden: Laufzeitbefunde (B-2, B-3, H-3)

Dieses Dokument dient als kompakte Checkliste für den manuellen Live-Test gegen den **Entropia Flyff Client (`neuz.exe`)**, um die statisch abgeleiteten Laufzeit-Korrekturen im echten Spielbetrieb zu validieren.

---

## 📋 Übersicht der Testfälle

| ID | Bereich | Kernfrage | Erwartung |
|---|---|---|---|
| **B-2** | **Spielertod & Vitals** | Spamt der Bot bei 0 % HP Heiltränke? | Kein Trank-Spam bei Tod; sauberer Übergang in `DEAD`, alle Tasten losgelassen. |
| **B-3** | **Not-Aus vs. ESC** | Bricht `ESC` ab? Reagiert `F12` sofort? | `ESC` ignoriert (kein Abbruch); kurzer `F12`-Druck stoppt sofort zuverlässig. |
| **H-3** | **Quest-NPC Interaktion** | Findet & klickt der Bot NPCs ohne YOLO? | 3D-World-to-Screen-Projektion klickt den NPC exakt an; Dialog öffnet sich. |

---

## 🧪 Testdurchführung

### 1. Befund B-2: Spielertod & Vitals-Trigger (Zero-HP Dwell / Potion Loop)

* **Ziel:** Sicherstellen, dass bei HP = 0 % kein Dauer-Feuern der Heiltrank-Taste (F1) stattfindet und der Bot den Tod korrekt abfängt.
* **Vorbereitung:**
  1. Bot starten mit aktivierter Vitals-Regel (z. B. HP-Trigger auf 70 % mit Taste `F1`).
  2. Zu einer Monstergruppe gehen, die den Charakter besiegen kann.
* **Schritte:**
  1. Farming starten und den Charakter sterben lassen (HP fällt auf 0 %).
  2. Tasten-Output und Dashboard beobachten.
* **Soll-Verhalten (Erfolgreich wenn):**
  - [ ] **Kein Trank-Spam:** `F1` wird bei 0 % HP **nicht** mehr gedrückt (`MINIMUM_TRIGGERABLE_VITAL_PERCENTAGE = 0.1` greift).
  - [ ] **Bewegungsstopp:** Alle Bewegungstasten (WASD) werden sofort gelöst.
  - [ ] **Status:** Bot wechselt im Dashboard in den Zustand `DEAD` / `PAUSED` (bzw. führt konfigurierten Respawn-Klick aus).

---

### 2. Befund B-3: Not-Aus-Zuverlässigkeit & ESC-Entkopplung

* **Ziel:** Prüfen, dass `ESC` den Bot nicht versehentlich stoppt und `F12` (Not-Aus) auch bei extrem kurzem Tastendruck sofort greift.
* **Vorbereitung:**
  1. Bot im normalen Farming- oder Navigationsmodus starten.
* **Schritte & Soll-Verhalten:**
  - **Teil A: ESC-Prüfung**
    1. Während der Bot läuft, im Spielfenster mehrfach `ESC` drücken (z. B. um Zielfenster oder Spielmenüs zu schließen).
    2. [ ] **Ergebnis:** Der Bot läuft unterbrechungsfrei weiter und bricht **nicht** ab.
  - **Teil B: F12 Not-Aus (Latching)**
    1. Während der Bot läuft (ideal bei aktiver Bewegung/WASD), ganz kurz `F12` antippen.
    2. [ ] **Ergebnis:** Der Bot stoppt unverzüglich, alle gehaltenen Tasten werden sofort freigegeben, Dashboard meldet `EMERGENCY_STOPPED`.

---

### 3. Befund H-3: Quest-NPC 3D-World-to-Screen Projektion

* **Ziel:** Prüfen, dass Quest-NPCs über die 3D-Kameramatrix projiziert und angeklickt werden (anstelle einer Suche im YOLO-Monster-Detektor).
* **Vorbereitung:**
  1. Eine Quest mit einem bekannten NPC in der aktuellen Welt/Zone auswählen.
* **Schritte:**
  1. Bot mit Quest-Ziel starten.
  2. Anfahrt zum NPC und Interaktion beobachten.
* **Soll-Verhalten (Erfolgreich wenn):**
  - [ ] **Zielanfahrt:** Bot navigiert via GPS/NavMesh bis in Interaktionsreichweite des NPCs.
  - [ ] **Klick-Genauigkeit:** Sobald in Reichweite, klickt die Maus präzise auf die berechnete Bildschirmposition des NPCs (berechnet aus 3D-Koordinate + Kameramatrix).
  - [ ] **Dialog:** Der Quest-Dialog öffnet sich und der Bot verarbeitet die Dialogoptionen via OCR.
  - [ ] **Keine Fehlauslösung:** Steht der NPC hinter der Kamera oder außerhalb des Sichtfelds, wird kein fehlerhafter Klick ins Leere ausgelöst.

---

## 📝 Testergebnis-Protokoll

| Test | Status (Pass / Fail) | Auffälligkeiten / Bemerkungen |
|---|---|---|
| **B-2** (Zero-HP / Tod) | `[ ]` | |
| **B-3** (ESC / F12 Stop) | `[ ]` | |
| **H-3** (NPC Projektion) | `[ ]` | |
