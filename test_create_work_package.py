"""Regression checks through FastMCP, with no requests to OpenProject."""

import json
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ["OPENPROJECT_URL"] = "https://openproject.invalid"
os.environ["OPENPROJECT_API_KEY"] = "test-only"

from fastmcp import Client
from src.server import mcp
from src.client import OpenProjectClient


class CreateWorkPackageTests(unittest.IsolatedAsyncioTestCase):
    async def test_object_and_json_string_create_subtask(self):
        data = dict(project_id=3010, subject="CDN", type_id=1,
                    priority_id=8, assignee_id=73, parent_id=24975)
        api = OpenProjectClient("https://openproject.invalid", "test-only")
        api._request = AsyncMock(side_effect=[
            {"payload": {"subject": "CDN", "_links": {}}},
            {"id": 123, "subject": "CDN"},
        ] * 2)
        with patch("src.tools.work_packages.get_client", return_value=api):
            async with Client(mcp) as client:
                tools = await client.list_tools()
                schema = next(t.inputSchema for t in tools if t.name == "create_work_package")
                self.assertIn("parent_id", json.dumps(schema))
                for value in (data, json.dumps(data)):
                    result = await client.call_tool("create_work_package", {"input": value})
                    self.assertFalse(result.is_error)
                    self.assertIn("#123", result.content[0].text)
        calls = api._request.call_args_list
        self.assertEqual(len(calls), 4)
        for form, create in (calls[:2], calls[2:]):
            self.assertEqual(form.args[1], "/work_packages/form")
            self.assertEqual(create.args[1], "/work_packages")
            for call in (form, create):
                self.assertEqual(call.args[2]["_links"]["parent"]["href"],
                                 "/api/v3/work_packages/24975")
            self.assertEqual(create.args[2]["_links"]["assignee"]["href"], "/api/v3/users/73")
            self.assertEqual(create.args[2]["_links"]["priority"]["href"], "/api/v3/priorities/8")

    async def test_invalid_input_never_reaches_api(self):
        api = AsyncMock()
        base = dict(project_id=3010, subject="CDN", type_id=1)
        with patch("src.tools.work_packages.get_client", return_value=api):
            async with Client(mcp) as client:
                for value in ("{bad", "[]", dict(base, parent_id=0),
                              json.dumps(dict(base, project_id=-1)), dict(base, subject="")):
                    with self.subTest(value=value):
                        result = await client.call_tool("create_work_package", {"input": value},
                                                        raise_on_error=False)
                        self.assertTrue(result.is_error)
        api.create_work_package.assert_not_awaited()

    async def test_object_without_parent_still_works(self):
        api = OpenProjectClient("https://openproject.invalid", "test-only")
        api._request = AsyncMock(side_effect=[
            {"payload": {"subject": "Standalone", "_links": {}}},
            {"id": 124, "subject": "Standalone"},
        ])
        with patch("src.tools.work_packages.get_client", return_value=api):
            async with Client(mcp) as client:
                result = await client.call_tool("create_work_package", {"input": {
                    "project_id": 3010, "subject": "Standalone", "type_id": 1}})
                self.assertFalse(result.is_error)
        self.assertNotIn("parent", api._request.call_args.args[2]["_links"])


if __name__ == "__main__":
    unittest.main()
