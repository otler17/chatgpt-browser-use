"""CLI — dead-simple command line interface for small LLMs.

7 commands. That's it.

    chatgpt start                     # Launch browser + connect to ChatGPT
    chatgpt send "your prompt"        # Send a prompt, print the response
    chatgpt response                  # Print the last response
    chatgpt messages                  # Print all messages in the conversation
    chatgpt new                       # Start a new conversation
    chatgpt download [prefix]         # Save code blocks, images, and files
    chatgpt stop                      # Stop the server + close browser

Design for small LLMs:
- Each command is independent (no state between calls except the server)
- Output is always plain text, never JSON
- Errors are human-readable, not stack traces
- No flags, no options, no subcommands-of-subcommands
- "chatgpt send" prints the response directly to stdout
"""

from __future__ import annotations

import sys
import json
import os
import subprocess
from . import server as srv


USAGE = """\
chatgpt-browser-use CLI

Commands:
  chatgpt start                   Launch browser + connect to ChatGPT
  chatgpt send "your prompt"      Send a prompt and print the response
  chatgpt response                Print the last assistant response
  chatgpt messages                Print all messages in the conversation
  chatgpt new                     Start a new conversation
  chatgpt download [prefix]       Save code blocks, images, and files (default prefix: chatgpt)
  chatgpt stop                    Stop the server + close browser
  chatgpt status                  Check if server is running
  chatgpt url                     Print the current conversation URL

Examples:
  chatgpt start
  chatgpt send "Write a Python function to reverse a string"
  chatgpt send "Now add type hints"
  chatgpt messages
  chatgpt download my_project
  chatgpt stop
"""


def main():
    """CLI entry point."""
    args = sys.argv[1:]

    if not args:
        print(USAGE)
        sys.exit(0)

    cmd = args[0]

    if cmd == "start":
        cmd_start()
    elif cmd == "send":
        cmd_send(args)
    elif cmd == "response":
        cmd_response()
    elif cmd == "messages":
        cmd_messages()
    elif cmd == "new":
        cmd_new()
    elif cmd == "download":
        cmd_download(args)
    elif cmd == "stop":
        cmd_stop()
    elif cmd == "status":
        cmd_status()
    elif cmd == "url":
        cmd_url()
    elif cmd in ("help", "--help", "-h"):
        print(USAGE)
    else:
        print(f"Unknown command: {cmd}")
        print(USAGE)
        sys.exit(1)


def cmd_start():
    """Start the server in the background."""
    if srv.is_server_running():
        print("Server is already running.")
        result = srv.send_command({"cmd": "url"})
        if result.get("url"):
            print(f"URL: {result['url']}")
        return

    # Launch the server as a detached background process
    sys_exec = sys.executable
    log_file = srv.LOG_FILE

    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
        if hasattr(subprocess, "DETACHED_PROCESS"):
            creationflags |= subprocess.DETACHED_PROCESS
        with open(log_file, "wb") as log:
            subprocess.Popen(
                [sys_exec, "-m", "chatgpt_browser_use.server"],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                creationflags=creationflags,
                close_fds=True,
            )
    else:
        # Use setsid + nohup to fully detach from the parent process group
        # so the server survives even after the CLI process exits.
        subprocess.Popen(
            f"nohup {sys_exec} -m chatgpt_browser_use.server > {log_file} 2>&1 &",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    # Wait for the server to be ready (check for socket file)
    import time
    for _ in range(45):  # 45 seconds timeout (Chrome startup takes time)
        time.sleep(1)
        if srv.is_server_running():
            result = srv.send_command({"cmd": "url"})
            print("Server started.")
            if result.get("url"):
                print(f"URL: {result['url']}")
            return

    # Check if the log file has error info
    try:
        with open(log_file) as f:
            log_content = f.read()
        if log_content.strip():
            print(f"Server log:\n{log_content[:500]}")
    except FileNotFoundError:
        pass
    print("Server did not become ready within 45 seconds.")
    sys.exit(1)


def cmd_send(args: list):
    """Send a prompt to ChatGPT and print the response."""
    if len(args) < 2:
        print('Usage: chatgpt send "your prompt here"')
        print('Tip: for multi-line prompts, use a file: chatgpt send @filename')
        sys.exit(1)

    prompt_arg = " ".join(args[1:])

    # Check if it's a file reference (@path)
    if prompt_arg.startswith("@"):
        filepath = prompt_arg[1:]
        if not os.path.isfile(filepath):
            print(f"File not found: {filepath}")
            sys.exit(1)
        with open(filepath, "r", encoding="utf-8") as f:
            prompt = f.read()
    else:
        prompt = prompt_arg

    if not prompt.strip():
        print("Prompt is empty.")
        sys.exit(1)

    if not srv.is_server_running():
        print("Server not running. Start it with: chatgpt start")
        sys.exit(1)

    timeout = _send_timeout()
    print(
        "Sending prompt to ChatGPT... "
        f"(this may take a while; timeout {timeout} seconds)"
    )
    result = srv.send_command(
        {"cmd": "send", "prompt": prompt, "timeout": timeout},
        timeout=timeout + 120,
    )

    if result.get("error"):
        print(f"Error: {result['error']}")
        sys.exit(1)

    response = result.get("response", "")
    if response:
        print(response)
    else:
        print("(No response received. Try: chatgpt response)")


def cmd_response():
    """Print the last assistant response."""
    if not srv.is_server_running():
        print("Server not running. Start it with: chatgpt start")
        sys.exit(1)

    result = srv.send_command({"cmd": "response"})
    if result.get("error"):
        print(f"Error: {result['error']}")
        sys.exit(1)

    response = result.get("response", "")
    if response:
        print(response)
    else:
        print("(No response yet. Send a prompt first: chatgpt send \"hello\")")


def _send_timeout() -> int:
    """Return the CLI send timeout in seconds."""
    raw = os.environ.get("CHATGPT_BROWSER_USE_SEND_TIMEOUT")
    if not raw:
        return srv.DEFAULT_SEND_TIMEOUT
    try:
        timeout = int(raw)
    except ValueError:
        print(
            "Ignoring invalid CHATGPT_BROWSER_USE_SEND_TIMEOUT; "
            f"using {srv.DEFAULT_SEND_TIMEOUT} seconds."
        )
        return srv.DEFAULT_SEND_TIMEOUT
    if timeout <= 0:
        print(
            "Ignoring non-positive CHATGPT_BROWSER_USE_SEND_TIMEOUT; "
            f"using {srv.DEFAULT_SEND_TIMEOUT} seconds."
        )
        return srv.DEFAULT_SEND_TIMEOUT
    return timeout


def cmd_messages():
    """Print all messages in the conversation."""
    if not srv.is_server_running():
        print("Server not running. Start it with: chatgpt start")
        sys.exit(1)

    result = srv.send_command({"cmd": "messages"})
    if result.get("error"):
        print(f"Error: {result['error']}")
        sys.exit(1)

    messages = result.get("messages", [])
    if not messages:
        print("(No messages in conversation)")
        return

    for msg in messages:
        role = msg.get("role", "?")
        text = msg.get("text", "")
        # Truncate very long messages for display
        if len(text) > 500:
            text = text[:500] + "..."
        print(f"[{role.upper()}]")
        print(text)
        print()


def cmd_new():
    """Start a new conversation."""
    if not srv.is_server_running():
        print("Server not running. Start it with: chatgpt start")
        sys.exit(1)

    result = srv.send_command({"cmd": "new"})
    if result.get("error"):
        print(f"Error: {result['error']}")
        sys.exit(1)

    print("New conversation started.")


def cmd_download(args: list):
    """Download code blocks and artifacts from the conversation."""
    if not srv.is_server_running():
        print("Server not running. Start it with: chatgpt start")
        sys.exit(1)

    prefix = args[1] if len(args) > 1 else "chatgpt"
    result = srv.send_command({"cmd": "download", "prefix": prefix})
    if result.get("error"):
        print(f"Error: {result['error']}")
        sys.exit(1)

    files = result.get("files", [])
    if files:
        print(f"Saved {len(files)} artifact(s):")
        for f in files:
            print(f"  {f}")
    else:
        print("No code blocks, images, or downloadable files found in the conversation.")


def cmd_stop():
    """Stop the server and close the browser."""
    if not srv.is_server_running():
        print("Server is not running.")
        # Clean up stale files
        for path in [srv.SOCKET_PATH, srv.PID_FILE]:
            if os.path.exists(path):
                os.unlink(path)
        return

    result = srv.send_command({"cmd": "stop"}, timeout=10)
    print("Server stopped.")

    # Clean up stale files
    for path in [srv.SOCKET_PATH, srv.PID_FILE]:
        if path and os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                pass


def cmd_status():
    """Check if the server is running."""
    if srv.is_server_running():
        print("Server is running.")
        result = srv.send_command({"cmd": "url"})
        if result.get("url"):
            print(f"URL: {result['url']}")
    else:
        print("Server is not running.")
        print("Start it with: chatgpt start")


def cmd_url():
    """Print the current conversation URL."""
    if not srv.is_server_running():
        print("Server not running. Start it with: chatgpt start")
        sys.exit(1)

    result = srv.send_command({"cmd": "url"})
    if result.get("error"):
        print(f"Error: {result['error']}")
        sys.exit(1)

    url = result.get("url", "")
    if url:
        print(url)
    else:
        print("(No URL available)")


if __name__ == "__main__":
    main()
