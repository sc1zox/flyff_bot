"""Unit tests for complete localization bundles."""

from flyff_bot.i18n import Language, Message, Translator


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
            )


def test_languages_return_different_application_descriptions() -> None:
    german = Translator(Language.GERMAN).text(Message.APP_DESCRIPTION)
    english = Translator(Language.ENGLISH).text(Message.APP_DESCRIPTION)

    assert german != english
