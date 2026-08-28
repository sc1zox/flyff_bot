"""The decision contract every artifact and dataset is stamped with (US-079).

An observation vector, an action index and a reward number only mean something together with
the contract that produced them. An artifact produced under a different contract cannot be
repaired by reordering columns or remapping indices, and
[ADR-003](../../../../docs/decisions/ADR-003-clean-schema-over-backward-compatibility.md)
forbids shimming it, so loading one is rejected with an explicit incompatibility diagnostic
that names what was expected and what was found.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique

from flyff_bot.features.policy.action_payloads import (
    OBJECTIVE_KIND_ORDER,
    STRATEGIC_GOAL_ORDER,
    TACTICAL_ACTION_COUNT,
)
from flyff_bot.features.rl.models import OBSERVATION_DIMENSION, RL_OBSERVATION_SCHEMA_VERSION
from flyff_bot.features.rl.rewards import REWARD_CONFIG_VERSION
from flyff_bot.features.tactical_parameters import TACTICAL_PARAMETER_SCHEMA_VERSION

# Bumped whenever any observation column, action index, goal vocabulary or reward weight
# changes. Artifacts stamped with any other value are rejected rather than adapted.
DECISION_CONTRACT_VERSION = "us083-v2"
# The key every artifact document and dataset stores its stamp under.
CONTRACT_DOCUMENT_KEY = "contract"
# What is reported as the found value when an artifact states nothing at all for a field.
CONTRACT_MISSING_MARKER = "none"


@unique
class ContractIncompatibility(StrEnum):
    """Why one artifact cannot be served by the running application."""

    CONTRACT_MISSING = "contract_stamp_missing"
    CONTRACT_VERSION = "contract_version_mismatch"
    OBSERVATION_SCHEMA = "observation_schema_mismatch"
    OBSERVATION_WIDTH = "observation_width_mismatch"
    GOAL_VOCABULARY = "goal_vocabulary_mismatch"
    ACTION_VOCABULARY = "action_vocabulary_mismatch"
    REWARD_CONFIG = "reward_config_mismatch"
    TACTICAL_PARAMETERS = "tactical_parameter_schema_mismatch"


class ContractVersionError(ValueError):
    """One artifact was produced under a different decision contract than this build."""

    def __init__(
        self,
        incompatibility: ContractIncompatibility,
        *,
        expected: object,
        found: object,
    ) -> None:
        self.incompatibility = incompatibility
        self.expected = str(expected)
        self.found = str(found)
        super().__init__(f"{incompatibility.value}:expected={self.expected},found={self.found}")


@dataclass(frozen=True, slots=True)
class ContractStamp:
    """Everything an artifact has to agree with the running application about."""

    contract_version: str
    observation_schema_version: str
    observation_width: int
    strategic_goal_order: tuple[str, ...]
    objective_kind_order: tuple[str, ...]
    tactical_action_count: int
    reward_config_version: str
    tactical_parameter_schema_version: str

    def as_document(self) -> dict[str, object]:
        """Return the stamp in the form written into an artifact or dataset."""

        return {
            "contract_version": self.contract_version,
            "observation_schema_version": self.observation_schema_version,
            "observation_width": self.observation_width,
            "strategic_goal_order": list(self.strategic_goal_order),
            "objective_kind_order": list(self.objective_kind_order),
            "tactical_action_count": self.tactical_action_count,
            "reward_config_version": self.reward_config_version,
            "tactical_parameter_schema_version": self.tactical_parameter_schema_version,
        }


def current_contract_stamp(*, reward_config_version: str = REWARD_CONFIG_VERSION) -> ContractStamp:
    """Return the contract this build produces and can serve."""

    return ContractStamp(
        DECISION_CONTRACT_VERSION,
        RL_OBSERVATION_SCHEMA_VERSION,
        OBSERVATION_DIMENSION,
        tuple(goal.value for goal in STRATEGIC_GOAL_ORDER),
        tuple(kind.value for kind in OBJECTIVE_KIND_ORDER),
        TACTICAL_ACTION_COUNT,
        reward_config_version,
        TACTICAL_PARAMETER_SCHEMA_VERSION,
    )


def verify_contract_document(document: object) -> ContractStamp:
    """Return the stamp an artifact carries, or reject the artifact.

    Every difference is reported as the exact field that disagrees, so an operator is told why
    an artifact was refused instead of seeing a generic load failure. No shim is attempted.
    """

    if not isinstance(document, dict):
        raise ContractVersionError(
            ContractIncompatibility.CONTRACT_MISSING,
            expected=DECISION_CONTRACT_VERSION,
            found=CONTRACT_MISSING_MARKER,
        )
    expected = current_contract_stamp()
    found = _read_stamp(document)
    for incompatibility, expected_value, found_value in (
        (
            ContractIncompatibility.CONTRACT_VERSION,
            expected.contract_version,
            found.contract_version,
        ),
        (
            ContractIncompatibility.OBSERVATION_SCHEMA,
            expected.observation_schema_version,
            found.observation_schema_version,
        ),
        (
            ContractIncompatibility.OBSERVATION_WIDTH,
            expected.observation_width,
            found.observation_width,
        ),
        (
            ContractIncompatibility.GOAL_VOCABULARY,
            _joined(expected.strategic_goal_order + expected.objective_kind_order),
            _joined(found.strategic_goal_order + found.objective_kind_order),
        ),
        (
            ContractIncompatibility.ACTION_VOCABULARY,
            expected.tactical_action_count,
            found.tactical_action_count,
        ),
        (
            ContractIncompatibility.REWARD_CONFIG,
            expected.reward_config_version,
            found.reward_config_version,
        ),
        (
            ContractIncompatibility.TACTICAL_PARAMETERS,
            expected.tactical_parameter_schema_version,
            found.tactical_parameter_schema_version,
        ),
    ):
        if expected_value != found_value:
            raise ContractVersionError(incompatibility, expected=expected_value, found=found_value)
    return found


def _read_stamp(document: dict[str, object]) -> ContractStamp:
    return ContractStamp(
        _text(document.get("contract_version")),
        _text(document.get("observation_schema_version")),
        _count(document.get("observation_width")),
        _text_tuple(document.get("strategic_goal_order")),
        _text_tuple(document.get("objective_kind_order")),
        _count(document.get("tactical_action_count")),
        _text(document.get("reward_config_version")),
        _text(document.get("tactical_parameter_schema_version")),
    )


def _text(value: object) -> str:
    return CONTRACT_MISSING_MARKER if value is None else str(value)


def _count(value: object) -> int:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else -1


def _text_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(str(item) for item in value)


def _joined(names: tuple[str, ...]) -> str:
    return ",".join(names) if names else CONTRACT_MISSING_MARKER
