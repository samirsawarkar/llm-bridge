# Models & routing

Model ids are `provider/model`. `GET /v1/models` and `llm-bridge models` list them; a model is listed only when its provider is authenticated. Antigravity and Anthropic catalogs are static seeds; the OpenAI catalog is fetched from the Codex backend for your account — `llm-bridge test <model>` is the real probe.

## Routing precedence

1. `provider/model` — explicit; unknown provider → 400.
2. Bare name matching a provider prefix: `claude-*` → anthropic; `gpt-*`, `o1*`, `o3*`, `o4*`, `codex*` → openai; `gemini-*` → antigravity. Prefix sets are disjoint (tested).
3. `default_provider` from `~/.llm-bridge/config.json` or `LLM_BRIDGE_DEFAULT_PROVIDER`.
4. 400 `model_not_found`.

No substring guessing. `gpt-oss-120b-medium` lives on antigravity and must be written `antigravity/gpt-oss-120b-medium`.

## Aliases (resolved inside the provider)

| Provider | Alias | Upstream |
|---|---|---|
| antigravity | `gemini-3.8-flash`, `-high`, `-medium`, `-low` | `gemini-3.8-flash-tiered` |
| antigravity | (Gemini 3.7 Flash not offered: AGY lists it, but Cloud Code returns 404 on every endpoint as of 2026-10-10) | — |
| antigravity | `gemini-3.6-flash` | `gemini-3.6-flash-high` |
| antigravity | `gemini-3.1-pro` | `gemini-3.1-pro-high` |
| antigravity | `gemini-pro` / `gemini-flash` | `gemini-2.5-pro` / `gemini-2.5-flash` |
| antigravity | `claude-sonnet` / `claude-opus` | `claude-sonnet-4-6` / `claude-opus-4-6-thinking` |
| anthropic | `claude-opus` / `claude-sonnet` / `claude-haiku` | `claude-opus-5` / `claude-sonnet-5` / `claude-haiku-4-5-20251001` |

## Named Google accounts

`antigravity@work/gemini-3.8-flash` selects the saved `work` login for a request.
Plain `antigravity/model` and bare Gemini names use the selected default. Use
`llm-bridge accounts list` to see saved labels/emails, and `accounts use work`
to change the default. The authenticated API model list includes named accounts.
See [account commands](commands.md#save-multiple-gemini--google-antigravity-accounts).

## Gemini 3.1 Pro High generation compatibility

Google's tested model catalog lists `gemini-3.1-pro-high` with a 10001-token
thinking budget, while its Pro tier generation route is `gemini-3.1-pro-low`.
The direct High ID returned invalid-argument errors on the daily generation
endpoints. LLM Bridge sends High requests through `gemini-3.1-pro-low` with
`thinkingConfig.thinkingBudget=10001` and `includeThoughts=true`. Google controls
actual thinking usage; this mapping does not prove the provider honors every
setting. The explicit Low ID remains available too.

The mapping passed a live request on 2026-10-08. Model access and backend behavior
can change. A successful local account listing does not validate generation;
use `llm-bridge test antigravity@work/gemini-3.1-pro-high` to check your account.
