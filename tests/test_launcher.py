from __future__ import annotations

from types import SimpleNamespace

from app.launcher import build_process_commands, dependencies_healthy


def test_build_process_commands_include_api_and_dashboard_targets():
    api_cmd, dashboard_cmd = build_process_commands("/tmp/python")

    assert api_cmd[:3] == ["/tmp/python", "-m", "uvicorn"]
    assert "app.main:app" in api_cmd
    assert dashboard_cmd[:3] == ["/tmp/python", "-m", "streamlit"]
    assert "dashboard/streamlit_app.py" in dashboard_cmd


def test_dependencies_healthy_checks_required_imports(monkeypatch):
    monkeypatch.setattr(
        "app.launcher.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0),
    )
    assert dependencies_healthy("/tmp/python") is True

    monkeypatch.setattr(
        "app.launcher.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1),
    )
    assert dependencies_healthy("/tmp/python") is False
