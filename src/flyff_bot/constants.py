"""Application-wide constants with stable domain meaning."""

from enum import IntEnum

DEFAULT_PROCESS_NAME = "neuz.exe"
DEFAULT_KEY_DURATION_SECONDS = 0.08
DEFAULT_START_DELAY_SECONDS = 3.0
MINIMUM_KEY_DURATION_SECONDS = 0.01
DEFAULT_DATASET_MANIFEST_PATH = "data/datasets/mobs/data.yaml"
DEFAULT_MOB_MODEL_PATH = "models/mob_detector.onnx"
DEFAULT_MOB_LABELS_PATH = "models/labels.txt"
DEFAULT_TRAINING_EPOCHS = 100
DEFAULT_CLIENT_POSITION_PROFILES_PATH = "data/navigation/client_profiles.json"
DEFAULT_CLIENT_CAMERA_PROFILES_PATH = "data/config/client_camera_profiles.json"
# Live dungeon cooldown profiles (US-063) remain empty until an exact client binary has
# verified offsets; the reader refuses to guess rather than reading an inferred address.
DEFAULT_CLIENT_DUNGEON_PROFILES_PATH = "data/config/client_dungeon_profiles.json"
DEFAULT_TELEMETRY_ROOT = "data/telemetry"
DEFAULT_TELEMETRY_DATABASE_PATH = "data/telemetry.sqlite3"
DEFAULT_TELEMETRY_DATASET_PATH = "data/datasets/rl"
DEFAULT_TELEMETRY_AREA_ID = "unknown"
# Offline farming value models trained from recorded telemetry (US-066). The version segment
# is part of the path so a new artifact set never overwrites the one a session already loaded.
DEFAULT_FARMING_VALUE_MODEL_PATH = "models/farming_value/v1"
# Extracted client world geometry (US-045). The client tree is the operator's own game
# installation and is never part of this repository, so the default only states where an
# unmodified Entropia install keeps its regions relative to the working directory.
DEFAULT_CLIENT_WORLD_ROOT = "Entropia/Entropia/Data/World"
DEFAULT_WORLD_MAP_DIRECTORY = "data/navigation/worlds"
DEFAULT_WORLD_MONSTER_IDS_PATH = "data/assets/world/monster_ids.json"
# Extracted client quest definitions (US-061). The client data tree holds the quest
# scripts, property tables, and language catalogs the extraction pass reads.
DEFAULT_CLIENT_DATA_ROOT = "Entropia/Entropia/Data"
DEFAULT_QUEST_DATABASE_PATH = "data/quests/quests.json"
DEFAULT_DUNGEON_DATABASE_PATH = "data/dungeons/dungeons.json"
DEFAULT_QUEST_NPC_POSITIONS_PATH = "data/quests/npc_positions.json"
# Reference screenshot of the in-game session stats window; its header line is the template
# that locates the same window in a live frame.
DEFAULT_MONSTER_STATS_PANEL_PATH = "data/assets/stats/monster_stats.png"
DEFAULT_TARGET_ANCHOR_PATH = "data/assets/mobs/target_anchor.png"
DEFAULT_TELEPORTER_DATABASE_PATH = "data/navigation/teleporters.json"
DEFAULT_CLIENT_WORLD_ID_PROFILES_PATH = "data/navigation/client_world_id_profiles.json"
DEFAULT_PLAYER_VITALS_PANEL_PATH = "data/assets/player/player_vitals_left_top_corner.png"
# Live dungeon cooldown profiles (US-063) remain empty until an exact client binary has
# verified offsets; the reader refuses to guess rather than reading an inferred address.
DEFAULT_CLIENT_DUNGEON_PROFILES_PATH = "data/config/client_dungeon_profiles.json"


class ExitCode(IntEnum):
    """Process exit codes exposed by the command-line interface."""

    SUCCESS = 0
    WINDOW_NOT_FOUND = 1
    ABORTED = 2
    INPUT_FAILURE = 3
    DETECTION_FAILURE = 4
    DATASET_FAILURE = 5
    TRAINING_FAILURE = 6
    WORLD_EXTRACTION_FAILURE = 7
    QUEST_EXTRACTION_FAILURE = 8
    VALUE_MODEL_FAILURE = 9
    TELEPORTER_EXTRACTION_FAILURE = 10
    DUNGEON_EXTRACTION_FAILURE = 11
