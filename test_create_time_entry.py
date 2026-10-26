"""Validate time entry inputs through FastMCP without writing real log time."""
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

with patch.dict(os.environ, OPENPROJECT_URL="https://openproject.invalid",
                OPENPROJECT_API_KEY="test-only"):
    from src.server import mcp
from fastmcp import Client


class CreateTimeEntryTests(unittest.IsolatedAsyncioTestCase):
    async def test_object_and_json_string(self):
        data = dict(work_package_id=25230, hours=1.5, spent_on="2026-07-09",
                    activity_id=25, comment="Thiết kế chi tiết")
        api = AsyncMock()
        api.create_time_entry.return_value = dict(id=123, hours="PT1H30M", spentOn=data["spent_on"])
        with patch("src.tools.time_entries.get_client", return_value=api):
            async with Client(mcp) as client:
                for value in (data, json.dumps(data, ensure_ascii=False)):
                    result = await client.call_tool("create_time_entry", {"input": value})
                    self.assertFalse(result.is_error)
                    self.assertIn("#123", result.content[0].text)
        self.assertEqual(api.create_time_entry.await_count, 2)
        for call in api.create_time_entry.await_args_list:
            self.assertEqual(call.args[0], dict(data, hours="1.5"))

    async def test_invalid_input_never_writes(self):
        base = dict(work_package_id=25230, hours=8, spent_on="2026-07-09", activity_id=25)
        api = AsyncMock()
        bad = ["{bad", "[]", '"text"', "null", {}, dict(base, hours=0),
               dict(base, hours=-1), dict(base, activity_id=0), dict(base, work_package_id=0)]
        with patch("src.tools.time_entries.get_client", return_value=api):
            async with Client(mcp) as client:
                for value in bad:
                    for encoded in (value, json.dumps(value)) if isinstance(value, dict) else (value,):
                        with self.subTest(value=encoded):
                            result = await client.call_tool("create_time_entry", {"input": encoded},
                                                            raise_on_error=False)
                            self.assertTrue(result.is_error)
        api.create_time_entry.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
