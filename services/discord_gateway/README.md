# Fisher Discord Gateway

The gateway exposes Discord application commands for Twitch channel owners and authorized channel
staff. It never reads ordinary message content. Every management response is ephemeral, and every
mutation is authorized and audited by `game_engine`.

## Discord application setup

1. Create an application and bot in the Discord Developer Portal.
2. Keep the Message Content intent disabled. No privileged gateway intents are required.
3. Invite the application with the `bot` and `applications.commands` scopes. Grant only the
   permissions needed to view and send messages in the management channel.
4. Set `DISCORD_BOT_TOKEN`, `DISCORD_APPLICATION_ID`, and a random `DISCORD_BOT_API_KEY` shared only
   with `game_engine`.
5. Register the backend callback URL from `TWITCH_DISCORD_REDIRECT_URI` in the Twitch application.

Use `COMMAND_SYNC_MODE=guild` with `DEV_GUILD_ID` while developing. Use `global` in production;
global Discord command propagation can take longer.

## Command workflow

- `/fish account link|status|unlink` manages the one-to-one Twitch identity link.
- `/fish setup bind|replace|remove|status` binds one Discord server to one Twitch channel. Binding
  requires Discord Manage Server permission and ownership of the linked Twitch channel.
- `/fish streamelements status|connect|test|disconnect|settings|operations` manages the encrypted
  StreamElements credential, health state, economy settings, and recent provider operations.
- `/fish config show|edit|reset|cooldown` manages versioned game settings.
- `/fish location list|show|create|edit|delete` manages up to 50 fishing locations.
- `/fish reward list|show|add|edit|delete` manages stable-ID weighted rewards. Supported types are
  `fish`, `timeout`, `robbery`, `russian_roulette`, and `nothing`.
- `/fish event list|show|export|create|edit|start|stop|delete` manages immediate or timed channel events; `export` dumps them as JSON.
- `/fish cast recent|show|search|stats|export` shows fishing cast history, filtered search, channel statistics, and raw JSON export.
- `/fish item effect-edit` edits an item's typed effects through structured forms, no raw JSON.
- `/fish item create` runs the step-by-step wizard: pick a template, then fill basic info, rarity,
  mechanics, and effects before reviewing and confirming. Effects are added with the typed builder,
  not raw JSON.
- `/fish item edit` opens the same wizard with the current definition prefilled and a final
  "Save Changes" button; if another administrator saved a newer version first, the wizard offers to
  reload the latest version instead of overwriting it.
- `/fish item export-json` and `/fish item import-json` (Twitch channel owner only) round-trip a raw
  definition file for backup and cross-channel migration; import reviews the JSON with the same
  compatibility validation as the wizard before confirming.
- The effects step runs in a Standard editor (up to 10 effects) by default. An "Advanced mode"
  button raises the cap to 25 and exposes low-level stats (`stat_multiply`, `points_flat_bonus`),
  always behind a warning; imported or legacy items that already overflow the standard editor open
  in advanced mode automatically.

Edit forms capture an entity version. If another administrator changes the same entity first, the
backend rejects the stale form and no data is overwritten. Destructive operations use a
user-bound confirmation control.

## Command module layout

Each domain lives in its own module under `app/commands/` (audit rule: no monolithic
registration file):

- `account.py`, `setup.py`, `config.py`, `locations.py`, `rewards.py`, `events.py`
  (including `placeholders`), `items.py`, `item_drops.py`, `players.py`
  (player / player-modifier / player-stats / player overflow), `casts.py`.
- `shared.py` holds the cross-domain helpers and choice constants; `register.py` is only the
  aggregator that wires the `/fish` tree and cross-group autocompletes.

## Local operation

Copy the required values from the repository `.env.example`, then run:

```bash
docker compose up --build postgres redis game_engine game_worker discord_gateway
```

The service has no published host port. Inside the Compose network it serves:

- `GET /health/live` for process liveness;
- `GET /health/ready` for Discord, Redis, game engine, and command-sync readiness;
- `GET /metrics` for dependency readiness gauges.

## Database migration and rollback

`game_engine` applies Alembic migrations before startup. For a manual deployment:

```bash
PYTHONPATH=services/game_engine alembic -c services/game_engine/alembic.ini upgrade head
```

Rollback only while both gateways are stopped:

```bash
PYTHONPATH=services/game_engine alembic -c services/game_engine/alembic.ini downgrade 20260802_0001
```

The downgrade removes Discord links, guild bindings, idempotency records, and administration audit
data. Back up the database first.

## Troubleshooting

- `DISCORD_LINK_REQUIRED`: run `/fish account link` and finish Twitch authorization.
- `GUILD_BINDING_REQUIRED`: a server manager must run `/fish setup bind`.
- `CONFIG_VERSION_CONFLICT`: reopen the form to load the latest version.
- `ENGINE_UNAVAILABLE`: check both readiness endpoints and Redis/PostgreSQL connectivity.
- `INTEGRATIONS_ENCRYPTION_KEY` must be set separately from `ENCRYPTION_KEY`; it encrypts
  StreamElements credentials and supports versioned rotation through
  `INTEGRATIONS_ENCRYPTION_KEYS`.
- `TWITCH_BOT_SERVICE_KEY` is a separate internal credential used only by `bot_gateway` for
  desired-membership reads and runtime status reports. Production membership uses PostgreSQL with
  `TWITCH_CHANNEL_SOURCE=database`; `BOOTSTRAP_CHANNELS` is transitional only.
- Commands are missing: confirm the invite includes `applications.commands`, then check sync mode,
  application ID, guild ID, and the `commands` readiness field.

Logs are JSON and include request and interaction IDs. Tokens and service API keys are never logged.
