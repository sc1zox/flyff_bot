"""Offline entry point that trains the farming value models from recorded telemetry.

The command is fully decoupled from the running game: it reads Parquet tables from disk,
writes model artifacts, and never opens a window, sends input, or reads process memory.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from flyff_bot.constants import (
    DEFAULT_FARMING_VALUE_MODEL_PATH,
    DEFAULT_TELEMETRY_DATABASE_PATH,
    DEFAULT_TELEMETRY_DATASET_PATH,
    ExitCode,
)
from flyff_bot.features.ml.cost import (
    DEFAULT_FOLLOWUP_WEIGHT,
    DEFAULT_KILL_WEIGHT,
    DEFAULT_STUCK_WEIGHT,
    DEFAULT_TRAVEL_WEIGHT,
    ExpectedCostWeights,
)
from flyff_bot.features.ml.dataset import (
    DEFAULT_HOLDOUT_FRACTION,
    DatasetError,
    DatasetErrorCode,
    FollowupValueDefinition,
)
from flyff_bot.features.ml.export import ExportError, ExportErrorCode
from flyff_bot.features.ml.models import DEFAULT_LOGISTIC_L2, DEFAULT_RIDGE_ALPHA
from flyff_bot.features.ml.pipeline import (
    DEFAULT_FOLLOWUP_DEFINITION,
    TrainingConfig,
    TrainingReport,
    train_farming_value_models,
)
from flyff_bot.i18n import Message, Translator

_DATASET_ERROR_MESSAGES = {
    DatasetErrorCode.TABLE_MISSING: Message.VALUE_MODEL_TABLE_MISSING,
    DatasetErrorCode.TABLE_UNREADABLE: Message.VALUE_MODEL_TABLE_UNREADABLE,
    DatasetErrorCode.NO_SAMPLES: Message.VALUE_MODEL_NO_SAMPLES,
}
_EXPORT_ERROR_MESSAGES = {
    ExportErrorCode.ONNX_EXTRA_REQUIRED: Message.VALUE_MODEL_ONNX_REQUIRED,
    ExportErrorCode.EXPORT_FAILED: Message.VALUE_MODEL_EXPORT_FAILED,
}


def build_parser(translator: Translator) -> argparse.ArgumentParser:
    """Assemble the localized argument parser for one offline training run."""

    parser = argparse.ArgumentParser(
        prog="flyff-bot-train-farming-value",
        description=translator.text(Message.VALUE_MODEL_DESCRIPTION),
    )
    parser.add_argument(
        "--dataset",
        default=DEFAULT_TELEMETRY_DATASET_PATH,
        help=translator.text(
            Message.HELP_VALUE_MODEL_DATASET, default=DEFAULT_TELEMETRY_DATASET_PATH
        ),
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_FARMING_VALUE_MODEL_PATH,
        help=translator.text(
            Message.HELP_VALUE_MODEL_OUTPUT, default=DEFAULT_FARMING_VALUE_MODEL_PATH
        ),
    )
    parser.add_argument(
        "--holdout-fraction",
        type=float,
        default=DEFAULT_HOLDOUT_FRACTION,
        help=translator.text(Message.HELP_VALUE_MODEL_HOLDOUT, default=DEFAULT_HOLDOUT_FRACTION),
    )
    parser.add_argument(
        "--followup-value",
        choices=[definition.value for definition in FollowupValueDefinition],
        default=DEFAULT_FOLLOWUP_DEFINITION.value,
        help=translator.text(
            Message.HELP_VALUE_MODEL_FOLLOWUP, default=DEFAULT_FOLLOWUP_DEFINITION.value
        ),
    )
    parser.add_argument(
        "--ridge-alpha",
        type=float,
        default=DEFAULT_RIDGE_ALPHA,
        help=translator.text(Message.HELP_VALUE_MODEL_RIDGE_ALPHA, default=DEFAULT_RIDGE_ALPHA),
    )
    parser.add_argument(
        "--logistic-l2",
        type=float,
        default=DEFAULT_LOGISTIC_L2,
        help=translator.text(Message.HELP_VALUE_MODEL_LOGISTIC_L2, default=DEFAULT_LOGISTIC_L2),
    )
    parser.add_argument(
        "--travel-weight",
        type=float,
        default=DEFAULT_TRAVEL_WEIGHT,
        help=translator.text(Message.HELP_VALUE_MODEL_TRAVEL_WEIGHT, default=DEFAULT_TRAVEL_WEIGHT),
    )
    parser.add_argument(
        "--kill-weight",
        type=float,
        default=DEFAULT_KILL_WEIGHT,
        help=translator.text(Message.HELP_VALUE_MODEL_KILL_WEIGHT, default=DEFAULT_KILL_WEIGHT),
    )
    parser.add_argument(
        "--stuck-weight",
        type=float,
        default=DEFAULT_STUCK_WEIGHT,
        help=translator.text(Message.HELP_VALUE_MODEL_STUCK_WEIGHT, default=DEFAULT_STUCK_WEIGHT),
    )
    parser.add_argument(
        "--followup-weight",
        type=float,
        default=DEFAULT_FOLLOWUP_WEIGHT,
        help=translator.text(
            Message.HELP_VALUE_MODEL_FOLLOWUP_WEIGHT, default=DEFAULT_FOLLOWUP_WEIGHT
        ),
    )
    parser.add_argument(
        "--telemetry-database",
        default=DEFAULT_TELEMETRY_DATABASE_PATH,
        help=translator.text(
            Message.HELP_VALUE_MODEL_TELEMETRY_DATABASE, default=DEFAULT_TELEMETRY_DATABASE_PATH
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Train, benchmark, and export the farming value models without a running client."""

    translator = Translator.from_environment()
    args = build_parser(translator).parse_args(argv)
    config = TrainingConfig(
        dataset_directory=Path(args.dataset),
        output_directory=Path(args.output),
        holdout_fraction=args.holdout_fraction,
        ridge_alpha=args.ridge_alpha,
        logistic_l2=args.logistic_l2,
        followup_definition=FollowupValueDefinition(args.followup_value),
        cost_weights=ExpectedCostWeights(
            travel=args.travel_weight,
            kill=args.kill_weight,
            stuck=args.stuck_weight,
            followup=args.followup_weight,
        ),
        telemetry_database=Path(args.telemetry_database),
        repository_root=Path(),
    )
    try:
        report = train_farming_value_models(config)
    except DatasetError as error:
        print(
            translator.text(_DATASET_ERROR_MESSAGES[error.code], path=error.detail),
            file=sys.stderr,
        )
        return ExitCode.VALUE_MODEL_FAILURE
    except ExportError as error:
        print(
            translator.text(_EXPORT_ERROR_MESSAGES[error.code], reason=error.detail),
            file=sys.stderr,
        )
        return ExitCode.VALUE_MODEL_FAILURE
    except ValueError as error:
        print(translator.text(Message.VALUE_MODEL_INVALID_OPTION, reason=error), file=sys.stderr)
        return ExitCode.VALUE_MODEL_FAILURE
    _report(report, config.output_directory, translator)
    return ExitCode.SUCCESS


def _report(report: TrainingReport, output_directory: Path, translator: Translator) -> None:
    """Print what the run produced, one complete localized sentence per fact."""

    print(
        translator.text(
            Message.VALUE_MODEL_DATASET_SUMMARY,
            count=report.train_sample_count,
            holdout=report.holdout_sample_count,
            sessions=report.session_count,
            strategy=report.split_strategy.value,
        )
    )
    for artifact in report.artifacts:
        if artifact.trained and artifact.filename is not None:
            print(
                translator.text(
                    Message.VALUE_MODEL_HEAD_EXPORTED,
                    name=artifact.kind.value,
                    path=output_directory / artifact.filename,
                )
            )
        else:
            print(
                translator.text(
                    Message.VALUE_MODEL_HEAD_SKIPPED,
                    name=artifact.kind.value,
                    reason=artifact.reason or "",
                )
            )
    if report.holdout_expected_cost is not None:
        print(
            translator.text(
                Message.VALUE_MODEL_EXPECTED_COST, cost=f"{report.holdout_expected_cost:.3f}"
            )
        )
    print(
        translator.text(
            Message.VALUE_MODEL_TRAINED,
            trained=report.trained_model_count,
            total=len(report.artifacts),
        )
    )
    print(translator.text(Message.VALUE_MODEL_METADATA_WRITTEN, path=report.metadata_path))


if __name__ == "__main__":
    raise SystemExit(main())
