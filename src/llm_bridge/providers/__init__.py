"""Provider registry and model routing."""
import time
from functools import lru_cache

from .. import accounts

from .anthropic import Anthropic
from .antigravity import Antigravity
from .openai import OpenAI

PROVIDERS = {p.name: p for p in (Antigravity(), Anthropic(), OpenAI())}


class RouteError(ValueError):
    pass


@lru_cache(maxsize=128)
def _named_account(name, project_id, created):
    # Limit cached provider objects, not the number of saved accounts.
    p = Antigravity(token_file=accounts.token_file(name), project_id=project_id)
    p.login_hint = "re-add account '%s' after signing in with agy" % name
    return p


def get_provider(name):
    base, marker, account = name.partition("@")
    if base not in PROVIDERS:
        raise RouteError("unknown provider '%s'" % base)
    if marker and base != "antigravity":
        raise RouteError("named accounts are currently supported for antigravity only")
    if base != "antigravity":
        return PROVIDERS[base]
    try:
        data = accounts.load()
        selected = account if marker else data.get("default")
        if selected is None:
            return PROVIDERS[base]
        if selected not in data["accounts"]:
            raise RouteError("no antigravity account named '%s'" % selected)
        item = data["accounts"][selected]
        return _named_account(selected, item["project_id"], item.get("created"))
    except ValueError as e:
        raise RouteError(str(e)) from None


def resolve(model, default_provider=None):
    """model string -> (provider, upstream_model). explicit provider/model > bare prefix > default_provider > error."""
    hint = "use provider/model, e.g. anthropic/claude-sonnet-5 (providers: %s)" % ", ".join(PROVIDERS)
    if not model:
        raise RouteError("model is required; " + hint)
    if "/" in model:
        pname, _, bare = model.partition("/")
        p = get_provider(pname)
        if not bare:
            raise RouteError("model name is required after '/'")
        return p, p.upstream_model(bare)
    for p in PROVIDERS.values():
        if model.startswith(p.prefixes):
            selected = get_provider(p.name)
            return selected, selected.upstream_model(model)
    if default_provider in PROVIDERS:
        p = get_provider(default_provider)
        return p, p.upstream_model(model)
    raise RouteError("cannot route model '%s'; %s" % (model, hint))


def list_models():
    now = int(time.time())
    data = accounts.load()  # One snapshot, so simultaneous removal cannot break listing.
    named = {name: _named_account(name, item["project_id"], item.get("created"))
             for name, item in data["accounts"].items()}
    entries = [(name, named[data["default"]] if name == "antigravity" and data.get("default") else p)
               for name, p in PROVIDERS.items()]
    entries += [("antigravity@" + name, p) for name, p in named.items()]
    return [{"id": "%s/%s" % (name, m["id"]), "object": "model", "created": now, "owned_by": p.name}
            for name, p in entries if p.auth_status()["ok"] for m in p.catalog]
