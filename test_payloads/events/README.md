Use these payloads with:

`POST /v1/admin/channels/{channel_twitch_id}/events`

Files:
- `create_event_minimal.json` - minimum valid body
- `create_event_basic.json` - standard event with modifiers
- `create_event_with_override_pool.json` - event with `override_loot_pool` (`location_id` string)
- `create_event_active_now.json` - create and immediately activate event
