"""Server — persistent socket server for CLI mode.

The server keeps the browser open between CLI calls, so the LLM can do:
    chatgpt start
    chatgpt send "hello"
    chatgpt response
    chatgpt send "another question"
    chatgpt response
    chatgpt stop

Without the server, each CLI call would need to launch Chrome from scratch.
The server communicates via a Unix socket with JSON messages.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import tempfile
from pathlib import Path

from .client import ChatGPT, DEFAULT_SEND_TIMEOUT

IS_WINDOWS = sys.platform == "win32"
SERVER_HOST = "127.0.0.1"
SERVER_PORT = int(os.environ.get("CHATGPT_BROWSER_USE_PORT", "8765"))
SOCKET_PATH = (
    str(Path(tempfile.gettempdir()) / "chatgpt_browser_use.sock")
    if IS_WINDOWS
    else "/tmp/chatgpt_browser_use.sock"
)
PID_FILE = str(Path(tempfile.gettempdir()) / "chatgpt_browser_use.pid")
LOG_FILE = str(Path(tempfile.gettempdir()) / "chatgpt_browser_use_server.log")
STILL_ACTIVE = 259


def _pid_is_running(pid: int) -> bool:
    """Return whether a process id is alive on the current platform."""
    if pid <= 0:
        return False

    if IS_WINDOWS:
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return False
                return exit_code.value == STILL_ACTIVE
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            return False

    try:
        os.kill(pid, 0)  # Check if process exists
        return True
    except OSError:
        return False


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, bot: ChatGPT):
    """Handle a single client connection."""
    try:
        data = await reader.read(1000000)
        if not data:
            return

        req = json.loads(data.decode())
        cmd = req.get("cmd", "")
        result = {"cmd": cmd}

        if cmd == "start":
            if not bot._started:
                bot.start()
            result["status"] = "running"
            result["url"] = bot.url()

        elif cmd == "send":
            prompt = req.get("prompt", "")
            timeout = req.get("timeout", DEFAULT_SEND_TIMEOUT)
            try:
                timeout = int(timeout)
            except (TypeError, ValueError):
                timeout = DEFAULT_SEND_TIMEOUT
            if timeout <= 0:
                timeout = DEFAULT_SEND_TIMEOUT
            if not prompt:
                result["error"] = "Missing 'prompt' field"
            else:
                reply = bot.send(prompt, timeout=timeout)
                result["response"] = reply
                result["url"] = bot.url()

        elif cmd == "response":
            result["response"] = bot.response()

        elif cmd == "messages":
            result["messages"] = bot.messages()

        elif cmd == "new":
            bot.new_chat()
            result["status"] = "new_chat"

        elif cmd == "download":
            prefix = req.get("prefix", "chatgpt")
            files = bot.download(prefix=prefix)
            result["files"] = files

        elif cmd == "url":
            result["url"] = bot.url()

        elif cmd == "stop":
            bot.stop()
            result["status"] = "stopped"
            writer.write(json.dumps(result).encode())
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            # Clean up and exit
            if os.path.exists(SOCKET_PATH):
                os.unlink(SOCKET_PATH)
            if os.path.exists(PID_FILE):
                os.unlink(PID_FILE)
            os._exit(0)

        else:
            result["error"] = f"Unknown command: {cmd}"

        writer.write(json.dumps(result).encode())
        await writer.drain()

    except Exception as e:
        try:
            writer.write(json.dumps({"error": str(e)}).encode())
            await writer.drain()
        except Exception:
            pass
    finally:
        writer.close()


async def run_server():
    """Run the persistent server."""
    # Clean up stale socket
    if not IS_WINDOWS and os.path.exists(SOCKET_PATH):
        os.unlink(SOCKET_PATH)

    bot = ChatGPT()
    bot.start()

    # Write PID file
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    print(f"[chatgpt-browser-use server ready]")
    if IS_WINDOWS:
        print(f"[TCP: {SERVER_HOST}:{SERVER_PORT}]")
    else:
        print(f"[Socket: {SOCKET_PATH}]")
    print(f"[URL: {bot.url()}]")
    sys.stdout.flush()

    if IS_WINDOWS:
        server = await asyncio.start_server(
            lambda r, w: handle_client(r, w, bot),
            SERVER_HOST,
            SERVER_PORT,
        )
    else:
        server = await asyncio.start_unix_server(
            lambda r, w: handle_client(r, w, bot),
            SOCKET_PATH,
        )

    async with server:
        await server.serve_forever()


def main():
    """Run the server when invoked as a module."""
    asyncio.run(run_server())


def send_command(cmd_dict: dict, timeout: int = 300) -> dict:
    """Send a command to the server and get the response. Used by CLI."""
    if not is_server_running():
        return {"error": "Server not running. Start it with: chatgpt start"}

    if IS_WINDOWS:
        s = socket.create_connection((SERVER_HOST, SERVER_PORT), timeout=timeout)
    else:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(SOCKET_PATH)
    try:
        s.sendall(json.dumps(cmd_dict).encode())
        data = b""
        timed_out = False
        while True:
            try:
                chunk = s.recv(1000000)
                if not chunk:
                    break
                data += chunk
            except (ConnectionResetError, ConnectionAbortedError, socket.timeout):
                timed_out = True
                break
        if data:
            return json.loads(data.decode())
        if cmd_dict.get("cmd") == "stop" and not is_server_running():
            return {"cmd": "stop", "status": "stopped"}
        if timed_out:
            return {
                "error": (
                    f"Timed out waiting for the server after {timeout} seconds. "
                    "ChatGPT may still be generating in the browser; try "
                    "`chatgpt response` or increase CHATGPT_BROWSER_USE_SEND_TIMEOUT."
                )
            }
        return {"error": "No response from server"}
    finally:
        s.close()


def is_server_running() -> bool:
    """Check if the server is running."""
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError, FileNotFoundError):
        return False

    if not _pid_is_running(pid):
        return False

    if IS_WINDOWS:
        try:
            with socket.create_connection((SERVER_HOST, SERVER_PORT), timeout=0.2):
                return True
        except OSError:
            return False

    return os.path.exists(SOCKET_PATH)


if __name__ == "__main__":
    main()
