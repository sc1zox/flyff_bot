"""Unit tests for complete localization bundles."""

import pytest

from flyff_bot.features.automation.controllers import EngagementBreakReason
from flyff_bot.i18n import Language, Message, Translator
from flyff_bot.ui.main_window import _engagement_break_message


def test_each_language_contains_every_message() -> None:
    for language in Language:
        translator = Translator(language)
        for message in Message:
            assert translator.text(
                message,
                default="x",
                process="x",
                reason="x",
                index=0,
                handle=0,
                title="x",
                seconds="0",
                mob_count=0,
                count=0,
                class_name="x",
                confidence="0",
                x=0,
                y=0,
                width=0,
                height=0,
                timestamp="x",
                item_name="x",
                dataset="x",
                code="x",
                path="x",
                model="x",
                labels="x",
                status="x",
                current=0,
                required=0,
                item="x",
                name="x",
                hp="100.0",
                mp="100.0",
                fp="100.0",
                score="0.00",
                threshold="0.00",
                pixels=0,
                percentage="0.0",
                text="x",
                stored="0.0",
                live="0.0",
                region="x",
                world="x",
                zones=0,
                obstacles=0,
                blocks=0,
                monsters="x",
                monster="x",
                capacity=0,
                z=0,
            )


def test_languages_return_different_application_descriptions() -> None:
    german = Translator(Language.GERMAN).text(Message.APP_DESCRIPTION)
    english = Translator(Language.ENGLISH).text(Message.APP_DESCRIPTION)

    assert german != english


@pytest.mark.parametrize("reason", list(EngagementBreakReason))
def test_every_engagement_break_reason_has_a_distinct_localized_sentence(
    reason: EngagementBreakReason,
) -> None:
    messages = {
        language: Translator(language).text(_engagement_break_message(reason))
        for language in Language
    }

    assert all(text.strip() for text in messages.values())
    assert len(set(messages.values())) == len(Language)
    assert all(
        text != Translator(language).text(Message.UI_TARGET_DEBUG_BREAK_NONE)
        for language, text in messages.items()
    )
