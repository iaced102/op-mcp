"""Time entry management tools for time tracking."""

import re
from datetime import date
from typing import Optional
from pydantic import BaseModel, Field
from src.server import mcp, get_client
from src.utils.formatting import format_success, format_error


def _hours(value):
    """Convert API day/time durations to decimal hours without dropping minutes."""
    if isinstance(value, (int, float)):
        return float(value)
    match = re.fullmatch(
        r"P(?:(\d+(?:\.\d+)?)D)?(?:T(?:(\d+(?:\.\d+)?)H)?"
        r"(?:(\d+(?:\.\d+)?)M)?(?:(\d+(?:\.\d+)?)S)?)?", str(value)
    )
    if not match or not any(match.groups()):
        raise ValueError(f"Invalid time entry duration: {value!r}")
    days, hours, minutes, seconds = (float(v or 0) for v in match.groups())
    return days * 24 + hours + minutes / 60 + seconds / 3600


class CreateTimeEntryInput(BaseModel):
    """Input model for creating time entries."""
    work_package_id: int = Field(..., description="Work package ID", gt=0)
    hours: float = Field(..., description="Hours spent", gt=0)
    spent_on: str = Field(..., description="Date spent (YYYY-MM-DD)")
    activity_id: int = Field(..., description="Actual activity ID returned by list_time_entry_activities(work_package_id)", gt=0)
    comment: Optional[str] = Field(None, description="Optional comment")


class UpdateTimeEntryInput(BaseModel):
    """Input model for updating time entries."""
    time_entry_id: int = Field(..., description="Time entry ID to update", gt=0)
    hours: Optional[float] = Field(None, description="New hours spent", gt=0)
    spent_on: Optional[str] = Field(None, description="New date (YYYY-MM-DD)")
    activity_id: Optional[int] = Field(None, description="New activity ID", gt=0)
    comment: Optional[str] = Field(None, description="New comment")


@mcp.tool
async def list_time_entries(
    work_package_id: Optional[int] = None,
    user_id: Optional[int] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    offset: int = 1,
    page_size: int = 100,
) -> str:
    """List time entries with optional filters.

    Args:
        work_package_id: Optional filter by work package
        user_id: Optional filter by user
        from_date: Optional start date (YYYY-MM-DD)
        to_date: Optional end date (YYYY-MM-DD)
        offset: Page number, starting at 1
        page_size: Entries per page (1-100)

    Returns:
        List of time entries
    """
    try:
        client = get_client()

        import json
        if offset < 1 or not 1 <= page_size <= 100:
            raise ValueError("offset must be >= 1 and page_size must be 1-100")
        for value in (from_date, to_date):
            if value:
                date.fromisoformat(value)
        if from_date and to_date and from_date > to_date:
            raise ValueError("from_date must not be after to_date")
        filters = []
        if work_package_id:
            filters.append({"entity_id": {"operator": "=", "values": [str(work_package_id)]}})
            filters.append({"entity_type": {"operator": "=", "values": ["WorkPackage"]}})
        if user_id:
            filters.append({"user_id": {"operator": "=", "values": [str(user_id)]}})
        if from_date or to_date:
            filters.append({"spent_on": {"operator": "<>d", "values": [
                from_date or date.min.isoformat(), to_date or date.max.isoformat()
            ]}})

        filters_json = json.dumps(filters) if filters else None

        result = await client.get_time_entries(filters_json, offset=offset, page_size=page_size)
        entries = result.get("_embedded", {}).get("elements", [])

        if not entries:
            return f"No time entries on page {offset}. Total matching entries: {result.get('total', 0)}."

        text = f"✅ **Found {len(entries)} time entr{'y' if len(entries) == 1 else 'ies'}:**\n\n"
        total_hours = 0

        for entry in entries:
            text += f"**Time Entry #{entry.get('id', 'N/A')}**\n"
            hours = _hours(entry.get('hours'))
            text += f"  Hours: {hours:g}\n"
            text += f"  Date: {entry.get('spentOn', 'N/A')}\n"

            embedded = entry.get("_embedded", {})
            if "workPackage" in embedded:
                text += f"  Work Package: {embedded['workPackage'].get('subject', 'Unknown')}\n"
            if "user" in embedded:
                text += f"  User: {embedded['user'].get('name', 'Unknown')}\n"
            if "activity" in embedded:
                text += f"  Activity: {embedded['activity'].get('name', 'Unknown')}\n"
            links = entry.get("_links", {})
            for label, key in (("Work Package", "entity"), ("User", "user"),
                               ("Activity", "activity"), ("Working hours", "customField2")):
                if key not in embedded and links.get(key, {}).get("title"):
                    text += f"  {label}: {links[key]['title']} ({links[key].get('href')})\n"

            if entry.get('comment', {}).get('raw'):
                text += f"  Comment: {entry['comment']['raw']}\n"

            total_hours += hours
            text += "\n"

        text += f"**Hours on this page**: {total_hours:g}\n"
        total = result.get("total", len(entries))
        text += f"**Page**: {offset}; **Total matching entries**: {total}\n"
        if offset * page_size < total:
            text += f"Use offset={offset + 1} to read the next page.\n"

        return text

    except Exception as e:
        return format_error(f"Failed to list time entries: {str(e)}")


@mcp.tool
async def create_time_entry(input: CreateTimeEntryInput) -> str:
    """Create a new time entry for a work package.

    Fetch valid activity IDs with list_time_entry_activities(work_package_id).
    Activity IDs are configured per instance and must not be guessed.

    Args:
        input: Time entry data including work_package_id, hours, date, activity, and optional comment

    Returns:
        Success message with created time entry details

    Example:
        {
            "work_package_id": 123,
            "hours": 2.5,
            "spent_on": "2025-01-15",
            "activity_id": 3,
            "comment": "Implemented feature X"
        }
    """
    try:
        client = get_client()

        data = {
            "work_package_id": input.work_package_id,
            "hours": str(input.hours),
            "spent_on": input.spent_on,
            "activity_id": input.activity_id,
        }

        if input.comment:
            data["comment"] = input.comment

        result = await client.create_time_entry(data)

        text = format_success(f"Time entry created successfully!\n\n")
        text += f"**ID**: #{result.get('id', 'N/A')}\n"
        text += f"**Hours**: {result.get('hours', 0)}\n"
        text += f"**Date**: {result.get('spentOn', 'N/A')}\n"

        embedded = result.get("_embedded", {})
        if "workPackage" in embedded:
            text += f"**Work Package**: {embedded['workPackage'].get('subject', 'Unknown')}\n"
        if "activity" in embedded:
            text += f"**Activity**: {embedded['activity'].get('name', 'Unknown')}\n"

        if result.get('comment', {}).get('raw'):
            text += f"**Comment**: {result['comment']['raw']}\n"

        return text

    except Exception as e:
        return format_error(f"Failed to create time entry: {str(e)}")


@mcp.tool
async def update_time_entry(input: UpdateTimeEntryInput) -> str:
    """Update an existing time entry.

    Args:
        input: Time entry update data including time_entry_id and fields to update

    Returns:
        Success message with updated time entry details
    """
    try:
        client = get_client()

        update_data = {}

        if input.hours is not None:
            update_data["hours"] = str(input.hours)
        if input.spent_on is not None:
            update_data["spent_on"] = input.spent_on
        if input.activity_id is not None:
            update_data["activity_id"] = input.activity_id
        if input.comment is not None:
            update_data["comment"] = input.comment

        if not update_data:
            return format_error("No fields provided to update")

        result = await client.update_time_entry(input.time_entry_id, update_data)

        text = format_success(f"Time entry #{input.time_entry_id} updated successfully!\n\n")
        text += f"**Hours**: {result.get('hours', 0)}\n"
        text += f"**Date**: {result.get('spentOn', 'N/A')}\n"

        embedded = result.get("_embedded", {})
        if "activity" in embedded:
            text += f"**Activity**: {embedded['activity'].get('name', 'Unknown')}\n"

        if result.get('comment', {}).get('raw'):
            text += f"**Comment**: {result['comment']['raw']}\n"

        return text

    except Exception as e:
        return format_error(f"Failed to update time entry: {str(e)}")


@mcp.tool
async def delete_time_entry(time_entry_id: int) -> str:
    """Delete a time entry.

    Args:
        time_entry_id: ID of the time entry to delete

    Returns:
        Success or error message
    """
    try:
        client = get_client()

        success = await client.delete_time_entry(time_entry_id)

        if success:
            return format_success(f"Time entry #{time_entry_id} deleted successfully")
        else:
            return format_error(f"Failed to delete time entry #{time_entry_id}")

    except Exception as e:
        return format_error(f"Failed to delete time entry: {str(e)}")


@mcp.tool
async def list_time_entry_activities(work_package_id: Optional[int] = None) -> str:
    """List actual allowed activities. Supply a work package ID for project choices.

    Never substitutes guessed activity IDs when the API is unavailable.
    """
    try:
        client = get_client()
        if work_package_id is not None:
            if work_package_id <= 0:
                raise ValueError("work_package_id must be positive")
            activities = await client.get_allowed_time_entry_activities(work_package_id)
        else:
            result = await client.get_time_entry_activities()
            activities = result.get("_embedded", {}).get("elements", [])
        if not activities:
            return "No allowed time entry activities found. Supply work_package_id to query its form."
        text = "Available Time Entry Activities:\n\n"
        for activity in activities:
            text += f"- {activity.get('name', 'Unnamed')} (ID: {activity.get('id', 'N/A')})\n"
            if activity.get("default", activity.get("isDefault", False)):
                text += "  Default activity\n"
        return text
    except Exception as e:
        return format_error(f"Failed to list activities: {e}. Supply work_package_id to use the form schema.")


@mcp.tool
async def get_time_entry_form(work_package_id: int) -> str:
    """Return time entry creation form with schema, defaults and validation errors.

    Does not create or save a time entry. Use its activity allowedValues for IDs.
    """
    try:
        import json
        if work_package_id <= 0:
            raise ValueError("work_package_id must be positive")
        return json.dumps(await get_client().get_time_entry_form(work_package_id), ensure_ascii=False)
    except Exception as e:
        return format_error(f"Failed to get time entry form: {e}")
