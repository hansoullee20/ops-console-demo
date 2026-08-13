import ast
import pathlib
import unittest


BRIDGE = pathlib.Path(__file__).with_name("aihub_bridge.py")


class BridgeLazyStartupContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = BRIDGE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_no_direct_eager_sdk_context_entry_remains(self):
        self.assertNotIn("await stack.enter_async_context(ClaudeSDKClient", self.source)
        self.assertIn("pool = LazyAgentPool", self.source)

    def test_agent_pool_get_only_occurs_inside_request_handler(self):
        main = next(
            node for node in self.tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "main"
        )
        handle = next(
            node for node in main.body
            if isinstance(node, ast.AsyncWith)
            for item in node.body
            if isinstance(item, ast.AsyncFunctionDef) and item.name == "handle"
        )
        get_calls = [
            node for node in ast.walk(main)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "pool"
        ]
        self.assertGreaterEqual(len(get_calls), 1)
        handle_nodes = set(ast.walk(handle))
        self.assertTrue(all(call in handle_nodes for call in get_calls))

    def test_server_bind_is_in_main_and_not_request_handler(self):
        main = next(
            node for node in self.tree.body
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "main"
        )
        start_server_calls = [
            node for node in ast.walk(main)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "asyncio"
            and node.func.attr == "start_server"
        ]
        self.assertEqual(len(start_server_calls), 1)
        self.assertIn("server = await asyncio.start_server(handle, HOST, PORT)", self.source)


if __name__ == "__main__":
    unittest.main()
