"""Tests for chatgpt_browser_use.

These tests verify the package structure and import-correctness without
requiring a running browser (which needs Xvfb + Chrome + ChatGPT login).

For end-to-end tests that actually drive ChatGPT, see examples/.
"""

import pytest


def test_import():
    """The main class should be importable from the package root."""
    from chatgpt_browser_use import ChatGPT
    assert ChatGPT is not None


def test_import_modules():
    """All internal modules should import cleanly."""
    from chatgpt_browser_use import browser, composer, response, downloads, server, cli
    assert browser is not None
    assert composer is not None
    assert response is not None
    assert downloads is not None
    assert server is not None
    assert cli is not None


def test_chatgpt_class_methods():
    """ChatGPT class should have exactly 5 public methods (+ start/stop)."""
    from chatgpt_browser_use import ChatGPT

    public_methods = [
        m for m in dir(ChatGPT)
        if not m.startswith("_") and callable(getattr(ChatGPT, m))
    ]

    # The core API surface
    expected = {"start", "send", "response", "messages", "new_chat", "download", "url", "stop"}
    actual = set(public_methods)

    assert expected.issubset(actual), f"Missing methods: {expected - actual}"


def test_chatgpt_class_init():
    """ChatGPT should be instantiable without a browser."""
    from chatgpt_browser_use import ChatGPT

    bot = ChatGPT()
    assert bot is not None
    assert bot._started is False
    assert bot._cdp is None


def test_cli_usage():
    """CLI should have a main function and print usage when called with no args."""
    from chatgpt_browser_use import cli

    assert callable(cli.main)
    assert "chatgpt start" in cli.USAGE
    assert "chatgpt send" in cli.USAGE
    assert "chatgpt stop" in cli.USAGE


def test_cli_send_timeout_env(monkeypatch):
    """CLI send timeout should be configurable for long-running prompts."""
    from chatgpt_browser_use import cli
    from chatgpt_browser_use.client import DEFAULT_SEND_TIMEOUT

    monkeypatch.delenv("CHATGPT_BROWSER_USE_SEND_TIMEOUT", raising=False)
    assert cli._send_timeout() == DEFAULT_SEND_TIMEOUT

    monkeypatch.setenv("CHATGPT_BROWSER_USE_SEND_TIMEOUT", "42")
    assert cli._send_timeout() == 42

    monkeypatch.setenv("CHATGPT_BROWSER_USE_SEND_TIMEOUT", "bad")
    assert cli._send_timeout() == DEFAULT_SEND_TIMEOUT


def test_server_helpers():
    """Server module should have send_command and is_server_running."""
    from chatgpt_browser_use import server

    assert callable(server.send_command)
    assert callable(server.is_server_running)
    assert server.SOCKET_PATH.endswith("chatgpt_browser_use.sock")
    assert server.PID_FILE.endswith("chatgpt_browser_use.pid")
    assert server.LOG_FILE.endswith("chatgpt_browser_use_server.log")


def test_browser_launcher():
    """BrowserLauncher should be instantiable with defaults."""
    from chatgpt_browser_use.browser import BrowserLauncher

    launcher = BrowserLauncher()
    assert launcher.cdp_port == 9222
    assert launcher.display == 99
    assert launcher.user_data_dir


def test_chromium_discovery_helpers():
    """Chromium discovery helpers should be callable on every platform."""
    from chatgpt_browser_use.browser import (
        _default_user_data_dir,
        _playwright_chromium_candidates,
    )

    assert _default_user_data_dir()
    assert isinstance(_playwright_chromium_candidates(), list)


def test_downloads_ext_map():
    """Extension mapping should cover common languages."""
    from chatgpt_browser_use.downloads import _get_extension

    assert _get_extension("python") == "py"
    assert _get_extension("javascript") == "js"
    assert _get_extension("typescript") == "ts"
    assert _get_extension("bash") == "sh"
    assert _get_extension("html") == "html"
    assert _get_extension("unknown") == "txt"


def test_download_artifact_helpers(tmp_path):
    """Artifact helpers should sanitize names and save data URLs."""
    from chatgpt_browser_use.downloads import (
        _extension_from_mime,
        _safe_filename,
        _save_data_url,
    )

    assert _safe_filename("bad:name?.png") == "bad_name_.png"
    assert _extension_from_mime("image/jpeg") == "jpg"
    assert _extension_from_mime("application/pdf") == "pdf"
    assert _extension_from_mime("application/zip") == "zip"
    assert _extension_from_mime("audio/mpeg") == "mp3"
    assert _extension_from_mime("video/mp4") == "mp4"

    target = tmp_path / "hello.txt"
    _save_data_url("data:text/plain;base64,aGVsbG8=", target)
    assert target.read_text(encoding="utf-8") == "hello"
