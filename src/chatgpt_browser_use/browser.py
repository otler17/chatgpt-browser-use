"""Browser lifecycle — Xvfb, real Chromium, CDP connection.

Handles all the infrastructure pitfalls so the caller never sees them:
- Headless = Cloudflare block → real Chrome on Xvfb
- Snap Chromium confinement → correct user-data-dir
- Stale SingletonLock → auto-cleanup
- IN_DOCKER equivalent → --no-sandbox always added
- CDP port not ready → retry with timeout
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import websockets

DEFAULT_CDP_PORT = 9222
DEFAULT_DISPLAY = 99
# Snap Chromium can only write here (snap confinement)
LINUX_USER_DATA_DIR = str(Path.home() / "snap/chromium/common/chromium")
DEFAULT_CHROMIUM_BIN = "/snap/bin/chromium"


def _local_app_data() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")


def _default_user_data_dir() -> str:
    """Return a Chrome profile root that is safe for this platform."""
    if sys.platform == "win32":
        return str(_local_app_data() / "chatgpt-browser-use" / "chrome-profile")
    if sys.platform == "darwin":
        return str(
            Path.home()
            / "Library"
            / "Application Support"
            / "chatgpt-browser-use"
            / "chrome-profile"
        )
    return LINUX_USER_DATA_DIR


def _playwright_cache_dirs() -> list[Path]:
    """Return possible Playwright browser cache roots for this platform."""
    dirs = [Path.home() / ".cache" / "ms-playwright"]
    if sys.platform == "win32":
        dirs.insert(0, _local_app_data() / "ms-playwright")
    elif sys.platform == "darwin":
        dirs.insert(0, Path.home() / "Library" / "Caches" / "ms-playwright")
    return dirs


def _playwright_chromium_candidates() -> list[str]:
    """Discover Playwright Chromium executables across cache revisions."""
    candidates: list[str] = []
    for cache_dir in _playwright_cache_dirs():
        if not cache_dir.exists():
            continue
        for root in sorted(cache_dir.glob("chromium-*"), reverse=True):
            if sys.platform == "win32":
                candidates.append(str(root / "chrome-win" / "chrome.exe"))
            elif sys.platform == "darwin":
                candidates.append(
                    str(
                        root
                        / "chrome-mac"
                        / "Chromium.app"
                        / "Contents"
                        / "MacOS"
                        / "Chromium"
                    )
                )
            else:
                candidates.extend([
                    str(root / "chrome-linux64" / "chrome"),
                    str(root / "chrome-linux" / "chrome"),
                ])
    return candidates


class CDPClient:
    """Minimal CDP client over websocket — just Runtime.evaluate and Page.navigate."""

    def __init__(self, ws_url: str):
        self.ws_url = ws_url
        self.ws = None
        self._msg_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None

    async def connect(self):
        self.ws = await websockets.connect(self.ws_url, max_size=50 * 1024 * 1024)
        self._reader_task = asyncio.create_task(self._reader_loop())
        await self.send("Runtime.enable")
        await self.send("Page.enable")

    async def _reader_loop(self):
        try:
            while True:
                msg = await self.ws.recv()
                data = json.loads(msg)
                if "id" in data:
                    fut = self._pending.pop(data["id"], None)
                    if fut and not fut.done():
                        if "error" in data:
                            fut.set_exception(
                                RuntimeError(f"CDP error: {data['error']}")
                            )
                        else:
                            fut.set_result(data.get("result"))
        except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
            pass

    async def send(self, method: str, params: dict | None = None, timeout: float = 60):
        self._msg_id += 1
        mid = self._msg_id
        fut = asyncio.get_event_loop().create_future()
        self._pending[mid] = fut
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        return await asyncio.wait_for(fut, timeout=timeout)

    async def evaluate(self, expression: str, await_promise: bool = False) -> any:
        """Evaluate a JS expression. Returns the Python value or None."""
        result = await self.send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": await_promise,
            "allowUnsafeEval": True,
        })
        if result.get("exceptionDetails"):
            desc = result["exceptionDetails"].get("exception", {}).get("description", "")
            raise RuntimeError(f"JS error: {desc}")
        return result.get("result", {}).get("value")

    async def close(self):
        if self._reader_task:
            self._reader_task.cancel()
        if self.ws:
            await self.ws.close()


def _find_chromium() -> str:
    """Find a Chromium-family browser for the current platform."""
    env_candidates = [
        os.environ.get("CHROME_BIN"),
        os.environ.get("CHROME_PATH"),
        os.environ.get("CHROMIUM_BIN"),
    ]

    if sys.platform == "win32":
        program_files = [
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ]
        browser_candidates = []
        for root in [Path(p) for p in program_files if p]:
            browser_candidates.extend([
                str(root / "Google" / "Chrome" / "Application" / "chrome.exe"),
                str(root / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
                str(root / "Chromium" / "Application" / "chrome.exe"),
            ])
        browser_candidates.extend(["chrome.exe", "chrome", "msedge.exe", "msedge"])
    elif sys.platform == "darwin":
        browser_candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "google-chrome",
            "chromium",
        ]
    else:
        browser_candidates = [
            DEFAULT_CHROMIUM_BIN,
            "chromium",
            "chromium-browser",
            "google-chrome",
            "google-chrome-stable",
        ]

    candidates = [
        *[c for c in env_candidates if c],
        *browser_candidates,
        *_playwright_chromium_candidates(),
    ]

    for candidate in candidates:
        if shutil.which(candidate) or os.path.isfile(candidate):
            return candidate
    raise FileNotFoundError(
        "No Chromium-family browser found.\n"
        "  Windows: install Google Chrome or Microsoft Edge, or set CHROME_BIN.\n"
        "  Linux: sudo snap install chromium, or install Playwright Chromium.\n"
        "  Playwright: pip install playwright && playwright install chromium"
    )


def _cleanup_stale_locks(user_data_dir: str):
    """Remove stale SingletonLock/Cookie/Socket files from a crashed Chrome."""
    p = Path(user_data_dir)
    for name in ["SingletonLock", "SingletonCookie", "SingletonSocket"]:
        f = p / name
        if f.exists() or f.is_symlink():
            try:
                f.unlink()
            except OSError:
                pass


class BrowserLauncher:
    """Manages Chromium + CDP lifecycle.

    Linux uses Xvfb so Chrome is not headless. Windows and macOS launch a
    normal visible browser window.
    """

    def __init__(
        self,
        cdp_port: int = DEFAULT_CDP_PORT,
        display: int = DEFAULT_DISPLAY,
        user_data_dir: str | None = None,
        chromium_bin: str | None = None,
    ):
        self.cdp_port = cdp_port
        self.display = display
        self.user_data_dir = user_data_dir or _default_user_data_dir()
        self.chromium_bin = chromium_bin
        self._xvfb_proc: subprocess.Popen | None = None
        self._chrome_proc: subprocess.Popen | None = None
        self._cdp: CDPClient | None = None
        self._launched_xvfb = False
        self._launched_chrome = False

    async def start(self) -> CDPClient:
        """Start Xvfb (if needed), Chrome (if needed), and connect CDP.

        If Chrome is already running on the CDP port, just connect to it.
        """
        # Check if CDP is already up
        if await self._cdp_is_up():
            self._cdp = await self._connect_cdp()
            return self._cdp

        # Start Xvfb on Linux if display not already running.
        if sys.platform.startswith("linux") and not self._display_is_up():
            if not shutil.which("Xvfb"):
                raise FileNotFoundError(
                    "Xvfb not found. Install it with: sudo apt install xvfb"
                )
            self._start_xvfb()

        # Start Chrome
        _cleanup_stale_locks(self.user_data_dir)
        self._start_chrome()

        # Wait for CDP
        if not await self._wait_for_cdp(timeout=30):
            raise RuntimeError(
                f"Chrome started but CDP never responded on port {self.cdp_port}.\n"
                "Check that --remote-debugging-port is not blocked by firewall.\n"
                "If Chrome opened an existing browser session, close that browser or "
                "use a different user-data-dir."
            )

        self._cdp = await self._connect_cdp()
        return self._cdp

    async def stop(self):
        """Close CDP, kill Chrome and Xvfb (only if we launched them)."""
        if self._cdp:
            await self._cdp.close()
            self._cdp = None
        if self._launched_chrome and self._chrome_proc:
            self._chrome_proc.terminate()
            try:
                self._chrome_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._chrome_proc.kill()
            self._chrome_proc = None
            self._launched_chrome = False
        if self._launched_xvfb and self._xvfb_proc:
            self._xvfb_proc.terminate()
            try:
                self._xvfb_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._xvfb_proc.kill()
            self._xvfb_proc = None
            self._launched_xvfb = False

    def _display_is_up(self) -> bool:
        """Check if Xvfb (or a real X server) is running on our display."""
        return os.path.exists(f"/tmp/.X11-unix/X{self.display}")

    def _start_xvfb(self):
        """Start Xvfb virtual display."""
        env = os.environ.copy()
        proc = subprocess.Popen(
            [
                "Xvfb", f":{self.display}",
                "-screen", "0", "1280x720x24",
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._xvfb_proc = proc
        self._launched_xvfb = True
        time.sleep(1)  # Give it a moment to create the socket

    def _start_chrome(self):
        """Start Chromium with remote debugging."""
        env = os.environ.copy()
        if sys.platform.startswith("linux"):
            env["DISPLAY"] = f":{self.display}"
        if not self.chromium_bin:
            self.chromium_bin = _find_chromium()
        Path(self.user_data_dir).mkdir(parents=True, exist_ok=True)

        args = [
            self.chromium_bin,
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-gpu",
            "--remote-allow-origins=*",
            f"--remote-debugging-port={self.cdp_port}",
            f"--user-data-dir={self.user_data_dir}",
            "--profile-directory=Default",
            "https://chatgpt.com",
        ]
        if sys.platform.startswith("linux"):
            args.insert(1, "--no-sandbox")

        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(
            args,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        self._chrome_proc = proc
        self._launched_chrome = True
        time.sleep(3)  # Give Chrome time to start

    async def _cdp_is_up(self) -> bool:
        """Check if the CDP HTTP endpoint is responding."""
        try:
            resp = urllib.request.urlopen(
                f"http://127.0.0.1:{self.cdp_port}/json/version", timeout=2
            )
            return resp.status == 200
        except Exception:
            return False

    async def _wait_for_cdp(self, timeout: int = 30) -> bool:
        """Poll until CDP responds or timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if await self._cdp_is_up():
                return True
            await asyncio.sleep(1)
        return False

    async def _connect_cdp(self) -> CDPClient:
        """Find the chatgpt.com tab (or any page tab) and connect via websocket."""
        resp = urllib.request.urlopen(
            f"http://127.0.0.1:{self.cdp_port}/json", timeout=5
        )
        tabs = json.loads(resp.read())

        # Prefer a chatgpt.com tab
        ws_url = None
        for tab in tabs:
            if tab.get("type") == "page" and "chatgpt" in tab.get("url", "").lower():
                ws_url = tab["webSocketDebuggerUrl"]
                break

        # Fall back to any page tab
        if not ws_url:
            for tab in tabs:
                if tab.get("type") == "page":
                    ws_url = tab["webSocketDebuggerUrl"]
                    break

        if not ws_url:
            # Create a new tab
            try:
                resp = urllib.request.urlopen(
                    f"http://127.0.0.1:{self.cdp_port}/json/new?https://chatgpt.com",
                    timeout=5,
                )
                tab = json.loads(resp.read())
                ws_url = tab["webSocketDebuggerUrl"]
            except Exception as e:
                raise RuntimeError(f"No browser tab found and couldn't create one: {e}")

        client = CDPClient(ws_url)
        await client.connect()
        return client

    @property
    def cdp(self) -> CDPClient | None:
        return self._cdp
