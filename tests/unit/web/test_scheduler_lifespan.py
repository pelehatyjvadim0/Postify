from __future__ import annotations

import asyncio

from postify.web.app import create_app
from postify.web.dependencies import WebContainer


class SchedulerApi:
    def __init__(self) -> None:
        self.ticks = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def scheduler_tick(self) -> None:
        self.ticks += 1
        self.started.set()
        await self.release.wait()


def test_lifespan_starts_one_scheduler_task_and_cancels_it_on_shutdown() -> None:
    # Поломка: startup создаёт 0/2 pollers или shutdown оставляет task живой.
    async def exercise() -> tuple[int, bool, bool]:
        api = SchedulerApi()
        app = create_app(WebContainer(api=api))
        async with app.router.lifespan_context(app):
            await asyncio.wait_for(api.started.wait(), timeout=0.5)
            task = app.state.scheduler_task
            during = not task.done()
        return api.ticks, during, task.done()

    ticks, during, stopped = asyncio.run(exercise())

    assert ticks == 1
    assert during is True
    assert stopped is True


def test_lifespan_poll_wait_is_short_and_does_not_swallow_cancellation() -> None:
    # Поломка: polling sleep блокирует shutdown или CancelledError классифицируется как infrastructure failure.
    class FastApi:
        def __init__(self) -> None:
            self.ticks = 0

        async def scheduler_tick(self) -> None:
            self.ticks += 1

    async def exercise() -> tuple[int, float]:
        api = FastApi()
        app = create_app(WebContainer(api=api))
        loop = asyncio.get_running_loop()
        started = loop.time()
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0.3)
        return api.ticks, loop.time() - started

    ticks, duration = asyncio.run(exercise())

    assert ticks >= 2
    assert duration < 0.8


def test_polling_continues_after_infrastructure_failure() -> None:
    # Поломка: один DB failure навсегда завершает polling task.
    class FlakyApi:
        def __init__(self) -> None:
            self.ticks = 0

        async def scheduler_tick(self) -> None:
            self.ticks += 1
            if self.ticks == 1:
                raise OSError("database unavailable")

    async def exercise() -> int:
        api = FlakyApi()
        app = create_app(WebContainer(api=api))
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0.25)
        return api.ticks

    assert asyncio.run(exercise()) >= 2
