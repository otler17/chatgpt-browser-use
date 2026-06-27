"""Composer — text input and submission for ChatGPT's ProseMirror editor.

Handles all the text-input pitfalls internally:
- browser-use input sends \\n as Enter → we use execCommand instead
- Direct DOM mutation doesn't sync React → execCommand('insertText') per line
- Submit button disabled state → we verify enablement before clicking
- ProseMirror insertParagraph for line breaks
- Clear previous content before pasting
"""

from __future__ import annotations

import json
import asyncio

from .browser import CDPClient

# CSS selector for the ChatGPT prompt input
PROMPT_SELECTOR = "#prompt-textarea"
# Submit button selectors (try multiple — ChatGPT changes these)
SUBMIT_SELECTORS = [
    'button[aria-label="Send prompt"]',
    'button[data-testid="send-button"]',
    '#composer-submit-button',
]


# JavaScript that pastes multi-line text into the ProseMirror editor.
# This is the core of what makes multi-line prompts work.
# It uses execCommand('insertText') per line + insertParagraph between lines
# so that ProseMirror and React both sync correctly.
_PASTE_JS = """(() => {
  const t = document.querySelector('#prompt-textarea');
  if (!t) return JSON.stringify({ok: false, error: 'NO_TEXTAREA'});

  // Focus the editor
  t.focus();

  // Select all existing content and delete it
  const sel = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(t);
  sel.removeAllRanges();
  sel.addRange(range);
  document.execCommand('delete');

  // Read the text from the global variable
  const text = window.__CHATGPT_PASTE_TEXT;
  if (!text) return JSON.stringify({ok: false, error: 'NO_TEXT'});

  // Insert each line, with paragraph breaks between lines
  const lines = text.split('\\n');
  for (let i = 0; i < lines.length; i++) {
    if (i > 0) {
      document.execCommand('insertParagraph');
    }
    if (lines[i].length > 0) {
      document.execCommand('insertText', false, lines[i]);
    }
  }

  return JSON.stringify({
    ok: true,
    lines: lines.length,
    chars: text.length,
    domLen: t.textContent.length
  });
})()"""


# JavaScript to click the send button
_CLICK_SEND_JS = """(() => {
  const selectors = [
    'button[aria-label="Send prompt"]',
    'button[data-testid="send-button"]',
    '#composer-submit-button'
  ];
  for (const sel of selectors) {
    const btn = document.querySelector(sel);
    if (btn && !btn.disabled && btn.offsetParent !== null) {
      btn.click();
      return 'sent';
    }
  }
  // Fallback: simulate Enter key
  const el = document.querySelector('#prompt-textarea');
  if (el) {
    el.focus();
    el.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'Enter', code: 'Enter', keyCode: 13,
      bubbles: true, cancelable: true
    }));
    return 'enter_sent';
  }
  return 'no_send';
})()"""


# JavaScript to check the composer state
_STATE_JS = """(() => {
  const ta = document.querySelector('#prompt-textarea');
  if (!ta) return JSON.stringify({ready: false, text: '', submitDisabled: true});
  const text = ta.textContent || '';
  const btn = document.querySelector('button[aria-label="Send prompt"]') ||
              document.querySelector('#composer-submit-button');
  return JSON.stringify({
    ready: true,
    text: text.substring(0, 200),
    textLen: text.length,
    submitDisabled: btn ? btn.disabled : true,
    submitLabel: btn ? btn.getAttribute('aria-label') : null
  });
})()"""


async def wait_for_ready(cdp: CDPClient, timeout: int = 30) -> bool:
    """Wait until the ChatGPT composer is loaded and interactive."""
    deadline = __import__("time").time() + timeout
    while __import__("time").time() < deadline:
        result = await cdp.evaluate(_STATE_JS)
        if result:
            state = json.loads(result)
            if state.get("ready") and state.get("textLen", 0) >= 0:
                return True
        await asyncio.sleep(1)

    # Debug info on failure
    debug = await cdp.evaluate(
        "JSON.stringify({url: location.href, title: document.title, "
        "inputs: document.querySelectorAll('[contenteditable=true],textarea').length})"
    )
    raise TimeoutError(f"ChatGPT composer never became ready. Debug: {debug}")


async def paste_prompt(cdp: CDPClient, text: str) -> dict:
    """Paste a prompt (any length, any number of lines) into the ChatGPT composer.

    This is the ONLY safe way to input text. It handles:
    - Multi-line prompts (newlines become paragraph breaks, not Enter submits)
    - React/ProseMirror state sync (execCommand, not DOM mutation)
    - Clearing previous content

    Returns a dict with {ok, lines, chars, domLen} or {ok: false, error}.
    """
    # Set the text as a global variable, then run the paste script
    # json.dumps produces a valid JS string literal
    set_js = f"window.__CHATGPT_PASTE_TEXT = {json.dumps(text)}; true"
    await cdp.evaluate(set_js)

    result = await cdp.evaluate(_PASTE_JS)
    if not result:
        return {"ok": False, "error": "CDP returned empty"}

    if isinstance(result, str):
        return json.loads(result)
    return result


async def click_send(cdp: CDPClient) -> str:
    """Click the send button. Returns 'sent', 'enter_sent', or 'no_send'."""
    result = await cdp.evaluate(_CLICK_SEND_JS)
    return str(result) if result else "no_send"


async def get_composer_state(cdp: CDPClient) -> dict:
    """Get the current state of the composer (text, submit button status)."""
    result = await cdp.evaluate(_STATE_JS)
    if result:
        if isinstance(result, str):
            return json.loads(result)
        return result
    return {"ready": False}


async def verify_paste(cdp: CDPClient, expected_len: int) -> bool:
    """Verify that the pasted text is actually in the DOM and submit is enabled.

    This catches the React sync failure (pitfall #20) where text appears
    in the DOM but submit stays disabled.
    """
    state = await get_composer_state(cdp)
    actual_len = state.get("textLen", 0)
    submit_disabled = state.get("submitDisabled", True)

    # Allow small whitespace differences
    if actual_len >= expected_len - 5 and not submit_disabled:
        return True
    if actual_len >= expected_len - 5 and submit_disabled:
        # React didn't sync — retry the paste
        return False
    return False