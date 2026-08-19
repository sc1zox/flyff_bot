---
id: US-054
title: Farming Telemetrie, SQLite Betriebsdaten, Parquet-Export und Offline-RL-Dataset-Generierung
status: in-progress
created: 2026-08-19
updated: 2026-08-19
---

# US-054: Farming Telemetrie, SQLite Betriebsdaten, Parquet-Export und Offline-RL-Dataset-Generierung

## Story

As a **Flyff bot developer and ML engineer**,
I want **to record structured, noise-free telemetry into an append-only JSONL stream via a decoupled background worker, maintain an operative SQLite telemetry database for fast local queries and UI diagnostics, and provide a batch converter for compiling compressed Parquet datasets**,
so that **we have instant operational insight during farming sessions and an authoritative, high-performance dataset for training Reinforcement Learning (RL) and trajectory optimization policies without impacting the 10 Hz orchestrator loop**.

## Context and assumptions

- Target client: Entropia Flyff PServer (`neuz.exe`).
- Relates to:
  - [`docs/wiki/architecture.md`](../wiki/architecture.md) & [`docs/wiki/glossary.md`](../wiki/glossary.md).
  - [`docs/decisions/ADR-005-client-folder-asset-access-for-data-extraction.md`](../decisions/ADR-005-client-folder-asset-access-for-data-extraction.md): Vollständiger Lesezugriff auf lokale Client-Dateien, Archive (.one/.hdr), Spawn-Zonen (.rgn), Weltdefinitionen (.wld) und 3D-Terrain (.lnd).
  - [`docs/user-stories/completed/US-048-3d-world-navigation-teleport-dispatch-and-terrain-aware-pathing.md`](completed/US-048-3d-world-navigation-teleport-dispatch-and-terrain-aware-pathing.md) & [`docs/user-stories/completed/US-049-session-event-log-and-transition-diagnostics.md`](completed/US-049-session-event-log-and-transition-diagnostics.md).
  - [`docs/user-stories/US-052-client-archive-extraction-for-complete-3d-terrain-heightfields.md`](US-052-client-archive-extraction-for-complete-3d-terrain-heightfields.md): Extraktion aller 3.861 Terrainblöcke und 3D-NavMesh-Kompilierung mit Sub-Millisekunden-Routing.
  - [`docs/user-stories/US-053-pure-gps-navigation-and-client-profile-configuration.md`](US-053-pure-gps-navigation-and-client-profile-configuration.md): Reines 3D-GPS-Navigationsmodell.
- **Freie Datenverfügbarkeit & Entwickler-Handlungsspielraum:**
  - Alle für die Telemetrie und das RL-Training relevanten Datenquellen des Clients (Live-Speicher, Bild-/HUD-Sensoren, statische Client-Dateien und extrahierte 3D-NavMeshes) stehen für die Implementierung uneingeschränkt zur Verfügung.
  - Die in dieser User Story beschriebenen Datenstrukturen, Event-Formate, Tabellenschemata, Parquet-Layouts und Worker-Konzepte dienen als **fundierter Referenzvorschlag und Leitfaden, nicht als starre Solution Outline**.
  - Der implementierende Entwickler besitzt **vollen Handlungsspielraum** bei der konkreten softwaretechnischen Modellierung (z. B. SQLite-Schema-Design, Batch-Größen, Parquet-Kompression snappy/zstd, Queue-Drop-Policies und Dataclass-Hierarchien), solange die Akzeptanzkriterien, die Rauschfreiheit und die Performance-Ziele (I/O-Entkopplung) erfüllt werden.
- **Dual-Tier Storage Architecture (Append-Only JSONL + SQLite + Parquet Export):**
  1. *Live Capture Layer (JSONL):* Bounded in-memory queue $\to$ asynchronous background worker $\to$ append-only JSONL files (`data/telemetry/<area_id>/<date>/session_<session_id>.jsonl`). Fail-safe and zero-latency impact on 10 Hz orchestrator ticks.
  2. *Operative Storage Layer (SQLite):* `SqliteTelemetryStore` (`data/telemetry.sqlite3`) for fast indexed queries across session histories, kill totals, stall frequencies, combat durations, and dashboard analytics.
  3. *ML/RL Training Layer (Parquet):* Batch exporter / CLI command (`flyff-bot export-telemetry --format parquet`) that compiles raw JSONL/SQLite sessions into columnar, compressed `.parquet` tables (e.g. `target_decisions.parquet`, `navigation_episodes.parquet`, `kill_cycles.parquet`) optimized for PyTorch, DuckDB, Polars, and Pandas.
- **100% Ground Truth & Integration mit 3D NavMesh (US-052 & ADR-005):**
  - *Player Kinematics:* Live 3D world coordinates $(x, y, z)$ read from memory via `LivePositionReader` at 10 Hz. Velocity $(\dot{x}, \dot{y}, \dot{z})$ and scalar speed $v = \|\dot{\mathbf{p}}\|$ are mathematically derived ($\Delta \mathbf{p} / \Delta t$).
  - *Terrain & NavMesh Geometry:* Gemäß ADR-005 und US-052 stellt das extrahierte 3D-NavMesh authoritative Bodenhöhen $y = \text{height\_at}(x, z)$, Geländesteigungen $\nabla y$, NavMesh-Polygon-IDs und Hindernis-Clearances bereit.
  - *Player Vitals:* $HP\%, MP\%, FP\%$ measured pixel-accurately from the top-left HUD orb via `PlayerVitalsReader`.
  - *Perception (YOLO + 3D NavMesh Raycast):* 2D bounding boxes $(x, y, w, h)$, confidences, class IDs, screen centers $(c_x, c_y)$, and screen distances to center $d_{\text{screen}}$. 3D world coordinates of mobs $(x_m, y_m, z_m)$ are determined via calibrated ground-raycast on the US-052 3D NavMesh/Heightfield. If the map/camera is uncalibrated, world coordinates are explicitly `null` (no fabricated heuristics).
  - *Kill Verification:* Authoritative HUD kill counter OCR (`MonsterStatsReader`) und Target HP bar collapse (`TargetVerifier`).
- **Offline Reinforcement Learning (RL) Transition Formulation:**
  - *Target Sequencing MDP Transition:*
    - State $S_t$: Player kinematics $(x, y, z, \dot{x}, \dot{y}, \dot{z})$, current NavMesh polygon ID, vitals, plus feature matrix for all $K$ visible mob candidates (BBox area, screen distance, confidence, class, 3D Euclidean distance $d_{3D}$, US-052 NavMesh topological path distance $d_{\text{path}}$, relative elevation $\Delta y$, local terrain slope, lockout status).
    - Action $A_t$: Selected candidate index $j^*$, decision latency $\Delta t_{\text{dec}}$, heuristic reason.
    - Reward $R_t$: Continuous reward based on kill-to-kill time, damage taken, stall events, and kill confirmation:
      $$R_t = - (\alpha \cdot T_{\text{k2k}} + \beta \cdot \Delta HP + \gamma \cdot T_{\text{stall}}) + \delta \cdot \mathbb{I}(\text{KillVerified})$$
  - *Kill-to-Kill Cycle ($T_{\text{k2k}}$) Decomposition:*
    $$T_{\text{k2k}} = T_{\text{decision}} + T_{\text{navigation}} + T_{\text{combat}} + T_{\text{idle}}$$

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
  * `navmesh_version`: Version / Hash der geladenen 3D-NavMesh-Karte (aus US-052 & ADR-005).
  * `active_spawn_zone`: Aus `.rgn` extrahierte Respawn-Metadaten (Monster-ID, Bounding Box, Kapazität, Respawn-Intervall).

### FR-2 – World-State-Snapshots (10 Hz)
* In jedem 10-Hz-Orchestrator-Tick wird ein reduzierter, strukturierter World-State-Snapshot erfasst:
  * `timestamp_ns`: Monotoner Nanosekunden-Zeitstempel.
  * `player_position`: $(x, y, z)$ in Welteinheiten (`PositionSource.LIVE`).
  * `player_velocity`: Numerisch abgeleiteter Vektor $(\dot{x}, \dot{y}, \dot{z})$ in Units/s.
  * `player_speed`: Skalarer Betrag $v = \sqrt{\dot{x}^2 + \dot{y}^2 + \dot{z}^2}$.
  * `player_navmesh_polygon_id`: Aktuelle NavMesh-Polygon-ID (aus US-052).
  * `player_terrain_slope`: Lokaler Geländegradient an der aktuellen Spielerposition.
  * `player_vitals`: $HP\%, MP\%, FP\%$ ($0.0 - 100.0\%$).
  * `buff_cooldowns`: Verbleibende Cooldown-Sekunden aktiver Power-Up-Slots.
  * `farming_mode`: Diskreter Modus (`SEARCHING`, `TARGETING`, `COMBAT`, `REPOSITIONING`, `RECONCILING`, `PAUSED`, etc.).
  * `visible_mob_count`: Anzahl der im aktuellen Frame erkannten Mobs.

### FR-3 – Mob Detection & Candidate Matrix (mit US-052 3D NavMesh & ADR-005)
* Für jeden im Frame erkannten Mob werden zum Entscheidungszeitpunkt folgende rauschfreie Features aufgezeichnet:
  * `candidate_index`: Index $j \in \{0..K-1\}$.
  * `class_id` & `class_name`: Erkannte Mobklasse.
  * `confidence`: YOLO-Inference-Score ($0.0 - 1.0$).
  * `bbox`: Client-Pixelkoordinaten $(x, y, w, h)$ und Zentrum $(c_x, c_y)$.
  * `screen_distance_to_center`: 2D-Pixel-Distanz $d_{\text{screen}}$ zum Viewport-Center.
  * `bbox_area`: Pixel-Fläche $w \times h$.
  * `world_position`: Projizierter 3D-Schnittpunkt $(x_m, y_m, z_m)$ auf dem US-052 3D-NavMesh/Terrain; falls ungeladen, explizit `null`.
  * `relative_distance`: 3D-Distanz $d_{3D}$ zum Spieler (falls Weltkoordinaten verfügbar, sonst `null`).
  * `relative_elevation`: $\Delta y = y_{\text{mob}} - y_{\text{player}}$ (falls Weltkoordinaten verfügbar, sonst `null`).
  * `target_navmesh_polygon_id`: Ziel-Polygon-ID auf dem NavMesh (aus US-052).
  * `path_distance`: Exakte sub-millisekunden A*-NavMesh-Korridordistanz $d_{\text{path}}$ (aus US-052; falls NavMesh ungeladen, `null`).
  * `is_locked_out`: Boolean (ob Mob auf Lockout-Liste steht).

### FR-4 – Target Decision Events (`TARGET_SELECTED`)
* Bei jeder Zielauswahl wird ein `TARGET_SELECTED`-Event erzeugt mit:
  * `timestamp_ns` und `player_position`.
  * `selected_candidate_index`: Index des gewählten Mobs.
  * `decision_reason`: Heuristik-Typ (z. B. `NEAREST_TO_VIEWPORT_CENTER`, `QUOTA_PRIORITY`).
  * `decision_latency_ms`: Zeitdauer vom Suchstart/letzten Kill bis zur Zielauswahl.
  * `candidates`: Vollständiges Array aller $K$ sichtbaren Kandidaten mit deren Feature-Vektoren zum exakten Entscheidungszeitpunkt.

### FR-5 – Navigation Episode & Trajektorien (mit US-052 Funnel-Wegpunkten)
* Jede Bewegung zum Ziel wird als Navigation-Episode erfasst:
  * `nav_start_time`, `nav_end_time`, `nav_duration`.
  * `start_position` $(x_0, y_0, z_0)$ und `target_position` $(x_g, y_g, z_g)$.
  * `planned_route`: Geplante 3D-Funnel-Wegpunkte $[(x_i, y_i, z_i)]$ aus dem US-052 NavMesh Route Planner.
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
* Jeder Übergang enthält: Start-/Zielposition, Distanz, NavMesh-Pfadlänge, Reisedauer, Kampfzeit und $T_{\text{k2k}}$.

### FR-9 – Operative Telemetrie-Datenbank (SQLite)
* `SqliteTelemetryStore` persistiert operative Farming-Ereignisse in `data/telemetry.sqlite3`:
  * Tabellen für `telemetry_sessions`, `target_decisions`, `navigation_episodes`, `combat_episodes` und `stall_events`.
  * Ermöglicht indizierte Abfragen für UI-Diagnostik, Kill-Raten-Berechnungen, $T_{\text{k2k}}$-Histogramme und historische Session-Vergleiche ohne sequentielles JSONL-Parsing.
  * Transaktionale Sicherheit und Verbindungspooling/Short-Lived Connections für Thread-Sicherheit.

### FR-10 – Training Dataset Pipeline (Parquet-Export)
* Ein dedizierter Exporter (`TelemetryDatasetExporter`) kompiliert aufgezeichnete JSONL/SQLite-Sessions in komprimierte, spaltenbasierte `.parquet`-Dateien unter `data/datasets/rl/`:
  * `target_decisions.parquet`: Feature-Matrizen aller Kandidaten mit gewählter Aktion und resultierendem Reward für Target-Sequencing Policies.
  * `navigation_trajectories.parquet`: 10-Hz-Trajektorienpunkte, Funnel-Wegpunkte und Effizienzmetriken für Tactical Navigation Policies.
  * `kill_cycles.parquet`: Aggregierte Kill-to-Kill-Metriken ($T_{\text{k2k}}, T_{\text{decision}}, T_{\text{nav}}, T_{\text{combat}}$).
* Volle Kompatibilität mit Dataframes (Polars, Pandas, DuckDB) und Deep-Learning-Loadern (PyTorch Datasets / DataLoaders).

### FR-11 – Performance, Speicherung & Fail-Safe
* Rohtelemetrie wird als JSONL gespeichert unter: `data/telemetry/<area_id>/<YYYY-MM-DD>/session_<session_id>.jsonl`.
* Telemetrie-Writes erfolgen vollständig asynchron über einen Hintergrund-Worker mit bounded Queue (`queue.Queue`).
* Bei voller Queue oder hoher I/O-Last wird Farming gegenüber Telemetrie priorisiert (kein Einfrieren des Bots).
* Disk- oder Serialisierungsfehler bringen weder den Orchestrator noch die PySide6-GUI zum Absturz.

## Acceptance criteria

- [ ] **Session & Metadata Lifecycle:**
  - Jede Farming-Session erzeugt beim Start einen versionierten Header-Datensatz (`schema_version: 1`) mit eindeutiger `session_id`, `client_sha256`, UTC-Startzeit, Modellpfaden, 3D-NavMesh-Metadaten (US-052 / ADR-005) und Gebiets-Metadaten.
- [ ] **10 Hz World-State Telemetrie:**
  - In jedem 10-Hz-Orchestrator-Tick wird ein Snapshot mit autoritativen GPS-Koordinaten $(x, y, z)$, numerisch abgeleitetem Geschwindigkeitsvektor $(\dot{x}, \dot{y}, \dot{z}, v)$, aktuellem NavMesh-Polygon-ID, Geländesteigung, Vitals ($HP\%, MP\%, FP\%$) und Farming-Modus in die Telemetrie-Queue geschrieben.
- [ ] **Target Decision & Alternative Candidates Logging (US-052 NavMesh & ADR-005):**
  - Bei jedem `TARGET_SELECTED`-Event werden der gewählte Mob sowie die vollständige Feature-Matrix aller alternativen sichtbaren Kandidaten (BBox, Screen-Distanz, Fläche, Confidence, Klasse, Lockout-Status, projizierte 3D-Koordinate, 3D-Distanz und US-052 NavMesh-Pfaddistanz $d_{\text{path}}$) persistiert.
  - Wenn keine Weltkoordinaten verfügbar sind, wird `world_position` explizit als `null` gespeichert; es werden keine erfundenen Heuristiken abgelegt.
- [ ] **Navigation Episode & Trajectory Extraction:**
  - Für jede Navigationsepisode werden Start-/Zielkoordinaten, geplante 3D-Funnel-Wegpunkte (US-052), reale 10-Hz-GPS-Trajektorie, zurückgelegte Wegstrecke, Pfadeffizienz $\eta$, Stall-Events, Ausweichschritte und das Navigationsergebnis aufgezeichnet.
- [x] **Combat Episode & Kill Verification:**
  - Für jeden Kampf werden Start-/Endzeitpunkte, Time-to-Kill ($T_{\text{ttk}}$), Spielerschaden ($\Delta HP$), gesendete Angriffs-Hotkeys, Verifikationsquelle (`HUD_COUNTER` vs. `HP_ZERO`) und Kampfergebnis protokolliert.
- [ ] **Kill-to-Kill Cycle & Transition Dataset:**
  - Jeder Kill-Zyklus wird vollständig in $T_{\text{decision}} + T_{\text{navigation}} + T_{\text{combat}} + T_{\text{idle}}$ zerlegt und als vollständiges State-Action-Reward-Transition-Tuple für Offline-RL exportiert.
- [x] **Operative SQLite-Telemetrie:**
  - `SqliteTelemetryStore` persistiert strukturierte Session-, Target-, Navigations- und Combat-Ereignisse in `data/telemetry.sqlite3` mit optimierten Indizes für schnelle Abfragen.
- [x] **Parquet-Export für ML-Training:**
  - Ein CLI-Befehl/Exporter generiert aus aufgezeichneten Sessions validierte, schema-konforme `.parquet`-Dateien (`target_decisions.parquet`, `navigation_trajectories.parquet`, `kill_cycles.parquet`) unter `data/datasets/rl/`.
- [x] **Performance & Threading-Entkopplung:**
  - Telemetrie-I/O blockiert zu keinem Zeitpunkt den 10-Hz-Orchestrator-Thread oder die Qt-GUI.
  - Serialisierung und Dateizugriffe laufen auf einem separaten Hintergrund-Worker.
- [x] **Storage Control:**
  - Rohe Videoframes/Screenshots sind standardmäßig deaktiviert (rein numerische strukturierte JSONL-Events).
- [x] **Typisierung & Tests:**
  - Alle neuen Datenmodelle und Telemetrie-Klassen bestehen `mypy --strict`.
  - Vollständige Unit-Test-Abdeckung für Telemetrie-Queue, SQLite-Store, Parquet-Exporter, Kinematik-Ableitung und Event-Serialisierung.

## Implementation status

The delivered numeric telemetry path is deliberately truthful about its current integration
boundary. `TelemetryRecorder` writes schema-v1 session envelopes, 10-Hz world snapshots, target
decisions, combat episodes, and verified-kill cycles through a bounded asynchronous JSONL worker;
the worker mirrors records into SQLite and the CLI exports the three stable Parquet tables.

The following acceptance criteria remain open and keep this story **in progress**:

- Session metadata is not yet populated with a client digest, bot version, loaded NavMesh version,
  or active spawn-zone metadata.
- The US-052 NavMesh/raycast provider is not available to this integration. Snapshot polygon and
  terrain-slope fields, plus candidate world position, 3D distance, relative elevation, target
  polygon, and path distance, are therefore persisted explicitly as `null`; no estimated geometry
  is fabricated.
- Target-selection envelopes preserve the visible candidate ordering and screen-space features, but
  their lockout status is not yet connected to the active lockout list.
- `NavigationEpisode` and `STALL_EVENT` contracts and storage/export support exist, but the
  orchestrator does not yet instrument active navigation into completed episodes, trajectories,
  replans, or stall events.
- Verified kill cycles currently record measured combat duration and the remaining interval as
  idle time; they do not yet derive the required decision, navigation, combat, and idle
  decomposition from integrated episode boundaries.

## Out of scope

- Ausführen von Online-RL-Inferenz oder Policy-Netzwerken während der Live-Farming-Session (reine Datenerhebung).
- Speicher-Schreibzugriffe (`WriteProcessMemory`), Dynamic DLL Injection oder Memory Hooking.
- Kontinuierliche Speicherung von unkomprimierten 1080p-Videoframes oder Screenshots.
- Streaming von Telemetriedaten über HTTP-Server oder Cloud-Endpunkte.

## Verification

- Automated:
  - Unit-Tests in `tests/unit/test_telemetry.py` zur Validierung von Session-Metadaten, 10-Hz-Snapshot-Generierung und JSONL-Serialisierung.
  - Unit-Tests in `tests/unit/test_telemetry_sqlite.py` zur Validierung von Schema-Initialisierung, Event-Inserts und operativen Abfragen.
  - Unit-Tests in `tests/unit/test_telemetry_parquet.py` zur Validierung der Parquet-Export-Pipeline, Columnar-Schemas und Datentyp-Integrität.
  - `./scripts/check.ps1` läuft fehlerfrei durch (`ruff check`, `ruff format --check`, `mypy`, `pytest`).
- Manual (Windows, outstanding):
  - [ ] Starte eine Farming-Session in Entropia Flyff mit geladenem US-052 3D-NavMesh, führe mehrere Kills und Laufwege aus, und überprüfe, dass sowohl `data/telemetry/<area_id>/<date>/session_<session_id>.jsonl` als auch `data/telemetry.sqlite3` aktualisiert werden.
  - [ ] Führe den Parquet-Export aus und verifiziere, dass die erzeugten `.parquet`-Dateien in Python (z. B. via `duckdb` oder `polars`) direkt geladen und für RL-Training analysiert werden können.
