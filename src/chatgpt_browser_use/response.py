"""Response — wait for and extract ChatGPT responses.

Handles all the response-related pitfalls internally:
- Streaming: poll until content stabilizes
- Empty assistant bubble → reload and re-check (UI render race)
- Stop button detection as secondary signal
- Conversation URL bookmarking
- Timeout handling
"""

from __future__ import annotations

import asyncio
import json
import time

from .browser import CDPClient

# Shared JavaScript helpers for extracting text plus non-text artifacts.
_MESSAGE_HELPERS_JS = r"""
function artifactInfo(msg) {
  const images = [];
  const files = [];
  const buttons = [];
  const seenImages = new Set();
  const seenFiles = new Set();
  const fileExt = /\.(png|jpe?g|webp|gif|svg|pdf|csv|xlsx?|docx?|pptx?|zip|7z|rar|tar|gz|json|txt|md|py|js|ts|html|css|xml|yaml|yml|mp3|wav|ogg|m4a|flac|aac|mp4|webm|mov|avi|mkv)\b/i;
  const privateFileUrl = /oaiusercontent|\/download|\/files\/|\/backend-api\/estuary\/content/i;

  const isVisible = (el) => {
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };

  const looksLikeFileUrl = (url, text = '', download = '') =>
    !!download ||
    /^blob:|^data:/i.test(url) ||
    privateFileUrl.test(url) ||
    fileExt.test(url) ||
    fileExt.test(text);

  for (const img of msg.querySelectorAll('img')) {
    const src = img.currentSrc || img.src || img.getAttribute('src') || '';
    if (!src) continue;
    const rect = img.getBoundingClientRect();
    const bigEnough = rect.width >= 64 && rect.height >= 64;
    const likelyGenerated = /oaiusercontent|blob:|data:image|\/files\/|\/backend-api\/estuary\/content/i.test(src);
    if (!bigEnough && !likelyGenerated) continue;
    if (seenImages.has(src)) continue;
    seenImages.add(src);
    images.push({
      url: src,
      alt: img.alt || '',
      width: img.naturalWidth || Math.round(rect.width),
      height: img.naturalHeight || Math.round(rect.height)
    });
  }

  for (const media of msg.querySelectorAll('audio, video, audio source, video source')) {
    const src = media.currentSrc || media.src || media.getAttribute('src') || '';
    if (!src || !looksLikeFileUrl(src)) continue;
    if (seenFiles.has(src)) continue;
    seenFiles.add(src);
    const container = media.closest('audio, video') || media;
    const tag = container.tagName.toLowerCase();
    files.push({
      url: src,
      text: container.getAttribute('aria-label') || '',
      filename: '',
      kind: tag === 'video' ? 'video' : 'audio'
    });
  }

  for (const embedded of msg.querySelectorAll('embed[src], object[data], iframe[src]')) {
    const href = embedded.getAttribute('src') || embedded.getAttribute('data') || '';
    const text = embedded.getAttribute('title') || '';
    if (!href || !looksLikeFileUrl(href, text)) continue;
    if (seenFiles.has(href)) continue;
    seenFiles.add(href);
    files.push({url: href, text, filename: text, kind: 'file'});
  }

  for (const link of msg.querySelectorAll('a[href]')) {
    const href = link.href || link.getAttribute('href') || '';
    const text = (link.innerText || link.textContent || '').trim();
    const download = link.getAttribute('download') || '';
    if (!href || !looksLikeFileUrl(href, text, download)) continue;
    if (seenFiles.has(href)) continue;
    seenFiles.add(href);
    files.push({url: href, text, filename: download});
  }

  for (const button of msg.querySelectorAll('button')) {
    const label = (
      button.getAttribute('aria-label') ||
      button.innerText ||
      button.textContent ||
      ''
    ).trim();
    if (/download|save|open file|view file|télécharger/i.test(label) && isVisible(button)) {
      buttons.push({label});
    }
  }

  return {images, files, buttons};
}

function textForMessage(msg) {
  const role = msg.getAttribute('data-message-author-role') || '';
  let content = msg.querySelector('[data-message-content], .markdown');
  if (!content && role !== 'assistant') {
    content = msg;
  }
  const text = ((content && (content.innerText || content.textContent)) || '').trim();
  if (text) return text;

  const artifacts = artifactInfo(msg);
  const parts = [];
  if (artifacts.images.length) {
    parts.push(`[${artifacts.images.length} image${artifacts.images.length === 1 ? '' : 's'} available]`);
  }
  if (artifacts.files.length) {
    parts.push(`[${artifacts.files.length} file${artifacts.files.length === 1 ? '' : 's'} available]`);
  }
  if (artifacts.buttons.length) {
    parts.push(`[${artifacts.buttons.length} downloadable item${artifacts.buttons.length === 1 ? '' : 's'} available]`);
  }
  return parts.join(' ');
}
"""


# Count assistant messages and generated artifacts that may render outside the
# normal assistant-message DOM.
_COUNT_JS = """(() => {
  %s
  const artifacts = artifactInfo(document);
  return document.querySelectorAll('[data-message-author-role="assistant"]').length +
    artifacts.images.length +
    artifacts.files.length;
})()""" % _MESSAGE_HELPERS_JS


# Get the last assistant response text
_LAST_RESPONSE_JS = """(() => {
  %s
  const msgs = document.querySelectorAll('[data-message-author-role="assistant"]');
  if (msgs.length) {
    const last = msgs[msgs.length - 1];
    const text = textForMessage(last);
    if (text) return text;
  }

  const artifacts = artifactInfo(document);
  const parts = [];
  if (artifacts.images.length) {
    parts.push(`[${artifacts.images.length} image${artifacts.images.length === 1 ? '' : 's'} available]`);
  }
  if (artifacts.files.length) {
    parts.push(`[${artifacts.files.length} file${artifacts.files.length === 1 ? '' : 's'} available]`);
  }
  if (artifacts.buttons.length) {
    parts.push(`[${artifacts.buttons.length} downloadable item${artifacts.buttons.length === 1 ? '' : 's'} available]`);
  }
  return parts.join(' ');
})()""" % _MESSAGE_HELPERS_JS

# Get ALL messages (user + assistant)
_ALL_MESSAGES_JS = """(() => {
  %s
  const results = [];
  const globalArtifacts = artifactInfo(document);
  let messageImages = 0;
  let messageFiles = 0;
  const msgs = document.querySelectorAll('[data-message-author-role]');
  for (const msg of msgs) {
    const role = msg.getAttribute('data-message-author-role');
    const text = textForMessage(msg);
    const artifacts = artifactInfo(msg);
    if (
      role === 'assistant' &&
      !text &&
      !artifacts.images.length &&
      !artifacts.files.length &&
      !artifacts.buttons.length
    ) {
      continue;
    }
    messageImages += artifacts.images.length;
    messageFiles += artifacts.files.length;
    results.push({role: role, text: text, artifacts: artifacts});
  }
  if (
    globalArtifacts.images.length > messageImages ||
    globalArtifacts.files.length > messageFiles
  ) {
    const parts = [];
    const extraImages = Math.max(0, globalArtifacts.images.length - messageImages);
    const extraFiles = Math.max(0, globalArtifacts.files.length - messageFiles);
    if (extraImages) {
      parts.push(`[${extraImages} image${extraImages === 1 ? '' : 's'} available]`);
    }
    if (extraFiles) {
      parts.push(`[${extraFiles} file${extraFiles === 1 ? '' : 's'} available]`);
    }
    results.push({role: 'assistant', text: parts.join(' '), artifacts: globalArtifacts});
  }
  return JSON.stringify(results);
})()""" % _MESSAGE_HELPERS_JS

# Check if ChatGPT is still generating (stop button visible)
_IS_GENERATING_JS = """(() => {
  const stopBtn = document.querySelector('button[data-testid="stop-button"]') ||
                  document.querySelector('button[aria-label="Stop answering"]');
  if (stopBtn && stopBtn.offsetParent !== null) return true;

  const turns = [...document.querySelectorAll('section[data-turn="assistant"]')];
  const lastTurn = turns[turns.length - 1];
  if (!lastTurn) return false;

  const hasRealContent = !!lastTurn.querySelector(
    '[data-message-content], .markdown p, .markdown li, .markdown pre, img, audio, video'
  );
  if (hasRealContent) return false;

  const text = (lastTurn.innerText || lastTurn.textContent || '').trim();
  return /thinking|thought|reasoning|réflexion|réfléchit|pensée/i.test(text);
})()"""

# Check if the submit button says "Send prompt" (idle) or "Stop answering" (generating)
_SUBMIT_STATE_JS = """(() => {
  const btn = document.querySelector('button[aria-label="Send prompt"]') ||
              document.querySelector('button[aria-label="Stop answering"]') ||
              document.querySelector('#composer-submit-button');
  return btn ? (btn.getAttribute('aria-label') || btn.textContent || '').trim() : 'unknown';
})()"""


async def count_assistant_messages(cdp: CDPClient) -> int:
    """Count existing assistant messages."""
    result = await cdp.evaluate(_COUNT_JS)
    return int(result) if result else 0


async def get_last_response(cdp: CDPClient) -> str:
    """Get the text of the last assistant response."""
    result = await cdp.evaluate(_LAST_RESPONSE_JS)
    return str(result).strip() if result else ""


async def get_all_messages(cdp: CDPClient) -> list[dict]:
    """Get all messages in the current conversation as [{role, text}, ...]."""
    result = await cdp.evaluate(_ALL_MESSAGES_JS)
    if not result:
        return []
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return []
    return result if isinstance(result, list) else []


async def is_generating(cdp: CDPClient) -> bool:
    """Check if ChatGPT is still generating a response."""
    result = await cdp.evaluate(_IS_GENERATING_JS)
    return bool(result)


async def get_submit_state(cdp: CDPClient) -> str:
    """Get the submit button state: 'Send prompt' (idle) or 'Stop answering' (generating)."""
    result = await cdp.evaluate(_SUBMIT_STATE_JS)
    return str(result).strip() if result else "unknown"


async def get_conversation_url(cdp: CDPClient) -> str:
    """Get the current conversation URL (for bookmarking)."""
    result = await cdp.evaluate("window.location.href")
    return str(result) if result else ""


async def wait_for_response(
    cdp: CDPClient,
    prev_count: int | None = None,
    timeout: int = 300,
    stable_interval: int = 3,
    poll_interval: float = 1.0,
) -> str:
    """Wait for ChatGPT to finish responding and return the response text.

    This handles:
    - Detecting a new assistant message (prev_count + 1)
    - Waiting for streaming content to stabilize
    - Empty bubble → page reload + retry (UI render race)
    - Stop button as secondary completion signal

    Args:
        cdp: Connected CDPClient
        prev_count: Assistant message count before sending (auto-detected if None)
        timeout: Max seconds to wait (default 5 min — big prompts take long)
        stable_interval: Number of consecutive stable reads to consider done
        poll_interval: Seconds between polls

    Returns: The response text, or empty string on timeout.
    """
    if prev_count is None:
        prev_count = await count_assistant_messages(cdp)

    target_count = prev_count + 1
    deadline = time.time() + timeout
    last_content = ""
    stable_hits = 0
    reloaded = False

    # Phase 1: Wait for new assistant message to appear
    while time.time() < deadline:
        count = await count_assistant_messages(cdp)
        if count >= target_count:
            break
        await asyncio.sleep(poll_interval)
    else:
        return last_content  # Timeout — no new message appeared

    # Phase 2: Wait for content to stabilize
    while time.time() < deadline:
        current = await get_last_response(cdp)
        generating = await is_generating(cdp)

        if current and current == last_content and len(current) > 0:
            stable_hits += 1
            if stable_hits >= stable_interval and not generating:
                return current
        else:
            stable_hits = 0
            last_content = current

        # Secondary signal: stop button gone + some stable reads
        if not generating and stable_hits >= 2:
            return current or last_content

        # Empty bubble recovery: if content is empty and we're past 30s
        # with no stop button, reload the page (UI render race)
        elapsed = timeout - (deadline - time.time())
        if (
            not current
            and not generating
            and elapsed > 30
            and not reloaded
        ):
            await cdp.send("Page.navigate", {"url": "https://chatgpt.com"})
            await asyncio.sleep(5)
            # Re-navigate to the conversation if we had a URL
            # (the navigation above may have gone to the home page)
            reloaded = True
            stable_hits = 0
            # After reload, re-check the message count
            new_count = await count_assistant_messages(cdp)
            if new_count >= target_count:
                current = await get_last_response(cdp)
                if current:
                    last_content = current

        await asyncio.sleep(poll_interval)

    return last_content  # Timeout


async def navigate_to_chat(cdp: CDPClient, url: str = "https://chatgpt.com"):
    """Navigate to a ChatGPT URL and wait for the composer to load."""
    await cdp.send("Page.navigate", {"url": url})
    await asyncio.sleep(5)

    # Wait for the composer to appear
    from .composer import wait_for_ready
    await wait_for_ready(cdp, timeout=30)


async def reload_page(cdp: CDPClient):
    """Reload the page (for empty-bubble recovery)."""
    await cdp.evaluate("location.reload()")
    await asyncio.sleep(5)
