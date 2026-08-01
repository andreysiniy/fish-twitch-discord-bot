from collections.abc import Awaitable, Callable

from aiohttp import web


class HealthServer:
    def __init__(
        self,
        port: int,
        readiness: Callable[[], Awaitable[dict[str, bool]]],
    ):
        self.port = port
        self.readiness = readiness
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/health/live", self.live)
        app.router.add_get("/health/ready", self.ready)
        app.router.add_get("/health", self.ready)
        app.router.add_get("/metrics", self.metrics)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, "0.0.0.0", self.port).start()

    async def close(self) -> None:
        if self._runner:
            await self._runner.cleanup()

    async def live(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "healthy", "service": "discord_gateway"})

    async def ready(self, request: web.Request) -> web.Response:
        dependencies = await self.readiness()
        healthy = all(dependencies.values())
        return web.json_response(
            {
                "status": "ready" if healthy else "unavailable",
                "service": "discord_gateway",
                "dependencies": dependencies,
            },
            status=200 if healthy else 503,
        )

    async def metrics(self, request: web.Request) -> web.Response:
        dependencies = await self.readiness()
        lines = [
            "# HELP fisher_discord_dependency_ready Whether a dependency is ready.",
            "# TYPE fisher_discord_dependency_ready gauge",
        ]
        lines.extend(
            f'fisher_discord_dependency_ready{{dependency="{name}"}} {int(ready)}'
            for name, ready in dependencies.items()
        )
        return web.Response(text="\n".join(lines) + "\n", content_type="text/plain")
