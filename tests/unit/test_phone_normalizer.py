import pytest

from memnex.identity.normalizer import infer_type, normalize


@pytest.mark.parametrize(
    "channel,raw,expected",
    [
        ("voice", "+91 92410 63955", "919241063955"),
        ("voice", "092-4106-3955", "919241063955"),
        ("voice", "9241063955", "919241063955"),
        ("whatsapp", "wa:919241063955", "919241063955"),
        ("whatsapp", "919241063955", "919241063955"),
        ("email", "Vikram.Dev@Example.com", "vikram.dev@example.com"),
        ("email", "  TEST@EXAMPLE.COM  ", "test@example.com"),
        ("web", "sess_abc123", "sess_abc123"),
        ("app", "user_789", "user_789"),
    ],
)
def test_normalize_examples(channel, raw, expected):
    assert normalize(channel, raw) == expected


def test_normalize_rejects_empty():
    with pytest.raises(ValueError):
        normalize("voice", "")


def test_infer_type():
    assert infer_type("voice", "+919241063955") == "phone"
    assert infer_type("whatsapp", "919241063955") == "whatsapp_id"
    assert infer_type("email", "x@y.com") == "email"
    assert infer_type("web", "abc") == "session_cookie"
    assert infer_type("app", "user_1") == "app_user_id"


def test_normalize_is_idempotent():
    first = normalize("voice", "+91 92410 63955")
    again = normalize("voice", first)
    assert first == again
