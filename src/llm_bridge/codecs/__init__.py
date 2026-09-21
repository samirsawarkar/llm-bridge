"""Inbound API formats. Each module: fmt, decode, encode_stream, encode_final, encode_error."""
from . import anthropic, openai_chat, responses

_BY_PATH = {"/v1/chat/completions": openai_chat, "/chat/completions": openai_chat,
            "/v1/messages": anthropic, "/messages": anthropic,
            "/v1/responses": responses, "/responses": responses}


def by_path(path):
    return _BY_PATH.get(path)
