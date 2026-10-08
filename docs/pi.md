# Connect the Pi coding agent to LLM Bridge

Use Pi with Gemini through AGY, or another bridge provider, via the bridge's
OpenAI-compatible endpoint. This custom-provider format was checked against
Pi 1.1.0's installed documentation.

## 1. Start the bridge

In a terminal, after signing AGY in:

```bash
llm-bridge accounts add personal
llm-bridge up
```

Skip `add personal` if it is already saved. See [multiple accounts](commands.md)
for additional Google logins and OAuth refresh setup.

## 2. Create a Pi key

In another terminal:

```bash
llm-bridge keys create pi
```

Copy the printed key and set it for the shell where Pi will run:

```bash
export LLM_BRIDGE_API_KEY="YOUR_BRIDGE_KEY"
```

If a key named `pi` already exists, use your saved key or create a new uniquely
named one. `keys list` shows masked values, not the original key.

## 3. Add a custom provider

Merge this provider into `models.json` in your Pi agent directory (normally
`~/.pi/agent/models.json`). Keep any existing providers:

```json
{
  "providers": {
    "llm-bridge": {
      "baseUrl": "http://127.0.0.1:8000/v1",
      "api": "openai-completions",
      "apiKey": "${LLM_BRIDGE_API_KEY}",
      "models": [
        { "id": "antigravity/gemini-3.8-flash", "name": "Bridge Gemini Flash" },
        { "id": "antigravity/gemini-3.1-pro-high", "name": "Bridge Gemini Pro High" }
      ]
    }
  }
}
```

For an isolated profile, set `PI_CODING_AGENT_DIR` to your chosen directory and
put `models.json` there. Use that same variable every time you launch Pi.
`${LLM_BRIDGE_API_KEY}` in the JSON is Pi's environment interpolation syntax;
Pi reads the exported value when it makes requests.

## 4. Start Pi

```bash
pi --provider llm-bridge --model antigravity/gemini-3.8-flash
```

Inside Pi, `/model` reloads the custom model file and lets you select another
configured model. To pin a saved Google account, use a model ID such as
`antigravity@work/gemini-3.8-flash` in `models.json` and the launch command.

For LAN use, replace `127.0.0.1` with the bridge host's LAN IP and bind the bridge
to the LAN: [local network setup](commands.md#local-network--lan).

## If Pi says no models or no API key

Check the bridge and the selected account first:

```bash
llm-bridge accounts list
llm-bridge test antigravity/gemini-3.8-flash
```

Check that `LLM_BRIDGE_API_KEY` is exported in Pi's terminal, the JSON is valid,
and Pi is reading the intended agent directory. Restart Pi after changing
shell variables. The bridge provider uses its own key; logging into a different
provider through Pi's `/login` does not configure the bridge connection.

YAML errors referring to another skill's `SKILL.md` are a separate configuration
problem. Quote YAML descriptions containing `: `, or use a YAML block scalar;
fix the named skill file, then reload Pi. Do not put API keys into skill files.
