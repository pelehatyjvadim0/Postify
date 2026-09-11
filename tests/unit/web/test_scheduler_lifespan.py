from __future__ import annotations

import asyncio
from threading import Event

from postify.web.app import create_app
from postify.web.dependencies import WebContainer
from tests.unit.web.test_api import AuthStub


class SchedulerApi:
    def __init__(self) -> None:
        self.ticks = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def scheduler_tick(self) -> None:
        self.ticks += 1
        self.started.set()
        await self.release.wait()

    def close(self) -> None:
        self.closed = True


def test_lifespan_starts_one_scheduler_task_and_stops_it_on_shutdown() -> None:
    # Поломка: startup создаёт 0/2 pollers или shutdown оставляет task живой.
    async def exercise() -> tuple[int, bool, bool]:
        api = SchedulerApi()
        app = create_app(WebContainer(api=api), auth=AuthStub())
        async with app.router.lifespan_context(app):
            await asyncio.wait_for(api.started.wait(), timeout=0.5)
            task = app.state.scheduler_task
            during = not task.done()
            api.release.set()
        return api.ticks, during, task.done(), getattr(api, "closed", False)

    ticks, during, stopped, closed = asyncio.run(exercise())

    assert ticks == 1
    assert during is True
    assert stopped is True
    assert closed is True


def test_recovery_finishes_once_before_the_first_scheduler_tick() -> None:
    class RecoveringApi:
        def __init__(self):
            self.events = []

        def recover_interrupted_operations(self):
            self.events.append("recover")

        def scheduler_tick(self):
            assert self.events[0] == "recover"
            self.events.append("tick")

    async def exercise():
        api = RecoveringApi()
        app = create_app(WebContainer(api=api), auth=AuthStub())
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0.25)
        return api.events

    events = asyncio.run(exercise())
    assert events.count("recover") == 1
    assert events.count("tick") >= 2


def test_lifespan_poll_wait_is_short_and_does_not_swallow_cancellation() -> None:
    # Поломка: polling sleep блокирует shutdown или CancelledError классифицируется как infrastructure failure.
    class FastApi:
        def __init__(self) -> None:
            self.ticks = 0

        async def scheduler_tick(self) -> None:
            self.ticks += 1

    async def exercise() -> tuple[int, float]:
        api = FastApi()
        app = create_app(WebContainer(api=api), auth=AuthStub())
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
        app = create_app(WebContainer(api=api), auth=AuthStub())
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0.25)
        return api.ticks

    assert asyncio.run(exercise()) >= 2


def test_lifespan_waits_for_blocking_sync_tick_without_blocking_loop() -> None:
    # Поломка: lifespan завершается, пока sync tick ещё может durable claim/command.
    class BlockingApi:
        def __init__(self) -> None:
            self.started = Event()
            self.release = Event()
            self.finished = Event()

        def scheduler_tick(self) -> None:
            self.started.set()
            self.release.wait(timeout=1.0)
            self.finished.set()

    async def exercise() -> tuple[bool, int, bool, bool]:
        api = BlockingApi()
        app = create_app(WebContainer(api=api), auth=AuthStub())
        context = app.router.lifespan_context(app)
        await context.__aenter__()
        for _ in range(50):
            if api.started.is_set():
                break
            await asyncio.sleep(0.01)
        task = app.state.scheduler_task
        exit_task = asyncio.create_task(context.__aexit__(None, None, None))
        heartbeat = 0
        for _ in range(5):
            await asyncio.sleep(0.01)
            heartbeat += 1
        exit_waited_for_worker = not exit_task.done()
        api.release.set()
        await asyncio.wait_for(exit_task, timeout=0.5)
        return exit_waited_for_worker, heartbeat, api.finished.is_set(), task.done()

    exit_waited, heartbeats, tick_finished, task_stopped = asyncio.run(exercise())

    assert exit_waited is True
    assert heartbeats == 5
    assert tick_finished is True
    assert task_stopped is True
