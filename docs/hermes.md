# Hermes Agent

[Hermes](https://github.com/nousresearch/hermes-agent) talks to LLM Bridge as a custom OpenAI provider.

```bash
llm-bridge connect hermes --model anthropic/claude-sonnet-5
hermes chat -q "Say hello!"
```

`connect` writes `~/.hermes/config.yaml` (backing up the existing file):

```yaml
model:
  provider: custom
  base_url: http://127.0.0.1:8000/v1
  api_key: sk-lb-…        # your bridge key
  default: anthropic/claude-sonnet-5
```

Any `provider/model` from `llm-bridge models` works as `default`. Re-run `connect --model …` to switch, or edit the file. Uses PyYAML when installed, otherwise a text replacement of the `model:` block.
