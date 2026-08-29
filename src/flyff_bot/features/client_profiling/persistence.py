"""Validated all-or-nothing registry persistence for generated memory profiles."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from flyff_bot.features.client_profiling.models import (
    ClientProfilingError,
    ClientProfilingErrorCode,
    GeneratedClientProfileBundle,
)
from flyff_bot.features.dungeons.profiles import (
    BeginEndDungeonSpan,
    FixedDungeonArray,
    load_client_dungeon_profiles,
)
from flyff_bot.features.navigation.live_camera import load_client_camera_profiles
from flyff_bot.features.navigation.live_position import load_client_position_profiles
from flyff_bot.features.player_stats.profiles import (
    DirectPlayerStatSource,
    RatioPlayerStatSource,
    XorPairPlayerStatSource,
    load_client_player_stats_profiles,
)

ProfileLoader = Callable[[Path], object]


def persist_profile_bundle(
    bundle: GeneratedClientProfileBundle,
    *,
    position_path: Path,
    player_stats_path: Path,
    camera_path: Path,
    dungeon_path: Path,
) -> None:
    """Merge one digest into four registries and expose none before all validate."""

    targets = (
        (position_path, _position_document(bundle), load_client_position_profiles),
        (player_stats_path, _player_stats_document(bundle), load_client_player_stats_profiles),
        (camera_path, _camera_document(bundle), load_client_camera_profiles),
        (dungeon_path, _dungeon_document(bundle), load_client_dungeon_profiles),
    )
    staged: list[tuple[Path, Path]] = []
    originals: dict[Path, bytes | None] = {}
    replaced: list[Path] = []
    try:
        for target, document, loader in targets:
            originals[target] = target.read_bytes() if target.is_file() else None
            merged = _merge_registry(target, bundle.sha256, document)
            temporary = _stage_document(target, merged)
            loaded = loader(temporary)
            if bundle.sha256 not in loaded:
                raise ValueError(f"Generated profile {bundle.sha256} did not round-trip.")
            staged.append((target, temporary))
        for target, temporary in staged:
            os.replace(temporary, target)
            replaced.append(target)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        for target in reversed(replaced):
            _restore_original(target, originals[target])
        raise ClientProfilingError(
            ClientProfilingErrorCode.PERSISTENCE_FAILED,
            str(error),
        ) from error
    finally:
        for _target, temporary in staged:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)


def _merge_registry(path: Path, digest: str, document: dict[str, object]) -> list[object]:
    if not path.is_file():
        return [document]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Profile registry {path} must contain a JSON list.")
    retained = [
        item
        for item in payload
        if not (
            isinstance(item, dict)
            and isinstance(item.get("sha256"), str)
            and item["sha256"].lower() == digest
        )
    ]
    retained.append(document)
    return retained


def _stage_document(target: Path, payload: list[object]) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(raw_path)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return temporary


def _restore_original(target: Path, payload: bytes | None) -> None:
    if payload is None:
        target.unlink(missing_ok=True)
        return
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f".{target.name}.restore.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(raw_path)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
    os.replace(temporary, target)


def _position_document(bundle: GeneratedClientProfileBundle) -> dict[str, object]:
    profile = bundle.position
    return {
        "sha256": profile.sha256,
        "player_pointer_rva": profile.player_pointer_rva,
        "pointer_size_bytes": profile.pointer_size_bytes,
        "position_offset": profile.position_offset,
    }


def _player_stats_document(bundle: GeneratedClientProfileBundle) -> dict[str, object]:
    profile = bundle.player_stats
    fields: list[dict[str, object]] = []
    for field in profile.fields:
        source = field.source
        if isinstance(source, DirectPlayerStatSource):
            source_document: dict[str, object] = {
                "kind": source.kind.value,
                "offset": source.offset,
                "primitive": source.primitive.value,
            }
        elif isinstance(source, XorPairPlayerStatSource):
            source_document = {
                "kind": source.kind.value,
                "offset": source.offset,
                "key_a": source.key_a,
                "key_b": source.key_b,
                "primitive": source.primitive.value,
            }
        else:
            if not isinstance(source, RatioPlayerStatSource):
                raise TypeError("Unsupported generated player-stat source.")
            source_document = {
                "kind": source.kind.value,
                "numerator_offset": source.numerator_offset,
                "denominator_offset": source.denominator_offset,
                "primitive": source.primitive.value,
                "scale": source.scale,
            }
        fields.append(
            {
                "name": field.name,
                "source": source_document,
                "minimum": field.minimum,
                "maximum": field.maximum,
                "is_unknown": field.is_unknown,
            }
        )
    doc: dict[str, object] = {
        "sha256": profile.sha256,
        "player_pointer_rva": profile.player_pointer_rva,
        "pointer_size_bytes": profile.pointer_size_bytes,
        "fields": fields,
    }
    if profile.monster_kills_rva is not None and profile.monster_kills_rva > 0:
        doc["monster_kills_rva"] = profile.monster_kills_rva
    return doc


def _camera_document(bundle: GeneratedClientProfileBundle) -> dict[str, object]:
    profile = bundle.camera
    return {
        "sha256": profile.sha256,
        "camera_pointer_rva": profile.camera_pointer_rva,
        "pointer_size_bytes": profile.pointer_size_bytes,
        "eye_position_offset": profile.eye_position_offset,
        "view_matrix_offset": profile.view_matrix_offset,
        "look_at_offset": profile.look_at_offset,
        "projection_matrix_rva": profile.projection_matrix_rva,
    }


def _dungeon_document(bundle: GeneratedClientProfileBundle) -> dict[str, object]:
    profile = bundle.dungeon
    container = profile.container
    if isinstance(container, FixedDungeonArray):
        container_document: dict[str, object] = {
            "kind": container.kind.value,
            "records_offset": container.records_offset,
            "record_size_bytes": container.record_size_bytes,
            "record_count": container.record_count,
        }
    else:
        if not isinstance(container, BeginEndDungeonSpan):
            raise TypeError("Unsupported generated dungeon container.")
        container_document = {
            "kind": container.kind.value,
            "container_offset": container.container_offset,
            "begin_pointer_offset": container.begin_pointer_offset,
            "end_pointer_offset": container.end_pointer_offset,
            "record_size_bytes": container.record_size_bytes,
            "maximum_record_count": container.maximum_record_count,
        }
    fields = profile.fields
    return {
        "sha256": profile.sha256,
        "runtime_state_pointer_rva": profile.runtime_state_pointer_rva,
        "pointer_size_bytes": profile.pointer_size_bytes,
        "container": container_document,
        "fields": {
            "dungeon_id_offset": fields.dungeon_id_offset,
            "cooldown_end_timestamp_offset": fields.cooldown_end_timestamp_offset,
            "entries_used_offset": fields.entries_used_offset,
            "daily_entry_limit_offset": fields.daily_entry_limit_offset,
        },
    }
