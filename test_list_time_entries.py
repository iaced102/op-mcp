"""Read-only time tracking regression checks; API requests are mocked."""
import json
import os
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import AsyncMock, patch

with patch.dict(os.environ, OPENPROJECT_URL="https://openproject.invalid",
                OPENPROJECT_API_KEY="test-only"):
    from src.server import mcp
from fastmcp import Client
from src.client import OpenProjectClient
from src.tools.time_entries import _hours


class TimeEntryTests(unittest.IsolatedAsyncioTestCase):
    def test_duration(self):
        for value, expected in [("PT8H", 8), ("PT1H30M", 1.5),
                                ("PT90M", 1.5), ("PT30S", 1/120),
                                ("P1DT2H", 26), ("PT0S", 0), (2.5, 2.5)]:
            self.assertAlmostEqual(_hours(value), expected)
        for value in (None, "P", "PT", "garbage", "P1M"):
            with self.assertRaises(ValueError):
                _hours(value)

    async def test_filters_hours_and_pagination(self):
        api = OpenProjectClient("https://openproject.invalid", "test-only")
        api._request = AsyncMock(return_value={"total": 3, "_embedded": {"elements": [
            {"id": 1, "hours": "PT8H", "spentOn": "2026-09-24",
             "_links": {"entity": {"href": "/api/v3/work_packages/25132", "title": "Audit"},
                        "user": {"title": "Phuc"}}},
            {"id": 2, "hours": "PT1H30M", "spentOn": "2026-09-24"},
        ]}})
        with patch("src.tools.time_entries.get_client", return_value=api):
            async with Client(mcp) as client:
                result = await client.call_tool("list_time_entries", dict(
                    work_package_id=25132, user_id=164, from_date="2026-09-24",
                    to_date="2026-09-24", page_size=2))
        self.assertFalse(result.is_error)
        text = result.content[0].text
        self.assertIn("9.5", text)
        self.assertIn("Audit", text)
        self.assertIn("offset=2", text)
        query = parse_qs(urlsplit(api._request.call_args.args[1]).query)
        self.assertEqual(query["offset"], ["1"])
        filters = {k: v for f in json.loads(query["filters"][0]) for k, v in f.items()}
        self.assertEqual(filters["entity_id"]["values"], ["25132"])
        self.assertEqual(filters["entity_type"]["values"], ["WorkPackage"])
        self.assertEqual(filters["user_id"]["values"], ["164"])
        self.assertEqual(filters["spent_on"], {"operator": "<>d", "values": ["2026-09-24"]*2})

    async def test_single_bounds_empty_and_invalid(self):
        api = AsyncMock()
        api.get_time_entries.return_value = {"total": 0, "_embedded": {"elements": []}}
        with patch("src.tools.time_entries.get_client", return_value=api):
            async with Client(mcp) as client:
                for field, bounds in (("from_date", ["2026-09-24", "9999-12-31"]),
                                      ("to_date", ["0001-01-01", "2026-09-24"])):
                    result = await client.call_tool("list_time_entries", {field: "2026-09-24"})
                    self.assertIn("Total matching entries: 0", result.content[0].text)
                    filters = json.loads(api.get_time_entries.call_args.args[0])
                    self.assertEqual(filters[0]["spent_on"], {"operator": "<>d", "values": bounds})
                for args in ({"from_date": "bad"}, {"from_date": "2026-10-01", "to_date": "2026-09-01"},
                             {"offset": 0}, {"page_size": 101}):
                    api.reset_mock()
                    result = await client.call_tool("list_time_entries", args)
                    self.assertIn("Failed to list time entries", result.content[0].text)
                    api.get_time_entries.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
