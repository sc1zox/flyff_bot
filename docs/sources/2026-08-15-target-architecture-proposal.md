# Target architecture proposal

- Origin: user request in the Codex session
- Captured: 2026-08-15
- Language: German
- Mutability: immutable

> leg mal ein architecture bootstrap user story an Kurz zusammengefasst wäre unser aktueller Ansatz:
>
> Python als Hauptsprache, weil YOLO/OpenCV/OCR dort am einfachsten sind.
> PySide6 für die Windows-UI, erstmal kein Angular/Node, um Komplexität und Overhead klein zu halten.
> YOLO für dynamische Objekte wie Mobs; Template Matching für feste UI-Elemente wie Icons/Fensterbereiche.
> OCR nur gezielt auf kleine ROIs, nicht auf den ganzen Bildschirm. ROIs relativ zum Spielfenster oder relativ zu erkannten UI-Ankern.
> Zentraler World State / Snapshot, der den aktuell angenommenen Spielzustand enthält: Items, Position, sichtbare Mobs, aktuelles Ziel, Fortschritt etc.
> Darüber ein Supervisor/Reconciliation Loop, der Desired State gegen Observed State vergleicht und Fehler bzw. fehlenden Fortschritt erkennt.
> STRIPS/Planner eher für strategische Ziele/Recipes wie 20k A + 20k B + 20k C, nicht für einzelne Kampfaktionen.
> Combat, Navigation, Loot usw. als kleinere reaktive Controller/State Machines.
> Executor ist komplett getrennt und führt nur Actions/Input aus.
> Aktionen gelten erst als erfolgreich, wenn sie anschließend beobachtet/verifiziert wurden.
> Für Self-Healing: Dinge wie NO_PROGRESS, NO_MOBS, STUCK, INVENTORY_MISMATCH erkennen und darauf mit Recovery/Replanning reagieren.
> Langfristig kann der Bot z. B. Mob-Populationsgebiete lernen, sodass er bei leerem Gebiet selbstständig zu einem produktiveren Spot navigiert.
>
> In Kurzform:
>
> Recipe / Goal
>      ↓
> Planner
>      ↓
> Supervisor
>      ↕
> World State
>      ↑
> YOLO / OCR / CV
>      ↓
> Combat / Navigation / Loot
>      ↓
> Executor
>      ↓
> Game
>
> Das wäre aktuell die Architektur, die ich für dein Experiment favorisieren würde. keine code vorschläge oder sonstiges
