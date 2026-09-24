import inspect

import anthropic
from anthropic.resources.messages import Messages

from src import commentary


class _FakeStream:
    text_stream = iter(["Bonjour", " le monde"])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_stream_commentary_matches_sdk_signature(monkeypatch):
    """Les arguments envoyés doivent être acceptés par Messages.stream() du SDK installé."""
    captured = {}

    class _FakeMessages:
        def stream(self, **kwargs):
            captured.update(kwargs)
            return _FakeStream()

    class _FakeClient:
        def __init__(self, api_key):
            self.messages = _FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", _FakeClient)

    text = "".join(commentary.stream_commentary("sk-test", "claude-haiku-4-5", "prompt"))

    assert text == "Bonjour le monde"
    inspect.signature(Messages.stream).bind(None, **captured)  # TypeError si un argument a disparu du SDK
