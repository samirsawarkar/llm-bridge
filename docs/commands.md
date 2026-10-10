# LLM Bridge CLI commands: accounts, API keys, models and local network

Use `llm-bridge --help` for the installed command reference. `lbr` is the installed
short command. To use the name `bridge` in your current shell:

```bash
alias bridge=llm-bridge
bridge accounts list
```

From a source checkout, replace `llm-bridge` with `./bin/llm-bridge` if you have
not installed it. Keep the server running in one terminal and use another for
management commands. [Install first](quickstart.md) if needed.

## Save multiple Gemini / Google Antigravity accounts

1. Run `agy` and sign in to the first Google account. Exit AGY.
2. Save that login:

```bash
llm-bridge accounts add personal
```

3. Open AGY, run `/logout` inside it, reopen AGY, and sign in to the next account.
   Exit AGY, then save it under a new name:

```bash
llm-bridge accounts add work
```

4. Repeat for additional accounts:

```bash
llm-bridge accounts add account3
llm-bridge accounts list
llm-bridge accounts use work
llm-bridge test antigravity@work/gemini-3.8-flash
llm-bridge test antigravity@work/gemini-3.1-pro-high
```

Sign in to each different account before its `add` command. Each add reads the
current login again, prints the email it saved, and keeps an independent copy.
On macOS, AGY 1.3.1's Keychain login is detected automatically; older token files
remain supported. Named accounts have no fixed count cap. Account names use
1–64 letters, digits, underscores or hyphens and must start with a letter/digit.

`accounts use current-cli` goes back to AGY's live login (refreshed by AGY itself, so it never goes stale; on Windows and macOS 1.3 it is read from Credential Manager / Keychain).
`accounts use work` selects the default for `antigravity/model` and bare Gemini
names. `antigravity@personal/model` explicitly selects another saved login for
that request. Account additions and default changes do not require a restart.

## Rotate accounts when one runs out of quota

AGY holds one login at a time. `accounts switch` signs AGY itself in as a saved
account (it writes the login to AGY's own store, where AGY refreshes it, so no
OAuth client settings are needed). The outgoing login is saved first, and a
login that was never saved is added automatically, so switching never loses one.

```bash
llm-bridge accounts switch personal          # AGY (and the bridge) now use 'personal'
llm-bridge accounts rotate --reset-in "Resets in 155h37m38s"   # mark the active one, move to the next
llm-bridge accounts list                     # shows "out of quota until ..." per account
```

With the default `current-cli`, this happens automatically: when Google answers
a request with a quota error (429), the bridge marks the active account until
its reset time and switches AGY to the next saved account that is not out of
quota, then retries once. AES does the same when `agy` itself reports
"Individual quota reached". When every saved account is out, the error names
the first reset time. Save every Google account once (`accounts add`) so the
rotation has somewhere to go.

## See account emails and names

```bash
llm-bridge accounts list
```

Illustrative output (these are example identities):

```text
Provider  Account      Email              Name   Default  Status         Source
AGY       personal     alice@example.com  Alice  *        authenticated  saved
AGY       work         bob@example.com    Bob             authenticated  saved
Codex     current-cli  alice@example.com  Alice  *        authenticated  CLI
Claude    current-cli  alice@example.com  Alice  *        authenticated  CLI
```

`*` means the default for that provider. Saved AGY accounts and the matching
active AGY login appear once. Codex and Claude show their active CLI login;
multiple named saved logins for those two providers are not implemented.

`authenticated` means local credentials exist and appear refreshable. It does
not prove provider access or available quota. Listing does not refresh tokens
or call provider APIs. Use `llm-bridge test provider/model` for a live check.

If older credentials have no identity metadata, the email shows `unknown`:

```bash
llm-bridge accounts label personal --email alice@example.com --display-name "Alice"
llm-bridge accounts add work --email bob@example.com --display-name "Bob"
```

Labels affect display metadata only. They do not change who a token logs in as.

## Import a token file or assigned Google project

```bash
llm-bridge accounts add work --token-file /absolute/path/to/agy-token.json --project-id YOUR_GOOGLE_PROJECT_ID
```

`--token-file` selects that file instead of automatic detection.
`ANTIGRAVITY_TOKEN_FILE` overrides the automatically detected CLI store too.
`--project-id` selects the Google project assigned to that account; otherwise
an imported project is used, then `ANTIGRAVITY_PROJECT_ID` / the existing default.
Supply the correct project if your accounts use different assigned projects.

## OAuth refresh for saved AGY accounts

Private account snapshots refresh directly with Google's OAuth endpoint. Set
the OAuth client settings used by your installed AGY CLI in the terminal that
starts the bridge:

```bash
export ANTIGRAVITY_CLIENT_ID="YOUR_AGY_OAUTH_CLIENT_ID"
export ANTIGRAVITY_CLIENT_SECRET="YOUR_AGY_OAUTH_CLIENT_SECRET"
llm-bridge up
```

The public repository does not bundle OAuth client credentials. These settings
identify the OAuth application; they are separate from your bridge API keys.
Use the client that issued the saved refresh token. Named accounts never refresh
through a different account's active AGY session. An access token may work until
it expires even when refresh settings are missing. Revoked tokens require a new
AGY login and a new snapshot.

## Remove or replace a saved account

```bash
llm-bridge accounts remove work
# Sign AGY in to the replacement account before this command:
llm-bridge accounts add work
```

Removing an account deletes its bridge snapshot. It does not sign out AGY or
revoke Google access. Removing the default chooses the next saved account.

## Start and inspect the gateway

```bash
llm-bridge up
llm-bridge up --host 127.0.0.1 --port 8000
llm-bridge status
llm-bridge models
llm-bridge test antigravity/gemini-3.8-flash
llm-bridge test antigravity@work/gemini-3.1-pro-high --prompt "Reply with exactly: bridge OK"
llm-bridge --version
llm-bridge accounts --help
llm-bridge accounts add --help
```

`up` runs in the foreground. Stop it with `Ctrl+C`; restart it after code updates.
`models` reports provider catalog entries and local credential status. Model
catalog entries are not a guarantee of access. AGY Pro High uses the supported
Pro route with High thinking settings; see [model routing](models.md).

## API keys

```bash
llm-bridge keys create pi
llm-bridge keys list
llm-bridge keys revoke pi
```

`create` prints a new key once. Save it privately; `list` shows masked values.
Use a different name for each client. Keys authenticate clients to the local
bridge; provider OAuth credentials stay in their credential stores.

Use your key from an API client:

```bash
export LLM_BRIDGE_API_KEY="YOUR_BRIDGE_KEY"
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Authorization: Bearer $LLM_BRIDGE_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"antigravity@work/gemini-3.8-flash","messages":[{"role":"user","content":"Say hello"}]}'
```

## Client connections

```bash
llm-bridge connect hermes --model antigravity/gemini-3.8-flash
llm-bridge connect openclaw --model antigravity@work/gemini-3.8-flash
```

These commands update the named client's configuration. Pi uses a custom
provider configuration: [Pi setup](pi.md). Other OpenAI-compatible clients use
base URL `http://127.0.0.1:8000/v1`, a bridge key, and a listed model ID.

## Local network / LAN

On the computer hosting the bridge:

```bash
llm-bridge up --host 0.0.0.0 --port 8000
```

On another device on the same trusted network, use
`http://YOUR_BRIDGE_COMPUTER_IP:8000/v1` and a bridge API key. Do not use
`0.0.0.0` as the client URL. Keep the host awake and connected to the internet;
model inference uses provider cloud services. The built-in server uses HTTP,
so use a trusted LAN or put a secure tunnel/TLS proxy in front of it. It is not
configured for public internet exposure.

## Background service

```bash
llm-bridge service install
llm-bridge service status
llm-bridge service stop
llm-bridge service start
llm-bridge service restart
llm-bridge service uninstall
```

Uses launchd on macOS or systemd on Linux. The current service installer does
not copy arbitrary shell environment variables into its service definition.
For custom storage or OAuth settings, configure the service environment
explicitly or run `up` in the configured terminal. `up` alone does not install
a background service.

## Data directory and environment

```bash
export LLM_BRIDGE_HOME="/absolute/path/to/bridge-data"
llm-bridge accounts list
llm-bridge up
```

Use the same home for the server and every management terminal. The default is
`~/.llm-bridge`. Saved tokens and the registry use private files; never commit
them to Git. `accounts/` contains snapshots, `accounts.json` contains labels and
the default, `keys.json` contains bridge keys, and `config.json` stores options.

| Variable | Purpose |
|---|---|
| `LLM_BRIDGE_HOME` | Bridge accounts, keys and config directory |
| `LLM_BRIDGE_HOST` / `LLM_BRIDGE_PORT` | Bind address and port |
| `LLM_BRIDGE_DEFAULT_PROVIDER` | Fallback for model names without a known prefix |
| `ANTIGRAVITY_TOKEN_FILE` | Explicit AGY CLI credential file |
| `ANTIGRAVITY_PROJECT_ID` | Default Google project |
| `ANTIGRAVITY_CLIENT_ID` / `ANTIGRAVITY_CLIENT_SECRET` | AGY OAuth refresh client settings |
| `CODEX_HOME` | Codex CLI auth directory |

Command flags override host/port environment/config values. See
[troubleshooting](troubleshooting.md) for common errors.
