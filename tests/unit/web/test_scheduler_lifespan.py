from __future__ import annotations

import asyncio
from threading import Event

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


def test_blocking_sync_tick_keeps_loop_responsive_and_shutdown_bounded() -> None:
    # Поломка: production sync tick блокирует event loop, а shutdown ждёт worker.
    class BlockingApi:
        def __init__(self) -> None:
            self.started = Event()
            self.release = Event()
            self.finished = Event()

        def scheduler_tick(self) -> None:
            self.started.set()
            self.release.wait(timeout=1.0)
            self.finished.set()

    async def exercise() -> tuple[float, bool, float, bool]:
        api = BlockingApi()
        app = create_app(WebContainer(api=api))
        loop = asyncio.get_running_loop()
        responsive_started = loop.time()
        shutdown_elapsed = 99.0
        task = None
        try:
            async with app.router.lifespan_context(app):
                await asyncio.sleep(0.05)
                responsive_elapsed = loop.time() - responsive_started
                task = app.state.scheduler_task
                running_during_shutdown = (
                    api.started.is_set() and not api.finished.is_set()
                )
                shutdown_started = loop.time()
            shutdown_elapsed = loop.time() - shutdown_started
        finally:
            api.release.set()
        return (
            responsive_elapsed,
            running_during_shutdown,
            shutdown_elapsed,
            task.done(),
        )

    responsive, worker_was_running, shutdown, task_stopped = asyncio.run(exercise())

    assert responsive < 0.2
    assert worker_was_running is True
    assert shutdown < 0.2
    assert task_stopped is True
