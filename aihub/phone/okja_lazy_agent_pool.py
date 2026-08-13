#!/usr/bin/env python3
"""Lazy async client pool for bridge profiles.

Construction performs no client I/O. A profile client is created only by get().
Failed initialization is not cached, so a later request can retry independently.
"""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from typing import Any, Callable, Mapping

Factory = Callable[[], Any]


class LazyAgentPool:
    def __init__(self, stack: AsyncExitStack, factories: Mapping[str, Factory]):
        if not factories:
            raise ValueError("at least one client factory is required")
        self._stack = stack
        self._factories = dict(factories)
        self._clients: dict[str, Any] = {}
        self._init_locks = {name: asyncio.Lock() for name in self._factories}

    def ready(self, name: str) -> bool:
        self._require_name(name)
        return name in self._clients

    def _require_name(self, name: str) -> None:
        if name not in self._factories:
            raise KeyError(f"unknown client profile: {name}")

    async def get(self, name: str) -> Any:
        self._require_name(name)
        existing = self._clients.get(name)
        if existing is not None:
            return existing

        async with self._init_locks[name]:
            existing = self._clients.get(name)
            if existing is not None:
                return existing

            context_manager = self._factories[name]()
            client = await self._stack.enter_async_context(context_manager)
            self._clients[name] = client
            return client
