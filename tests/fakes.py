"""Fake Telegram objects and LLM providers that record everything the bot does."""
from types import SimpleNamespace

import httpx2
import openai
from telegram.error import BadRequest


# ---------- LLM ----------

def _request():
    return httpx2.Request("POST", "https://llm.test/v1/chat/completions")


def status_error(cls, status: int, headers: dict | None = None, message: str = "erro de teste"):
    response = httpx2.Response(status, headers=headers or {}, request=_request())
    return cls(message, response=response, body=None)


def rate_limit(retry_after: str | None = None):
    return status_error(openai.RateLimitError, 429, {"retry-after": retry_after} if retry_after else {})


def timeout_error():
    return openai.APITimeoutError(request=_request())


def completion(content=None, tool_calls=None, finish_reason="stop"):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish_reason)])


def tool_call(name: str, arguments: str, call_id: str = "call_1"):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))


class FakeLLMClient:
    """Each create() pops the next scripted item: an exception is raised, a callable gets the
    request kwargs, anything else is returned as the response."""

    def __init__(self, script=(), transcripts=()):
        self.script = list(script)
        self.transcripts = list(transcripts)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self._transcribe))

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.script.pop(0) if self.script else completion("resposta padrão")
        if isinstance(item, BaseException):
            raise item
        return item(kwargs) if callable(item) else item

    async def _transcribe(self, **kwargs):
        self.calls.append(kwargs)
        item = self.transcripts.pop(0) if self.transcripts else SimpleNamespace(text="")
        if isinstance(item, BaseException):
            raise item
        return item


def provider(name: str, script=(), transcripts=(), max_tokens: int = 500):
    return {"name": name, "client": FakeLLMClient(script, transcripts), "model": f"{name}-model",
            "max_tokens": max_tokens, "params": {}}


# ---------- Telegram ----------

class Recorder:
    """Shared log of everything the bot sent, edited or deleted in one chat."""

    def __init__(self, chat_id: int = 1000):
        self.chat_id = chat_id
        self.events: list[tuple] = []
        self.fail_delete = False
        self.html_rejected = False
        self._next_id = 1

    def new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    @property
    def sent(self) -> list[str]:
        return [e[1] for e in self.events if e[0] == "send"]

    @property
    def visible(self) -> list[str]:
        deleted = {e[2] for e in self.events if e[0] == "delete"}
        return [e[1] for e in self.events if e[0] == "send" and e[3] not in deleted]


class SentMessage:
    def __init__(self, recorder: Recorder, text: str, reply_markup=None):
        self.recorder = recorder
        self.text = text
        self.reply_markup = reply_markup
        self.message_id = recorder.new_id()

    async def delete(self):
        if self.recorder.fail_delete:
            raise BadRequest("Message can't be deleted")
        self.recorder.events.append(("delete", self.text, self.message_id))

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kwargs):
        return await _send(self.recorder, text, reply_markup, parse_mode)


async def _send(recorder: Recorder, text, reply_markup=None, parse_mode=None):
    if len(text) > 4096:
        raise BadRequest("Message is too long")
    if parse_mode == "HTML" and recorder.html_rejected:
        raise BadRequest("Can't parse entities")
    message = SentMessage(recorder, text, reply_markup)
    recorder.events.append(("send", text, reply_markup, message.message_id, parse_mode))
    return message


class FakeFile:
    def __init__(self, data: bytes, fail: bool = False):
        self.data = data
        self.fail = fail

    async def download_as_bytearray(self):
        if self.fail:
            raise OSError("download falhou")
        return bytearray(self.data)


class FakeAttachment:
    def __init__(self, data=b"", file_name=None, mime_type=None, file_size=None, duration=None,
                 file_id="FILE123", fail_download=False):
        self.data = data
        self.file_name = file_name
        self.mime_type = mime_type
        self.file_size = file_size if file_size is not None else len(data)
        self.duration = duration
        self.file_id = file_id
        self.fail_download = fail_download

    async def get_file(self):
        return FakeFile(self.data, self.fail_download)


class FakeIncoming:
    def __init__(self, recorder: Recorder, text=None, caption=None, photo=None, document=None,
                 voice=None, audio=None):
        self.recorder = recorder
        self.text = text
        self.caption = caption
        self.photo = photo or []
        self.document = document
        self.voice = voice
        self.audio = audio

    async def reply_text(self, text, reply_markup=None, parse_mode=None, **kwargs):
        return await _send(self.recorder, text, reply_markup, parse_mode)


def make_update(recorder: Recorder, **message_kwargs):
    return SimpleNamespace(
        message=FakeIncoming(recorder, **message_kwargs),
        effective_chat=SimpleNamespace(id=recorder.chat_id),
        callback_query=None,
    )


class FakeQuery:
    def __init__(self, recorder: Recorder, data: str, message_text: str = "", reply_markup=None,
                 answer_error: Exception | None = None):
        self.recorder = recorder
        self.data = data
        self.answer_error = answer_error
        self.message = SentMessage(recorder, message_text, reply_markup)

    async def answer(self, *args, **kwargs):
        if self.answer_error:
            raise self.answer_error

    async def edit_message_text(self, text, reply_markup=None, **kwargs):
        if text == self.message.text and _same_markup(reply_markup, self.message.reply_markup):
            raise BadRequest("Message is not modified")
        if len(text) > 4096:
            raise BadRequest("Message is too long")
        self.message.text, self.message.reply_markup = text, reply_markup
        self.recorder.events.append(("edit", text, reply_markup))

    async def edit_message_reply_markup(self, reply_markup=None, **kwargs):
        if _same_markup(reply_markup, self.message.reply_markup):
            raise BadRequest("Message is not modified")
        self.message.reply_markup = reply_markup
        self.recorder.events.append(("edit_markup", reply_markup))


def _same_markup(a, b) -> bool:
    if a is None or b is None:
        return a is b
    return a.to_dict() == b.to_dict()


def make_callback_update(query: FakeQuery):
    return SimpleNamespace(message=None, callback_query=query,
                           effective_chat=SimpleNamespace(id=query.recorder.chat_id))


async def _noop(*args, **kwargs):
    return None


CONTEXT = SimpleNamespace(bot=SimpleNamespace(send_chat_action=_noop))
