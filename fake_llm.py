"""A scripted stand-in for the OpenAI client, so you can run and test the agent loop
without an API key. Each scripted item is what the "model" says on one call."""
from types import SimpleNamespace as NS


def tool_call(call_id: str, name: str, arguments: str):
    return NS(id=call_id, function=NS(name=name, arguments=arguments))


def reply(content=None, tool_calls=None):
    return NS(content=content, tool_calls=tool_calls or None)


class FakeClient:
    """Mimics client.chat.completions.create(...). Records every call in .calls."""

    def __init__(self, script, repeat_last: bool = False):
        self.script = list(script)
        self.repeat_last = repeat_last
        self.calls = []
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kwargs):
        snapshot = {**kwargs, "messages": [dict(m) for m in kwargs["messages"]]}
        self.calls.append(snapshot)
        if not self.script:
            raise AssertionError("The model was called more times than the script allows.")
        message = self.script[0] if (self.repeat_last and len(self.script) == 1) else self.script.pop(0)
        return NS(choices=[NS(message=message)])
