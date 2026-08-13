import asyncio
import unittest
from contextlib import AsyncExitStack

from okja_lazy_agent_pool import LazyAgentPool


class FakeContext:
    def __init__(self, value=None, fail=False):
        self.value = value
        self.fail = fail
        self.entered = 0
        self.exited = 0

    async def __aenter__(self):
        self.entered += 1
        if self.fail:
            raise RuntimeError("init failed")
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        self.exited += 1


class LazyAgentPoolTests(unittest.IsolatedAsyncioTestCase):
    async def test_construction_is_lazy(self):
        calls = []
        async with AsyncExitStack() as stack:
            pool = LazyAgentPool(stack, {"personal": lambda: calls.append("made") or FakeContext("client")})
            self.assertFalse(pool.ready("personal"))
            self.assertEqual(calls, [])

    async def test_first_get_initializes_once_and_reuses_client(self):
        contexts = []
        def factory():
            ctx = FakeContext(object())
            contexts.append(ctx)
            return ctx
        async with AsyncExitStack() as stack:
            pool = LazyAgentPool(stack, {"personal": factory})
            first, second = await asyncio.gather(pool.get("personal"), pool.get("personal"))
            self.assertIs(first, second)
            self.assertEqual(len(contexts), 1)
            self.assertTrue(pool.ready("personal"))
        self.assertEqual(contexts[0].exited, 1)

    async def test_failed_initialization_is_not_cached_and_next_request_retries(self):
        attempts = 0
        good = FakeContext("recovered")
        def factory():
            nonlocal attempts
            attempts += 1
            return FakeContext(fail=True) if attempts == 1 else good
        async with AsyncExitStack() as stack:
            pool = LazyAgentPool(stack, {"grandma": factory})
            with self.assertRaises(RuntimeError):
                await pool.get("grandma")
            self.assertFalse(pool.ready("grandma"))
            self.assertEqual(await pool.get("grandma"), "recovered")
            self.assertTrue(pool.ready("grandma"))
            self.assertEqual(attempts, 2)

    async def test_profiles_initialize_independently(self):
        made = []
        async with AsyncExitStack() as stack:
            pool = LazyAgentPool(stack, {
                "grandma": lambda: made.append("grandma") or FakeContext("g"),
                "personal": lambda: made.append("personal") or FakeContext("p"),
            })
            self.assertEqual(await pool.get("personal"), "p")
            self.assertEqual(made, ["personal"])
            self.assertFalse(pool.ready("grandma"))

    async def test_unknown_profile_fails_closed(self):
        async with AsyncExitStack() as stack:
            pool = LazyAgentPool(stack, {"personal": lambda: FakeContext("p")})
            with self.assertRaises(KeyError):
                await pool.get("unknown")


if __name__ == "__main__":
    unittest.main()
