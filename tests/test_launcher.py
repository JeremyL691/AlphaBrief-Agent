from __future__ import annotations

from app.launcher import build_process_commands


def test_build_process_commands_include_api_and_dashboard_targets():
    api_cmd, dashboard_cmd = build_process_commands("/tmp/python")

    assert api_cmd[:3] == ["/tmp/python", "-m", "uvicorn"]
    assert "app.main:app" in api_cmd
    assert dashboard_cmd[:3] == ["/tmp/python", "-m", "streamlit"]
    assert "dashboard/streamlit_app.py" in dashboard_cmd
