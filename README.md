# Fisher Bot

Rebuilt from scratch version of this [bot](https://github.com/andreysiniy/fisher-bot)

Fisher Bot is a multi-service Twitch fishing game with Discord administration. The game engine is
the single source of truth for rules, rewards, inventory, events, economy, permissions, and cast
history. Twitch and Discord gateways are thin interfaces that call the engine over authenticated
HTTP APIs.

## What is included

- Fishing casts with weighted rewards, mass, XP, levels, cooldowns, events, robbery, and Russian
  roulette scenarios.
- Typed item definitions, effects, equipment, inventory capacity, overflow storage, item drops,
  durability, and player modifiers.
- StreamElements points integration for buying and selling fish, including idempotent operations,
  provider health checks, caps, reconciliation, and operation history.
- Twitch channel membership reconciliation and role-aware administration.
- Discord application commands with authenticated channel binding, structured forms, previews,
  version-conflict handling, pagination, and readable views.
- Durable cast journal with searchable outcomes, reward details, modifier snapshots, and item drops.
- A deterministic StreamElements stub and a real-transport Twitch E2E runner for race, resilience,
  permissions, inventory, channel, and provider-fault scenarios.

## Architecture

```text
Twitch chat ──> bot_gateway ──authenticated HTTP──> game_engine ──> PostgreSQL
                                                          │             │
                                                          └────────────> Redis
Discord ─────> discord_gateway ──authenticated HTTP───────┘

StreamElements <── encrypted provider client / outbox worker <── game_engine
```

The backend owns all game calculations and authorization. Gateways parse commands, submit stable
request identifiers, and render backend responses; they must not reimplement game rules.

## Services

| Component | Purpose | Local endpoint or port |
| --- | --- | --- |
| `services/game_engine` | FastAPI API, domain logic, persistence, migrations, and internal workers | `http://localhost:8000` |
| `services/bot_gateway` | TwitchIO chat bot and Twitch-side command rendering | no public HTTP port |
| `services/discord_gateway` | Discord slash commands and administration UI | internal Compose port `8081` |
| `services/streamelements_stub` | Deterministic provider fake for E2E runs | internal port `8080` (E2E profile) |
| `services/twitch_e2e_runner` | Real Twitch transport and race-test orchestration | `http://localhost:8090` (E2E profile) |
| `services/frontend` | Prototype web client | `http://localhost` |
| PostgreSQL | Durable game state, catalog, journal, and audit data | `localhost:5432` |
| Redis | Cooldowns, locks, queues, and cache | `localhost:6379` |

## Prerequisites

For the recommended setup install:

- Docker Desktop with Docker Compose v2;
- Git;
- Python 3.10 or newer only if you want to run tests outside containers.

The development Compose file builds all application services. The production Compose file adds
health-gated startup, stricter required-variable checks, and container security defaults.

## Quick start with Docker

1. Create a local environment file. On PowerShell:

   ```powershell
   Copy-Item .env.example .env
   ```

   On a POSIX shell:

   ```bash
   cp .env.example .env
   ```

2. Replace every `replace_...` value in `.env`. Use separate random values for database,
   application, service, and integration encryption keys. Never commit `.env`.

3. Build and start the development stack:

   ```bash
   docker compose up -d --build
   ```

4. Check the containers and backend readiness:

   ```bash
   docker compose ps
   curl http://localhost:8000/health/live
   curl http://localhost:8000/health/ready
   ```

   PowerShell equivalent:

   ```powershell
   Invoke-WebRequest http://localhost:8000/health/live
   Invoke-WebRequest http://localhost:8000/health/ready
   ```

5. Open the API documentation at <http://localhost:8000/docs> or
   <http://localhost:8000/redoc>.

Useful operational commands:

```bash
docker compose logs -f game_engine
docker compose logs -f bot_gateway
docker compose logs -f discord_gateway
docker compose restart game_engine bot_gateway discord_gateway
docker compose down
```

`docker compose down` keeps named database volumes. `docker compose down -v` permanently deletes
the local PostgreSQL and Redis volumes; use it only when you intentionally want a clean local
database.

### Production Compose

After filling all required production variables, start the hardened stack with:

```bash
docker compose -f docker-compose.prod.yml --env-file .env up -d --build
```

Do not use production credentials or a personal channel for local tests. Back up PostgreSQL before
any destructive operation.

## Configuration and secrets

`.env.example` is the complete template for the regular stack. Important groups are:

- `DB_*`, `DATABASE_URL`, and `REDIS_URL` — PostgreSQL and Redis connection settings;
- `SECRET_KEY` and `ENCRYPTION_KEY` — application signing/encryption values;
- `INTEGRATIONS_ENCRYPTION_KEY`, `INTEGRATIONS_ENCRYPTION_KEYS`, and the active key version —
  versioned encryption for stored provider credentials;
- `BOT_API_KEY`, `DISCORD_BOT_API_KEY`, and `TWITCH_BOT_SERVICE_KEY` — distinct internal service
  credentials;
- `API_TWITCH_CLIENT_ID` and `API_TWITCH_CLIENT_SECRET` — engine OAuth application credentials;
- `TWITCH_CLIENT_ID`, `TWITCH_TOKEN`, and `BOT_NICK` — the Twitch chat bot identity;
- `DISCORD_BOT_TOKEN`, `DISCORD_APPLICATION_ID`, `COMMAND_SYNC_MODE`, and `DEV_GUILD_ID` — the
  Discord application identity and command registration mode;
- `TWITCH_CHANNEL_SOURCE`, `TWITCH_CHANNEL_RECONCILE_SECONDS`, and optional
  `BOOTSTRAP_CHANNELS` — channel membership discovery and reconciliation;
- `STREAMELEMENTS_API_BASE_URL` — the provider API endpoint. The local E2E profile overrides it
  with the in-network stub.

Generate secrets with a password manager or a cryptographically secure generator. A Fernet key
must be generated in the format expected by the `cryptography` library. Do not paste access tokens,
JWTs, refresh tokens, or API keys into source files, test fixtures, README examples, logs, or issue
reports.

### Twitch credentials

Create a Twitch developer application for the engine and a separate bot identity for chat. The bot
account must have an OAuth access token with the scopes required by the commands it executes. Set
the bot login in `BOT_NICK`, the client ID in `TWITCH_CLIENT_ID`, and the token (including the
`oauth:` prefix used by TwitchIO) in `TWITCH_TOKEN`.

Production channel membership is read from the database. `BOOTSTRAP_CHANNELS` is a transitional
emergency fallback; prefer Discord setup and the membership reconciler for normal operation.

### Discord credentials

Create an application and bot in the Discord Developer Portal, then invite it with the `bot` and
`applications.commands` scopes. Message Content intent is not required. Set
`DISCORD_BOT_TOKEN` and `DISCORD_APPLICATION_ID`. During development use
`COMMAND_SYNC_MODE=guild` and set `DEV_GUILD_ID`; use `global` for production (global command
propagation can take longer).

The Discord gateway shares `DISCORD_BOT_API_KEY` with the engine. Keep it different from
`BOT_API_KEY` and `TWITCH_BOT_SERVICE_KEY`.

### StreamElements credentials

StreamElements is connected per Twitch channel through the Discord administration flow. The JWT is
submitted to the backend and stored encrypted; it is not a repository or Docker environment value.
The integration encryption key must be configured before connecting an account. Use the
`/fish streamelements status`, `connect`, `test`, `settings`, and `operations` commands to inspect
the connection and economy state.

## Database and migrations

The `game_engine` container runs `alembic upgrade head` before starting Uvicorn. For manual checks:

```bash
docker compose exec game_engine alembic current
docker compose exec game_engine alembic upgrade head
docker compose exec game_engine alembic check
```

Alembic is the supported schema migration mechanism. Do not use `Base.metadata.create_all()` for a
deployment. PostgreSQL is the durable source of truth; Redis must not be the only storage for
deadlines or irreversible operations.

## Discord administration

After inviting the application, complete the account and server setup flow:

1. Run `/fish account link` and finish Twitch authorization.
2. Run `/fish setup bind` as the linked Twitch channel owner.
3. Use `/fish help` to see commands available to the bound channel.

The main command groups are:

- `/fish account` — link, status, and unlink a Twitch identity;
- `/fish setup` — bind, replace, remove, and inspect a Discord-server channel binding;
- `/fish config` — show, edit, reset, and configure fishing cooldowns;
- `/fish location` — manage fishing locations;
- `/fish reward` — list, inspect, create, edit, delete, and import legacy rewards;
- `/fish event` — create, edit, start, stop, inspect, export, and delete channel events;
- `/fish item` — create, edit, archive, list, inspect, and build typed item effects;
- `/fish item-drop` — configure location item drops;
- `/fish player` — inspect inventory, grant/revoke items, manage overflow, and manage modifiers;
- `/fish cast` — browse recent casts, search, inspect one cast, view statistics, and export JSON;
- `/fish streamelements` — connect and operate the StreamElements economy integration.

Mutations use drafts, validation, readable previews, explicit confirmation, and backend version
checks. Administrative responses are ephemeral by default. Raw JSON is reserved for explicit
import/export/debug operations.

## Twitch chat commands

The Twitch gateway currently exposes these command families:

| Command | Purpose |
| --- | --- |
| `!fish` | Process one fishing cast |
| `!fishstats [viewer]` | Show a viewer's statistics |
| `!fishtop [alltime\|catches\|level]` | Show a leaderboard |
| `!fishtravel [location]` | Travel to a fishing location |
| `!fishbag [viewer] [slot]` | Show inventory, or readable item stats for a slot |
| `!fishtrash <slot>` | Remove an item from the viewer's inventory |
| `!fishequip <slot>` | Equip or unequip an item according to the backend rules |
| `!fishbuy <kg\|all>` | Buy fish with StreamElements points |
| `!fishsell <kg\|all>` | Sell fish for StreamElements points |
| `!fishrate` | Show buy and sell rates |
| `!fishmods` | List channel moderators and roles |
| `!fishmodadd`, `!fishmoddel` | Manage channel editor/moderator roles |
| `!fishcd` | Inspect or administer fishing cooldowns |
| `!fishevent` | List or toggle channel events |
| `!fisheconomy` | Inspect or toggle economy, buy, and sell switches |

Exact argument validation and permission checks are performed by the engine. Twitch command replies
are intentionally short and do not expose provider JSON, secrets, or internal operation details.

## E2E runner and StreamElements stub

The E2E services are disabled unless the `e2e` Compose profile is selected. Copy the local-only
template first:

```bash
cp .env.e2e.example .env.e2e
```

On PowerShell:

```powershell
Copy-Item .env.e2e.example .env.e2e
```

Fill `.env.e2e` with dedicated Twitch test identities and keep it uncommitted. Compose reads the
base settings from `.env` and the E2E overrides from `.env.e2e` when both files are supplied:

```bash
docker compose --env-file .env --env-file .env.e2e --profile e2e build \
  streamelements_stub twitch_e2e_runner
docker compose --env-file .env --env-file .env.e2e --profile e2e up -d \
  postgres redis game_engine streamelements_stub twitch_e2e_runner
```

The default E2E mode uses the deterministic StreamElements stub while exercising the real engine
and Twitch transport path. Set `TWITCH_E2E_TRANSPORT=disabled` for a control-plane smoke run that
does not connect to Twitch. Use `TWITCH_E2E_MODE=real` only with an explicitly authorized dedicated
test channel and four dedicated actor accounts.

Check the runner and execute a scenario:

```bash
curl http://localhost:8090/health/live
curl http://localhost:8090/health/ready
curl -X POST http://localhost:8090/internal/e2e/run/smoke \
  -H "X-E2E-Key: <TWITCH_E2E_RUNNER_API_KEY>"
```

The runner also exposes suite and scenario endpoints implemented in
`services/twitch_e2e_runner/main.py`. The API key is optional only when the local configuration
leaves it empty; use a key for any shared environment. E2E result history is kept in the runner's
local SQLite file and access/refresh tokens are redacted from results.

## Tests and quality checks

Run fast checks locally in service-specific environments because production requirements are pinned
independently:

```bash
python -m compileall -q services/game_engine services/bot_gateway \
  services/discord_gateway services/twitch_e2e_runner tests
ruff check services/game_engine services/bot_gateway \
  services/discord_gateway services/twitch_e2e_runner tests
pytest -q tests/unit
pytest -q tests/discord
```

Integration tests require PostgreSQL and Redis. Point them at the local test stack, never at a
personal or production database:

```bash
docker compose up -d postgres redis
pytest -q -m integration tests/integration
```

The E2E runner is complementary to unit and integration tests: it validates the real gateway path,
Twitch timing, authorization boundaries, provider failures, and cross-request races. A scenario
marked `skipped` means its fixture or lifecycle control is not enabled; it is not the same as a
failed assertion.

## Repository layout

```text
services/
  game_engine/          FastAPI backend, domain, services, repositories, migrations
  bot_gateway/          TwitchIO bot and chat command modules
  discord_gateway/      Discord commands, forms, presentation, and API client
  streamelements_stub/  deterministic provider fake for E2E
  twitch_e2e_runner/    real-transport E2E scenarios and assertions
  frontend/             prototype client (kept separate from backend work)
tests/
  unit/                 fast isolated tests
  integration/          PostgreSQL/Redis-backed tests
  discord/              Discord UI and command contract tests
  test_payloads/        versioned API fixtures
docker-compose.yml       development stack
docker-compose.prod.yml  hardened production stack
.env.example             safe configuration template
.env.e2e.example         safe E2E configuration template
```

## Troubleshooting

**The engine is unhealthy.** Inspect `docker compose logs game_engine`, verify `DB_*`,
`DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, and the integration encryption key, then check the
Alembic revision with `docker compose exec game_engine alembic current`.

**The Twitch bot does not answer.** Confirm `TWITCH_TOKEN` includes the `oauth:` prefix, the bot
login and client ID match, the channel is present in the database membership table, and
`/health/ready` reports the bot dependencies as healthy. Check `docker compose logs -f bot_gateway`.

**Discord commands are missing.** Confirm the invite included `applications.commands`, verify
`DISCORD_APPLICATION_ID`, and use `COMMAND_SYNC_MODE=guild` with the correct `DEV_GUILD_ID` while
developing. Global command registration may take time to propagate.

**A Discord mutation is denied.** Link the Twitch identity, bind the Discord server to the channel,
and use an account with the operation-specific owner/editor/moderator role. Backend authorization
is authoritative even when Discord permissions look sufficient.

**The StreamElements market is unavailable.** Run `/fish streamelements status` and `test`, verify
the encrypted integration key and provider base URL, and inspect engine/worker logs. For E2E, the
provider URL inside Compose must be `http://streamelements_stub:8080`, not `localhost`.

**A local database must be reset.** Stop the stack, confirm the data is disposable, then run
`docker compose down -v` and start it again. This deletes all local game state, inventory, links,
and cached data.

## Security and contribution notes

- Never commit `.env`, `.env.e2e`, tokens, JWTs, refresh tokens, API keys, or private test data.
- Keep internal service credentials distinct and rotate integration encryption keys through the
  configured versioned key set.
- Use Decimal for persisted mass, economy, probabilities, and user-visible ratios.
- Add or update tests with every formula, schema, migration, gateway, or authorization change.
- Use Alembic for schema changes and preserve tenant/channel boundaries.
- Keep user-visible text in English and avoid exposing raw infrastructure errors in Twitch or
  Discord responses.

No license file is currently included in the repository. Add one explicitly before distributing the
project outside its current development context.
