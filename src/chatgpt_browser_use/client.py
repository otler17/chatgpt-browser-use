"""ChatGPT — the single class small LLMs interact with.

This is the ONLY file an LLM agent needs to understand.

Usage (Python):
    from chatgpt_browser_use import ChatGPT

    bot = ChatGPT()
    bot.start()              # Launch browser + connect to ChatGPT
    reply = bot.send("Hi!")  # Send a message, wait for response
    print(reply)
    bot.stop()               # Clean up

Usage (CLI — even simpler, no Python knowledge needed):
    chatgpt start            # Start the server
    chatgpt send "Hi!"       # Send a message
    chatgpt response         # Get the last response
    chatgpt stop             # Stop the server

That's it. Five Python methods. Seven CLI commands.
No pitfalls to know about. No browser-use commands to memorize.
No ProseMirror, no execCommand, no CDP, no Xvfb.
Just send a prompt, get a response.

Design principles for small local LLMs:
1. MINIMAL API SURFACE — 5 methods, 7 CLI commands. Nothing else.
2. NO PITFALL AWARENESS — all 27 documented pitfalls handled internally.
3. LINEAR FLOW — start → send → response → stop. No branching, no retries,
   no fallbacks the caller needs to know about.
4. CLEAR ERRORS — if something goes wrong, the error message says what to do,
   not what went wrong in CDP protocol internals.
5. ALWAYS RETURNS TEXT — send() returns the response string. No JSON, no
   dicts, no nested objects to parse. Just the text ChatGPT wrote.
6. IDEMPOTENT — calling start() twice is fine. Calling stop() twice is fine.
7. SYNCHRONOUS — no asyncio in the public API. The LLM doesn't need to
   know about event loops.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from typing import Optional

from .browser import BrowserLauncher, CDPClient
from . import composer, response, downloads


def _env_int(name: str, default: int) -> int:
    """Read a positive integer environment variable."""
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


DEFAULT_SEND_TIMEOUT = _env_int("CHATGPT_BROWSER_USE_SEND_TIMEOUT", 1800)


class ChatGPT:
    """Drive ChatGPT (chatgpt.com) from a real browser session.

    All you need:
        bot = ChatGPT()
        bot.start()
        reply = bot.send("your prompt here")
        bot.stop()
    """

    def __init__(
        self,
        cdp_port: int = 9222,
        user_data_dir: str | None = None,
        chromium_bin: str | None = None,
    ):
        """Create a ChatGPT instance.

        Args:
            cdp_port: Chrome remote debugging port (default 9222)
            user_data_dir: Chrome profile directory (default: snap Chromium dir)
            chromium_bin: Path to Chromium binary (auto-detected if None)
        """
        self._launcher = BrowserLauncher(
            cdp_port=cdp_port,
            user_data_dir=user_data_dir,
            chromium_bin=chromium_bin,
        )
        self._cdp: CDPClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = False
        self._last_url: str = ""

    def start(self) -> None:
        """Launch the browser and connect to ChatGPT.

        This starts Xvfb (if needed), Chrome (if needed), and connects CDP.
        If Chrome is already running on the CDP port, it just connects.

        Safe to call multiple times — if already started, does nothing.
        """
        if self._started:
            return

        # Run the async event loop in a background thread
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        self._cdp = self._run_async(self._launcher.start())

        # Navigate to chatgpt.com if not already there
        current_url = self._run_async(self._cdp.evaluate("window.location.href"))
        if current_url and "chatgpt.com" not in str(current_url).lower():
            self._run_async(response.navigate_to_chat, self._cdp)

        # Wait for the composer to be ready
        self._run_async(composer.wait_for_ready, self._cdp, timeout=30)
        self._started = True

    def send(self, prompt: str, timeout: int = DEFAULT_SEND_TIMEOUT) -> str:
        """Send a prompt to ChatGPT and return the response text.

        This is the main method. It:
        1. Pastes the prompt into the ChatGPT composer (handles multi-line)
        2. Clicks send
        3. Waits for the full response (handles streaming + empty bubble)
        4. Returns the response text as a string

        Args:
            prompt: The prompt text. Can be any length, any number of lines.
            timeout: Max seconds to wait for response (default 30 min, or
                CHATGPT_BROWSER_USE_SEND_TIMEOUT if set).

        Returns: The response text from ChatGPT.

        Raises:
            RuntimeError: If the browser isn't started or ChatGPT doesn't respond.
        """
        if not self._started or not self._cdp:
            raise RuntimeError("Call bot.start() first.")

        return self._run_async(
            self._send_async,
            prompt,
            timeout,
            _result_timeout=timeout + 120,
        )

    def response(self) -> str:
        """Get the last assistant response text (without sending a new message).

        Returns: The text of the last assistant message, or empty string.
        """
        if not self._cdp:
            return ""
        return self._run_async(response.get_last_response, self._cdp)

    def messages(self) -> list[dict]:
        """Get all messages in the current conversation.

        Returns: A list of {"role": "user"|"assistant", "text": "..."} dicts.
        """
        if not self._cdp:
            return []
        return self._run_async(response.get_all_messages, self._cdp)

    def new_chat(self) -> None:
        """Start a new conversation (navigate to chatgpt.com home)."""
        if not self._cdp:
            raise RuntimeError("Call bot.start() first.")
        self._run_async(response.navigate_to_chat, self._cdp, "https://chatgpt.com")
        self._run_async(composer.wait_for_ready, self._cdp, timeout=30)

    def download(self, prefix: str = "chatgpt", output_dir: str | None = None) -> list[str]:
        """Extract and save code blocks, generated images, and file links.

        Args:
            prefix: Filename prefix (e.g. "my_project" -> my_project_1.py)
            output_dir: Directory to save to (default: ~/chatgpt_downloads/)

        Returns: List of saved file paths.
        """
        if not self._cdp:
            return []
        return self._run_async(downloads.save_code_blocks, self._cdp, prefix, output_dir)

    def url(self) -> str:
        """Get the current conversation URL (useful for bookmarking).

        Returns: The current page URL, e.g. "https://chatgpt.com/c/<uuid>".
        """
        if not self._cdp:
            return ""
        url = self._run_async(response.get_conversation_url, self._cdp)
        self._last_url = url
        return url

    def stop(self) -> None:
        """Stop the browser and clean up.

        Safe to call multiple times.
        """
        if not self._started:
            return
        try:
            self._run_async(self._launcher.stop())
        except Exception:
            pass
        self._started = False
        self._cdp = None

        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        self._loop = None
        self._thread = None

    # --- Internal async methods ---

    async def _send_async(self, prompt: str, timeout: int) -> str:
        """Internal: send a prompt and wait for the response."""
        cdp = self._cdp

        # Get current assistant message count (to detect the new one)
        prev_count = await response.count_assistant_messages(cdp)

        # Paste the prompt into the composer
        paste_result = await composer.paste_prompt(cdp, prompt)
        if not paste_result.get("ok"):
            raise RuntimeError(
                f"Failed to paste prompt into ChatGPT: {paste_result.get('error')}\n"
                "Make sure you're on chatgpt.com and the page is loaded."
            )

        # Verify the paste worked (React state sync check)
        paste_ok = await composer.verify_paste(cdp, len(prompt))
        if not paste_ok:
            # Retry once — React sync sometimes needs a second attempt
            paste_result = await composer.paste_prompt(cdp, prompt)
            paste_ok = await composer.verify_paste(cdp, len(prompt))
            if not paste_ok:
                raise RuntimeError(
                    "Prompt was pasted into the DOM but the submit button "
                    "stayed disabled. This is a React sync issue. Try calling "
                    "bot.new_chat() and then bot.send() again."
                )

        # Click send
        send_result = await composer.click_send(cdp)
        if send_result == "no_send":
            raise RuntimeError(
                "Could not find or click the send button. "
                "The ChatGPT UI may have changed. Try bot.new_chat()."
            )

        # Bookmark the URL immediately (in case the page dies)
        self._last_url = await response.get_conversation_url(cdp)

        # Wait for the response
        reply = await response.wait_for_response(
            cdp, prev_count=prev_count, timeout=timeout
        )

        # Empty bubble recovery: if response is empty, reload and retry
        if not reply:
            await response.reload_page(cdp)
            await composer.wait_for_ready(cdp, timeout=30)
            reply = await response.get_last_response(cdp)

        return reply

    def _run_async(self, coro_or_func, *args, _result_timeout: float | None = 600, **kwargs):
        """Run an async function or coroutine on the background event loop.

        Accepts either:
        - A coroutine object (already created): _run_async(some_coro())
        - A callable that returns a coroutine: _run_async(some_async_func, arg1, arg2)
        """
        if asyncio.iscoroutine(coro_or_func):
            coro = coro_or_func
        elif callable(coro_or_func):
            coro = coro_or_func(*args, **kwargs)
        else:
            return coro_or_func  # Not a coroutine, return as-is

        if asyncio.iscoroutine(coro):
            future = asyncio.run_coroutine_threadsafe(coro, self._loop)
            return future.result(timeout=_result_timeout)
        return coro

    def _run_loop(self):
        """Run the event loop in the background thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    # Context manager support
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
