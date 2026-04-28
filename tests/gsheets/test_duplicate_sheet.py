"""Tests for duplicate_sheet tool."""

from unittest.mock import Mock

import pytest

from gsheets.sheets_tools import duplicate_sheet


def _create_mock_service(sheets_metadata, batch_update_response):
    """Create a Sheets service mock for duplicate_sheet."""
    mock_service = Mock()
    mock_service.spreadsheets().get().execute = Mock(return_value=sheets_metadata)
    mock_service.spreadsheets().batchUpdate().execute = Mock(
        return_value=batch_update_response
    )
    return mock_service


async def _call_duplicate_sheet(service, **overrides):
    """Call the undecorated implementation to keep auth out of unit tests."""
    impl = duplicate_sheet.__wrapped__.__wrapped__
    defaults = {
        "service": service,
        "user_google_email": "user@example.com",
        "spreadsheet_id": "spreadsheet-123",
        "source_sheet_name": "Original",
    }
    defaults.update(overrides)
    return await impl(**defaults)


@pytest.mark.asyncio
async def test_duplicate_sheet_basic():
    service = _create_mock_service(
        sheets_metadata={
            "sheets": [
                {"properties": {"sheetId": 100, "title": "Original"}},
            ]
        },
        batch_update_response={
            "replies": [
                {
                    "duplicateSheet": {
                        "properties": {
                            "sheetId": 200,
                            "title": "Copy of Original",
                        }
                    }
                }
            ]
        },
    )

    result = await _call_duplicate_sheet(service)

    assert "Successfully duplicated" in result
    assert "'Original'" in result
    assert "'Copy of Original'" in result
    assert "(ID: 200)" in result


@pytest.mark.asyncio
async def test_duplicate_sheet_with_custom_name_and_index():
    service = _create_mock_service(
        sheets_metadata={
            "sheets": [
                {"properties": {"sheetId": 100, "title": "2026-04-21"}},
            ]
        },
        batch_update_response={
            "replies": [
                {
                    "duplicateSheet": {
                        "properties": {
                            "sheetId": 300,
                            "title": "2026-04-28",
                        }
                    }
                }
            ]
        },
    )

    result = await _call_duplicate_sheet(
        service,
        source_sheet_name="2026-04-21",
        new_sheet_name="2026-04-28",
        insert_sheet_index=0,
    )

    assert "'2026-04-28'" in result
    assert "(ID: 300)" in result


@pytest.mark.asyncio
async def test_duplicate_sheet_source_not_found():
    service = _create_mock_service(
        sheets_metadata={
            "sheets": [
                {"properties": {"sheetId": 100, "title": "Sheet1"}},
            ]
        },
        batch_update_response={},
    )

    with pytest.raises(Exception, match="not found"):
        await _call_duplicate_sheet(service, source_sheet_name="NonExistent")
