# LLM Bridge troubleshooting: AGY accounts, Gemini Pro and Pi

Start with local inventory, then a live request:

```bash
llm-bridge accounts list
llm-bridge status
llm-bridge test antigravity/gemini-3.8-flash
```

## `no AGY login found` even though AGY shows your email

Update to the current source and reinstall:

```bash
git pull --ff-only
./install.sh
llm-bridge accounts add work
```

AGY 1.3.1 on macOS stores its login in Keychain. Updated account commands read
that store automatically, including Go Keyring's base64 format. If macOS asks
for Keychain access, allow access to your AGY login for the bridge process.

If you set `ANTIGRAVITY_TOKEN_FILE` to a missing or outdated file, unset it before
using automatic detection:

```bash
unset ANTIGRAVITY_TOKEN_FILE
llm-bridge accounts add work
```

On other systems, legacy AGY token files are supported. You can explicitly
select a valid file with `--token-file /absolute/path/to/token.json`. No bridge
command signs you into another Google account: do that in AGY first.

## `no antigravity account named 'account2'`

The account has not been saved in the bridge home used by the server:

```bash
llm-bridge accounts add account2
llm-bridge accounts list
llm-bridge test antigravity@account2/gemini-3.8-flash
```

If `add` fails, fix that error before testing. Use the same `LLM_BRIDGE_HOME` in
both terminals; different homes have different saved accounts and keys.

## `this AGY login is already saved`

The error identifies its saved label. Sign AGY out with `/logout`, reopen it,
sign in to the next Google account, and then run `accounts add` with a new label.
An existing account label cannot be overwritten accidentally; remove it only
when you intend to replace that snapshot.

## Email shows `unknown`

Some old snapshots lack identity metadata. The bridge will not guess which
email belongs to an unrelated token. Set a display label:

```bash
llm-bridge accounts label personal --email alice@example.com --display-name "Alice"
```

New imports preserve available email/name metadata. Labels do not alter login
credentials. Codex and Claude display their current CLI login, not multiple
saved account profiles.

## Gemini 3.1 Pro High returns HTTP 400

Update/reinstall and restart the bridge. Current Pro High requests use the
accepted Pro generation route with the High catalog entry's thinking budget:

```bash
llm-bridge test antigravity@work/gemini-3.1-pro-high
```

The direct High generation ID returned invalid-argument errors on the tested
upstream daily endpoints. See [models and routing](models.md) for the explicit
compatibility mapping. This fix does not guarantee upstream model availability
or quota; an unrelated HTTP 400 still needs investigation.

## HTTP 401, expired token, or login revoked

Sign in again using the affected provider's CLI. For a named AGY snapshot,
remove and re-add that specific account after its new AGY login. Check the
[OAuth refresh settings](commands.md#oauth-refresh-for-saved-agy-accounts) for
saved accounts. The bridge does not refresh a named account through another
account's active CLI login.

A 401 from the bridge itself can mean the client sent the wrong bridge API key.
Provider OAuth tokens and bridge client API keys serve different purposes.

## HTTP 429 / quota exhausted

Google or another provider may limit requests. The account list does not query
quota. The bridge does not automatically rotate Google accounts. You can
explicitly select another saved account you are entitled to use with
`antigravity@other/model` or `accounts use other`. Existing AGY model fallback
behavior is documented in [providers](providers.md).

## Old command does not recognize `accounts`

Your shell is finding an older installation. Reinstall from the updated
checkout, or use its source launcher:

```bash
./bin/llm-bridge accounts list
```

An alias to an old checkout remains old until you update it. `bridge` is an
optional shell alias, while `llm-bridge` and `lbr` are installed commands.

## Pi says `No models available` or `No API key found`

Follow [Pi setup](pi.md). Confirm its custom provider, key environment variable,
selected model, and agent directory. Pi's ordinary `/login` screen does not
create the bridge's custom provider automatically.

## Another device cannot connect over the local network

Bind the bridge with `--host 0.0.0.0`, use the host computer's actual LAN IP in
the client URL, allow the port through its firewall, and provide a bridge key.
Check that both devices share the intended network. See [LAN setup](commands.md#local-network--lan).
