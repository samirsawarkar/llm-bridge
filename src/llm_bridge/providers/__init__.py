"""Provider registry and model routing."""
import time

from .anthropic import Anthropic
from .antigravity import Antigravity
from .openai import OpenAI

PROVIDERS = {p.name: p for p in (Antigravity(), Anthropic(), OpenAI())}


class RouteError(ValueError):
    pass


def resolve(model, default_provider=None):
    """model string -> (provider, upstream_model). explicit provider/model > bare prefix > default_provider > error."""
    hint = "use provider/model, e.g. anthropic/claude-sonnet-5 (providers: %s)" % ", ".join(PROVIDERS)
    if not model:
        raise RouteError("model is required; " + hint)
    if "/" in model:
        pname, _, bare = model.partition("/")
        if pname not in PROVIDERS:
            raise RouteError("unknown provider '%s'; %s" % (pname, hint))
        return PROVIDERS[pname], PROVIDERS[pname].upstream_model(bare)
    for p in PROVIDERS.values():
        if model.startswith(p.prefixes):
            return p, p.upstream_model(model)
    if default_provider in PROVIDERS:
        return PROVIDERS[default_provider], PROVIDERS[default_provider].upstream_model(model)
    raise RouteError("cannot route model '%s'; %s" % (model, hint))


def list_models():
    now = int(time.time())
    return [{"id": "%s/%s" % (p.name, m["id"]), "object": "model", "created": now, "owned_by": p.name}
            for p in PROVIDERS.values() if p.auth_status()["ok"] for m in p.catalog]
