"""Workaround for twitchio 2.10.0 reconnect handling.

twitchio sets ``WSConnection._init`` to True after the first ``ready``
dispatch but never resets it when the websocket reconnects. On a reconnect
the NAMES (353) handler skips populating ``_join_load`` because ``_init`` is
already True and the MOTD (376) handler only sets ``is_ready`` when there
are no initial channels, so the login coroutine blocks on
``is_ready.wait()`` forever and ``event_ready`` stops firing. Resetting the
flag before each connect makes a reconnect behave exactly like a clean
startup.
"""


def patch_reconnect_init(connection) -> None:
    """Make every websocket (re)connect behave like a clean startup."""
    original_connect = connection._connect

    async def _connect() -> None:
        connection._init = False
        await original_connect()

    connection._connect = _connect
