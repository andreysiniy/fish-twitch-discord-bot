# Twitch E2E runner

`twitch_e2e_runner` is disabled by default and runs under the Docker `e2e`
profile. It uses four dedicated Twitch accounts when the full real transport
is enabled and never stores access or refresh tokens in run history.

For a local deterministic smoke check:

```powershell
Copy-Item .env.e2e.example .env.e2e
# Edit .env.e2e and keep it local; it contains Twitch/provider credentials.
docker compose --env-file .env --env-file .env.e2e --profile e2e build streamelements_stub twitch_e2e_runner
docker compose --env-file .env --env-file .env.e2e --profile e2e up -d postgres redis game_engine streamelements_stub twitch_e2e_runner
```

The base `.env` supplies database and service settings. The second file supplies
only E2E credentials and overrides them for the E2E profile. Set
`TWITCH_E2E_ENABLED=true` in `.env.e2e`, then call
`POST /internal/e2e/run/smoke`. The default `stub` mode validates the
engine/provider control path without sending Twitch messages. Set
`TWITCH_E2E_MODE=real` only for a dedicated test channel and all required
actor credentials.

The provider stub control endpoints are available only inside the Docker
network and can be protected with `STREAMELEMENTS_STUB_CONTROL_KEY`.
