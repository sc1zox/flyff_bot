---
id: US-054
title: Farming Telemetrie, strukturierte Datenerhebung und Offline-RL-Dataset-Generierung
status: draft
created: 2026-08-19
updated: 2026-08-19
---

# US-054: Farming Telemetrie, strukturierte Datenerhebung und Offline-RL-Dataset-Generierung

## Story

As a **Flyff bot developer and ML engineer**,
I want **to record structured, noise-free, and high-frequency telemetry data on player kinematics, visible mob candidates, target selection decisions, navigation trajectories, combat dynamics, and kill cycles during autonomous farming sessions into an append-only JSONL stream via a decoupled background worker**,
so that **we obtain an authoritative offline dataset for training Reinforcement Learning (RL) and trajectory optimization policies (minimizing travel distance, target acquisition latency, and kill-to-kill time) without impacting the 10 Hz orchestrator loop or violating safety boundaries**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Relates to:
  - [`docs/wiki/architecture.md`](../wiki/architecture.md) & [`docs/wiki/glossary.md`](../wiki/glossary.md).
  - [`docs/decisions/ADR-004-coordinate-only-read-process-memory.md`](../decisions/ADR-004-coordinate-only-read-process-memory.md): Read-only `ReadProcessMemory` exclusively for player XYZ at `CMover + 0x188`. No additional memory offsets or code hooking.
  - [`docs/user-stories/completed/US-048-3d-world-navigation-teleport-dispatch-and-terrain-aware-pathing.md`](completed/US-048-3d-world-navigation-teleport-dispatch-and-terrain-aware-pathing.md) & [`docs/user-stories/completed/US-049-session-event-log-and-transition-diagnostics.md`](completed/US-049-session-event-log-and-transition-diagnostics.md).
  - [`docs/user-stories/US-052-client-archive-extraction-for-complete-3d-terrain-heightfields.md`](US-052-client-archive-extraction-for-complete-3d-terrain-heightfields.md) & [`docs/user-stories/US-053-pure-gps-navigation-and-client-profile-configuration.md`](US-053-pure-gps-navigation-and-client-profile-configuration.md).
- **100% Ground Truth & Elimination of Noise/Heuristics:**
  - *Player Kinematics:* Live 3D world coordinates $(x, y, z)$ read from memory via `LivePositionReader` at 10 Hz. Velocity $(\dot{x}, \dot{y}, \dot{z})$ and scalar speed $v = \|\dot{\mathbf{p}}\|$ are mathematically derived ($\Delta \mathbf{p} / \Delta t$).
  - *Player Vitals:* $HP\%, MP\%, FP\%$ measured pixel-accurately from the top-left HUD orb via `PlayerVitalsReader`.
  - *Perception (YOLO):* 2D bounding boxes $(x, y, w, h)$, confidences, class IDs, screen centers $(c_x, c_y)$, and screen distances to center $d_{\text{screen}}$. 3D world coordinates of mobs are only emitted if a 3D NavMesh/heightfield is loaded and camera alignment is active; otherwise explicitly `null` (no fabricated heuristics).
  - *Kill Verification:* Authoritative HUD kill counter OCR (`MonsterStatsReader`) and target HP bar collapse (`TargetVerifier`).
- **Offline Reinforcement Learning (RL) Transition Formulation:**
  - *Target Sequencing MDP Transition:*
    - State $S_t$: Player position, velocity, vitals, plus feature matrix for all $K$ visible mob candidates (BBox area, screen distance, confidence, class, 3D distance / NavMesh path distance if available, lockout status).
    - Action $A_t$: Selected candidate index $j^*$, decision latency $\Delta t_{\text{dec}}$, heuristic reason.
    - Reward $R_t$: Continuous reward based on kill-to-kill time, damage taken, stall events, and kill confirmation:
      $$R_t = - (\alpha \cdot T_{\text{k2k}} + \beta \cdot \Delta HP + \gamma \cdot T_{\text{stall}}) + \delta \cdot \mathbb{I}(\text{KillVerified})$$
  - *Kill-to-Kill Cycle ($T_{\text{k2k}}$) Decomposition:*
    $$T_{\text{k2k}} = T_{\text{decision}} + T_{\text{navigation}} + T_{\text{combat}} + T_{\text{idle}}$$
- **Non-Blocking I/O & Performance Architecture:**
  - Telemetry generation must never block the 10 Hz orchestrator tick or the PySide6 UI event loop.
  - A thread-safe bounded queue and dedicated background worker (`TelemetryWorker`) serialize and append JSONL records to disk (`data/telemetry/<area_id>/<date>/session_<session_id>.jsonl`).
  - Full-frame screenshots/videos are disabled by default to avoid multi-gigabyte disk saturation and I/O bottlenecks.
  - Telemetry operations are fail-safe: disk I/O errors or formatting exceptions are handled gracefully without aborting farming sessions.

## Functional Requirements

### FR-1 – Session-basierte Telemetrie & Metadaten
* Jede Farming-Session erzeugt beim Start eine eindeutige `session_id` (UUID4).
* Der Session-Header speichert unveränderliche Metadaten:
  * `client_sha256`: SHA-256 Digest von `neuz.exe`.
  * `bot_version`: Git-Commit / Semantic Version des Bots.
  * `schema_version`: Schema-Versionsnummer (z. B. `1`).
  * `area_id`: Aktiver Zonen-/Welt-Identifier (z. B. `"WdEden"`).
  * `session_start_utc`: ISO-8601 UTC-Startzeitpunkt.
  * `active_models`: YOLO-Modelldatei und Label-Konfiguration.
  * `active_spawn_zone`: Aus `.rgn` extrahierte Respawn-Metadaten (Monster-ID, Bounding Box, Kapazität, Respawn-Intervall).

### FR-2 – World-State-Snapshots (10 Hz)
* In jedem 10-Hz-Orchestrator-Tick wird ein reduzierter, strukturierter World-State-Snapshot erfasst:
  * `timestamp_ns`: Monotoner Nanosekunden-Zeitstempel.
  * `player_position`: $(x, y, z)$ in Welteinheiten (`PositionSource.LIVE`).
  * `player_velocity`: Numerisch abgeleiteter Vektor $(\dot{x}, \dot{y}, \dot{z})$ in Units/s.
  * `player_speed`: Skalarer Betrag $v = \sqrt{\dot{x}^2 + \dot{y}^2 + \dot{z}^2}$.
  * `player_vitals`: $HP\%, MP\%, FP\%$ ($0.0 - 100.0\%$).
  * `buff_cooldowns`: Verbleibende Cooldown-Sekunden aktiver Power-Up-Slots.
  * `farming_mode`: Diskreter Modus (`SEARCHING`, `TARGETING`, `COMBAT`, `REPOSITIONING`, `RECONCILING`, `PAUSED`, etc.).
  * `visible_mob_count`: Anzahl der im aktuellen Frame erkannten Mobs.

### FR-3 – Mob Detection & Candidate Matrix
* Für jeden im Frame erkannten Mob werden zum Entscheidungszeitpunkt folgende rauschfreie Features aufgezeichnet:
  * `candidate_index`: Index $j \in \{0..K-1\}$.
  * `class_id` & `class_name`: Erkannte Mobklasse.
  * `confidence`: YOLO-Inference-Score ($0.0 - 1.0$).
  * `bbox`: Client-Pixelkoordinaten $(x, y, w, h)$ und Zentrum $(c_x, c_y)$.
  * `screen_distance_to_center`: 2D-Pixel-Distanz $d_{\text{screen}}$ zum Viewport-Center.
  * `bbox_area`: Pixel-Fläche $w \times h$.
  * `world_position`: $(x_m, y_m, z_m)$ nur bei geladenem 3D-Terrain/NavMesh, sonst explizit `null`.
  * `relative_distance`: 3D-Distanz $d_{3D}$ zum Spieler (falls Weltkoordinaten verfügbar, sonst `null`).
  * `relative_elevation`: $\Delta y = y_{\text{mob}} - y_{\text{player}}$ (falls Weltkoordinaten verfügbar, sonst `null`).
  * `path_distance`: A*-NavMesh-Distanz $d_{\text{path}}$ (falls NavMesh verfügbar, sonst `null`).
  * `is_locked_out`: Boolean (ob Mob auf Lockout-Liste steht).

### FR-4 – Target Decision Events (`TARGET_SELECTED`)
* Bei jeder Zielauswahl wird ein `TARGET_SELECTED`-Event erzeugt mit:
  * `timestamp_ns` und `player_position`.
  * `selected_candidate_index`: Index des gewählten Mobs.
  * `decision_reason`: Heuristik-Typ (z. B. `NEAREST_TO_VIEWPORT_CENTER`, `QUOTA_PRIORITY`).
  * `decision_latency_ms`: Zeitdauer vom Suchstart/letzten Kill bis zur Zielauswahl.
  * `candidates`: Vollständiges Array aller $K$ sichtbaren Kandidaten mit deren Feature-Vektoren zum exakten Entscheidungszeitpunkt.

### FR-5 – Navigation Episode & Trajektorien
* Jede Bewegung zum Ziel wird als Navigation-Episode erfasst:
  * `nav_start_time`, `nav_end_time`, `nav_duration`.
  * `start_position` $(x_0, y_0, z_0)$ und `target_position` $(x_g, y_g, z_g)$.
  * `planned_route`: Geplante Wegpunkte $[(x_i, y_i, z_i)]$ aus dem A*-Planner.
  * `planned_length` $L_{\text{plan}}$ vs. `actual_travel_distance` $L_{\text{actual}}$.
  * `path_efficiency`: $\eta = L_{\text{plan}} / L_{\text{actual}}$.
  * `trajectory`: 10-Hz-Zeitreihe der realen GPS-Wegpunkte $[(t_k, x_k, y_k, z_k, v_k)]$.
  * `replans_count`: Anzahl durchgeführter Pfad-Neuplanungen.
  * `stall_events`: Anzahl und Gesamtdauer erkannter Hindernis-Stalls (`StallDetector`).
  * `collision_evasions`: Anzahl ausgeführter Strafe/Backstep-Ausweichmanöver.
  * `nav_outcome`: `REACHED_TARGET`, `TARGET_LOST`, `TARGET_DIED`, `TIMEOUT`, `STALL_ABORT`.

### FR-6 – Combat Episode & Verifikation
* Für jeden Kampf wird eine Combat-Episode erzeugt:
  * `combat_start_time`, `combat_end_time`, `time_to_kill` ($T_{\text{ttk}}$).
  * `target_name`: OCR-verifizierter Mob-Name.
  * `player_hp_start`, `player_hp_end`, `damage_taken` ($\Delta HP$).
  * `target_hp_start_pct`, `target_hp_end_pct` ($0.0 - 100.0\%$).
  * `attack_actions`: Array aller gesendeten Tastatureingaben $[(t_i, \text{key}_i, \text{duration}_i)]$.
  * `combat_outcome`: `KILL_VERIFIED`, `ENGAGEMENT_TIMEOUT`, `ACQUISITION_TIMEOUT`, `OBSTACLE_STALL`, `TARGET_LOST`.
  * `verification_source`: `HUD_COUNTER` (Session Stats Window) oder `HP_ZERO`.

### FR-7 – Kill-to-Kill Cycle ($T_{\text{k2k}}$)
* Das System berechnet für jeden bestätigten Kill den zusammenhängenden Zyklus:
  * $T_{\text{k2k}} = T_{\text{decision}} + T_{\text{navigation}} + T_{\text{combat}} + T_{\text{idle}}$.
  * Jede Zeitkomponente wird separat gespeichert und ist deterministisch aus den Events rekonstruierbar.

### FR-8 – Sequenzinformationen (Target-Sequencing)
* Die Abfolge aller getöteten Mobs einer Session wird als Graph rekonstruierbar gespeichert:
  $\text{Mob}_1 \to \text{Mob}_2 \to \dots \to \text{Mob}_N$.
* Jeder Übergang enthält: Start-/Zielposition, Distanz, Reisedauer, Kampfzeit und $T_{\text{k2k}}$.

### FR-9 – Performance, Speicherung & Fail-Safe
* Rohtelemetrie wird als JSONL gespeichert unter: `data/telemetry/<area_id>/<YYYY-MM-DD>/session_<session_id>.jsonl`.
* Telemetrie-Writes erfolgen vollständig asynchron über einen Hintergrund-Worker mit bounded Queue (`queue.Queue`).
* Bei voller Queue oder hoher I/O-Last wird Farming gegenüber Telemetrie priorisiert (kein Einfrieren des Bots).
* Disk- oder Serialisierungsfehler bringen weder den Orchestrator noch die PySide6-GUI zum Absturz.

## Acceptance criteria

- [ ] **Session & Metadata Lifecycle:**
  - Jede Farming-Session erzeugt beim Start einen versionierten Header-Datensatz (`schema_version: 1`) mit eindeutiger `session_id`, `client_sha256`, UTC-Startzeit, Modellpfaden und Gebiets-Metadaten.
- [ ] **10 Hz World-State Telemetrie:**
  - In jedem 10-Hz-Orchestrator-Tick wird ein Snapshot mit autoritativen GPS-Koordinaten $(x, y, z)$, numerisch abgeleitetem Geschwindigkeitsvektor $(\dot{x}, \dot{y}, \dot{z}, v)$, Vitals ($HP\%, MP\%, FP\%$) und Farming-Modus in die Telemetrie-Queue geschrieben.
- [ ] **Target Decision & Alternative Candidates Logging:**
  - Bei jedem `TARGET_SELECTED`-Event werden der gewählte Mob sowie die vollständige Feature-Matrix aller alternativen sichtbaren Kandidaten (BBox, Screen-Distanz, Fläche, Confidence, Klasse, Lockout-Status, und 3D-/NavMesh-Distanz sofern verfügbar) persistiert.
  - Wenn keine Weltkoordinaten verfügbar sind, wird `world_position` explizit als `null` gespeichert; es werden keine erfundenen Heuristiken abgelegt.
- [ ] **Navigation Episode & Trajectory Extraction:**
  - Für jede Navigationsepisode werden Start-/Zielkoordinaten, geplanter Pfad, reale 10-Hz-GPS-Trajektorie, zurückgelegte Wegstrecke, Pfadeffizienz $\eta$, Stall-Events, Ausweichschritte und das Navigationsergebnis aufgezeichnet.
- [ ] **Combat Episode & Kill Verification:**
  - Für jeden Kampf werden Start-/Endzeitpunkte, Time-to-Kill ($T_{\text{ttk}}$), Spielerschaden ($\Delta HP$), gesendete Angriffs-Hotkeys, Verifikationsquelle (`HUD_COUNTER` vs. `HP_ZERO`) und Kampfergebnis protokolliert.
- [ ] **Kill-to-Kill Cycle & Transition Dataset:**
  - Jeder Kill-Zyklus wird vollständig in $T_{\text{decision}} + T_{\text{navigation}} + T_{\text{combat}} + T_{\text{idle}}$ zerlegt und als vollständiges State-Action-Reward-Transition-Tuple für Offline-RL exportiert.
- [ ] **Performance & Threading-Entkopplung:**
  - Telemetrie-I/O blockiert zu keinem Zeitpunkt den 10-Hz-Orchestrator-Thread oder die Qt-GUI.
  - Serialisierung und Dateizugriffe laufen auf einem separaten Hintergrund-Worker.
- [ ] **Safety & ADR-004 Konformität:**
  - Keine zusätzlichen Memory-Offsets oder Speicher-Leseoperationen über `CMover + 0x188` hinaus.
  - Keine Memory-Writes, Code-Injections oder Umgehung bestehender Foreground-/Emergency-Stop-Gates.
- [ ] **Storage Control:**
  - Rohe Videoframes/Screenshots sind standardmäßig deaktiviert (rein numerische strukturierte JSONL-Events).
- [ ] **Typisierung & Tests:**
  - Alle neuen Datenmodelle und Telemetrie-Klassen bestehen `mypy --strict`.
  - Vollständige Unit-Test-Abdeckung für Telemetrie-Queue, JSONL-Writer, Kinematik-Ableitung und Event-Serialisierung.

## Out of scope

- Ausführen von Online-RL-Inferenz oder Policy-Netzwerken während der Live-Farming-Session (reine Datenerhebung).
- Speicher-Schreibzugriffe (`WriteProcessMemory`), Dynamic DLL Injection oder Memory Hooking.
- Kontinuierliche Speicherung von unkomprimierten 1080p-Videoframes oder Screenshots.
- Streaming von Telemetriedaten über HTTP-Server oder Cloud-Endpunkte.

## Verification

- Automated:
  - Unit-Tests in `tests/unit/test_telemetry.py` zur Validierung von Session-Metadaten, 10-Hz-Snapshot-Generierung und JSONL-Serialisierung.
  - Unit-Tests zur Validierung der numerischen Geschwindigkeitsableitung $(\dot{x}, \dot{y}, \dot{z}, v)$ und Kill-Cycle-Zerlegung ($T_{\text{k2k}}$).
  - Unit-Tests für `TelemetryWorker` zur Verifikation der asynchronen, blockierungsfreien Queue-Verarbeitung und Fehlerbehandlung bei vollem Speicher.
  - `./scripts/check.ps1` läuft fehlerfrei durch (`ruff check`, `ruff format --check`, `mypy`, `pytest`).
- Manual (Windows):
  - Starte eine Farming-Session in Entropia Flyff, führe mehrere Kills und Laufwege aus, und überprüfe, dass `data/telemetry/<area_id>/<date>/session_<session_id>.jsonl` erzeugt wird.
  - Validiere offline, dass die JSONL-Datei fehlerfrei geparst werden kann und für jeden Kill-Zyklus die vollständige Kette $\text{WorldState} \to \text{Candidates} \to \text{Target Selection} \to \text{Navigation} \to \text{Combat} \to \text{Kill}$ rekonstruiert werden kann.
