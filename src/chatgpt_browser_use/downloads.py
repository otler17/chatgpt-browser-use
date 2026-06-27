"""Downloads — extract code blocks, generated images, and file links.

Handles:
- CodeMirror blocks (pre.cm-content) — ChatGPT's inline code canvas
- Standard pre > code blocks — fallback
- Generated images (<img>, blob:, data:, and signed http URLs)
- Audio/video media elements and embedded documents
- Downloadable file links/cards where ChatGPT exposes an href
- Button-only downloads where ChatGPT hides the URL behind a behavior button
- Language detection from wrapper text
- File extension mapping
"""

from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .browser import CDPClient

DEFAULT_DOWNLOAD_DIR = str(Path.home() / "chatgpt_downloads")

# JavaScript to extract all code blocks from the page
_EXTRACT_CODE_JS = """(() => {
  const results = [];

  // Method 1: CodeMirror blocks (ChatGPT's canvas/inline code)
  const cmBlocks = document.querySelectorAll('pre.cm-content');
  for (const pre of cmBlocks) {
    const code = pre.innerText || pre.textContent;
    if (!code || !code.trim()) continue;
    const wrapper = pre.closest('div.border') || pre.parentElement;
    const wrapperText = wrapper ? wrapper.innerText : '';
    const lines = wrapperText.split('\\n').filter(l => l.trim());
    let lang = 'txt';
    if (lines.length > 1 && lines[1].trim() === 'Run') {
      lang = lines[0].trim().toLowerCase();
    } else if (lines.length > 0 && lines[0].trim().length < 20) {
      const candidate = lines[0].trim().toLowerCase();
      if (['python','javascript','js','typescript','ts','java','c','cpp',
           'go','rust','ruby','bash','sh','sql','html','css','json',
           'yaml','xml','markdown','md','shell'].includes(candidate)) {
        lang = candidate;
      }
    }
    results.push({code: code.trim(), language: lang});
  }

  // Method 2: Standard pre > code blocks
  const stdBlocks = document.querySelectorAll('pre > code');
  for (const block of stdBlocks) {
    const text = block.innerText || block.textContent;
    if (!text || !text.trim()) continue;
    const classes = block.className || '';
    const langMatch = classes.match(/language-(\\w+)/);
    const lang = langMatch ? langMatch[1] : 'txt';
    if (!results.some(r => r.code === text.trim())) {
      results.push({code: text.trim(), language: lang});
    }
  }

  return JSON.stringify(results);
})()"""


# JavaScript to extract downloadable non-code artifacts from assistant messages.
# Blob/data URLs are converted in the browser so Python can save them directly.
_EXTRACT_ARTIFACTS_JS = r"""(async () => {
  const results = [];
  const seen = new Set();
  const fileExt = /\.(png|jpe?g|webp|gif|svg|pdf|csv|xlsx?|docx?|pptx?|zip|7z|rar|tar|gz|json|txt|md|py|js|ts|html|css|xml|yaml|yml|mp3|wav|ogg|m4a|flac|aac|mp4|webm|mov|avi|mkv)\b/i;
  const privateFileUrl = /oaiusercontent|\/download|\/files\/|\/backend-api\/estuary\/content/i;

  const add = (item) => {
    const key = `${item.kind}|${item.url || ''}|${(item.dataUrl || '').slice(0, 80)}`;
    if (seen.has(key)) return;
    seen.add(key);
    results.push(item);
  };

  const isVisible = (el) => {
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };

  const filenameFromUrl = (url) => {
    try {
      const parsed = new URL(url, window.location.href);
      const last = parsed.pathname.split('/').filter(Boolean).pop() || '';
      return decodeURIComponent(last);
    } catch {
      return '';
    }
  };

  const looksLikeFileUrl = (url, text = '', download = '') =>
    !!download ||
    /^blob:|^data:/i.test(url) ||
    privateFileUrl.test(url) ||
    fileExt.test(url) ||
    fileExt.test(text);

  const dataUrlFrom = async (url) => {
    try {
      if (url.startsWith('data:')) return url;
      const res = await fetch(url);
      if (!res.ok) return null;
      const blob = await res.blob();
      return await new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => resolve(null);
        reader.readAsDataURL(blob);
      });
    } catch {
      return null;
    }
  };

  const roots = [document];
  for (const msg of roots) {
    for (const img of msg.querySelectorAll('img')) {
      const src = img.currentSrc || img.src || img.getAttribute('src') || '';
      if (!src) continue;
      const rect = img.getBoundingClientRect();
      const bigEnough = rect.width >= 64 && rect.height >= 64;
      const likelyGenerated = /oaiusercontent|blob:|data:image|\/files\/|\/backend-api\/estuary\/content/i.test(src);
      if (!bigEnough && !likelyGenerated) continue;

      const dataUrl = (
        /^data:|^blob:/i.test(src) ||
        privateFileUrl.test(src)
      ) ? await dataUrlFrom(src) : null;
      add({
        kind: 'image',
        url: src,
        dataUrl,
        mime: dataUrl ? (dataUrl.match(/^data:([^;,]+)/) || [])[1] : '',
        filename: img.alt || filenameFromUrl(src) || 'image',
        alt: img.alt || '',
        width: img.naturalWidth || Math.round(rect.width),
        height: img.naturalHeight || Math.round(rect.height)
      });
    }

    for (const media of msg.querySelectorAll('audio, video, audio source, video source')) {
      const src = media.currentSrc || media.src || media.getAttribute('src') || '';
      if (!src || !looksLikeFileUrl(src)) continue;
      const container = media.closest('audio, video') || media;
      const tag = container.tagName.toLowerCase();
      const dataUrl = (
        /^data:|^blob:/i.test(src) ||
        privateFileUrl.test(src)
      ) ? await dataUrlFrom(src) : null;
      const mime = media.getAttribute('type') || (dataUrl ? (dataUrl.match(/^data:([^;,]+)/) || [])[1] : '');
      add({
        kind: tag === 'video' ? 'video' : 'audio',
        url: src,
        dataUrl,
        mime,
        filename: filenameFromUrl(src) || tag,
        text: container.getAttribute('aria-label') || ''
      });
    }

    for (const embedded of msg.querySelectorAll('embed[src], object[data], iframe[src]')) {
      const url = embedded.getAttribute('src') || embedded.getAttribute('data') || '';
      if (!url || !looksLikeFileUrl(url)) continue;
      const dataUrl = (
        /^data:|^blob:/i.test(url) ||
        privateFileUrl.test(url)
      ) ? await dataUrlFrom(url) : null;
      add({
        kind: 'file',
        url,
        dataUrl,
        mime: embedded.getAttribute('type') || (dataUrl ? (dataUrl.match(/^data:([^;,]+)/) || [])[1] : ''),
        filename: embedded.getAttribute('title') || filenameFromUrl(url) || 'file',
        text: embedded.getAttribute('title') || ''
      });
    }

    for (const link of msg.querySelectorAll('a[href]')) {
      const href = link.href || link.getAttribute('href') || '';
      const text = (link.innerText || link.textContent || '').trim();
      const download = link.getAttribute('download') || '';
      if (!href || !looksLikeFileUrl(href, text, download)) continue;

      const dataUrl = (
        /^data:|^blob:/i.test(href) ||
        privateFileUrl.test(href)
      ) ? await dataUrlFrom(href) : null;
      add({
        kind: 'file',
        url: href,
        dataUrl,
        mime: dataUrl ? (dataUrl.match(/^data:([^;,]+)/) || [])[1] : '',
        filename: download || text || filenameFromUrl(href) || 'file',
        text
      });
    }
  }

  return JSON.stringify(results);
})()"""


_DOWNLOAD_BUTTONS_JS = r"""(() => {
  const isVisible = (el) => {
    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };
  return JSON.stringify([...document.querySelectorAll('button')]
    .map((button, index) => ({
      index,
      inAssistant: !!button.closest('[data-message-author-role="assistant"], section[data-turn="assistant"]'),
      label: (
        button.getAttribute('aria-label') ||
        button.innerText ||
        button.textContent ||
        ''
      ).trim(),
      visible: isVisible(button)
    }))
    .filter((button) =>
      button.inAssistant &&
      button.visible &&
      /download|save|open file|view file|télécharger/i.test(button.label)
    ));
})()"""


_CLICK_DOWNLOAD_BUTTON_JS = r"""(() => {
  const wanted = window.__CHATGPT_DOWNLOAD_BUTTON_INDEX;
  const buttons = [...document.querySelectorAll('button')];
  const button = buttons[wanted];
  if (!button) return JSON.stringify({ok: false, error: 'NO_BUTTON'});
  button.scrollIntoView({block: 'center'});
  button.click();
  const label = (
    button.getAttribute('aria-label') ||
    button.innerText ||
    button.textContent ||
    ''
  ).trim();
  return JSON.stringify({ok: true, label});
})()"""

# Language → file extension map
EXT_MAP = {
    'python': 'py', 'py': 'py',
    'javascript': 'js', 'js': 'js',
    'typescript': 'ts', 'ts': 'ts',
    'html': 'html', 'css': 'css',
    'json': 'json', 'yaml': 'yaml', 'yml': 'yml',
    'bash': 'sh', 'sh': 'sh', 'shell': 'sh',
    'sql': 'sql', 'java': 'java', 'c': 'c', 'cpp': 'cpp',
    'go': 'go', 'rust': 'rs', 'ruby': 'rb',
    'markdown': 'md', 'md': 'md',
    'xml': 'xml', 'csv': 'csv',
    'dockerfile': 'dockerfile',
    'toml': 'toml', 'ini': 'ini',
}


def _get_extension(lang: str) -> str:
    return EXT_MAP.get(lang.lower(), 'txt')


def _safe_filename(value: str, fallback: str = "artifact") -> str:
    """Return a filesystem-safe filename stem or filename."""
    name = (value or "").strip().replace("\\", "/").split("/")[-1]
    name = urllib.parse.unquote(name)
    name = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", "_", name)
    name = re.sub(r"\s+", "_", name).strip("._ ")
    return name[:120] or fallback


def _extension_from_mime(mime: str) -> str:
    mime = (mime or "").split(";")[0].strip().lower()
    common = {
        "application/json": "json",
        "application/pdf": "pdf",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "application/x-zip-compressed": "zip",
        "application/zip": "zip",
        "audio/aac": "aac",
        "audio/flac": "flac",
        "audio/m4a": "m4a",
        "audio/mp4": "m4a",
        "audio/mpeg": "mp3",
        "audio/ogg": "ogg",
        "audio/wav": "wav",
        "audio/webm": "webm",
        "audio/x-wav": "wav",
        "image/jpeg": "jpg",
        "image/svg+xml": "svg",
        "text/csv": "csv",
        "text/html": "html",
        "text/markdown": "md",
        "text/plain": "txt",
        "video/mp4": "mp4",
        "video/ogg": "ogv",
        "video/quicktime": "mov",
        "video/webm": "webm",
        "video/x-matroska": "mkv",
    }
    if mime in common:
        return common[mime]
    ext = mimetypes.guess_extension(mime) if mime else None
    return (ext or ".bin").lstrip(".")


def _extension_from_url(url: str) -> str:
    try:
        path = urllib.parse.urlparse(url).path
    except Exception:
        return "bin"
    suffix = Path(path).suffix.lower().lstrip(".")
    return suffix or "bin"


def _unique_path(out_dir: Path, stem: str, ext: str) -> Path:
    path = out_dir / f"{stem}.{ext}"
    counter = 2
    while path.exists():
        path = out_dir / f"{stem}_{counter}.{ext}"
        counter += 1
    return path


def _save_data_url(data_url: str, path: Path) -> None:
    header, encoded = data_url.split(",", 1)
    if ";base64" in header:
        path.write_bytes(base64.b64decode(encoded))
    else:
        path.write_text(urllib.parse.unquote(encoded), encoding="utf-8")


def _download_url(url: str, path: Path) -> None:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 chatgpt-browser-use"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        path.write_bytes(resp.read())


def _download_snapshot(out_dir: Path) -> dict[Path, tuple[int, float]]:
    """Return stable metadata for files currently in the download directory."""
    snapshot = {}
    if not out_dir.exists():
        return snapshot
    for path in out_dir.iterdir():
        if path.is_file():
            stat = path.stat()
            snapshot[path] = (stat.st_size, stat.st_mtime)
    return snapshot


async def _wait_for_new_downloads(
    out_dir: Path,
    before: dict[Path, tuple[int, float]],
    timeout: int = 60,
) -> list[Path]:
    """Wait for Chrome downloads that appeared after a click to finish."""
    deadline = time.time() + timeout
    last_sizes: dict[Path, int] = {}
    stable_since: dict[Path, float] = {}

    while time.time() < deadline:
        files = [p for p in out_dir.iterdir() if p.is_file()]
        active = [p for p in files if p.name.endswith((".crdownload", ".tmp"))]
        changed = [
            p for p in files
            if not p.name.endswith((".crdownload", ".tmp"))
            and (p not in before or before[p] != (p.stat().st_size, p.stat().st_mtime))
        ]

        now = time.time()
        complete = []
        for path in changed:
            size = path.stat().st_size
            if last_sizes.get(path) == size:
                stable_since.setdefault(path, now)
                if now - stable_since[path] >= 0.75:
                    complete.append(path)
            else:
                last_sizes[path] = size
                stable_since[path] = now

        if complete and not active:
            return complete

        await asyncio.sleep(0.25)

    return []


async def _save_button_downloads(
    cdp: CDPClient,
    prefix: str,
    out_dir: Path,
) -> list[str]:
    """Click visible download buttons and collect browser-downloaded files."""
    try:
        await cdp.send("Page.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": str(out_dir),
        })
    except Exception:
        # Some Chromium builds do not expose this deprecated method; in that
        # case the button may still download to the browser's default folder.
        pass

    result = await cdp.evaluate(_DOWNLOAD_BUTTONS_JS)
    if not result:
        return []
    try:
        buttons = json.loads(result)
    except json.JSONDecodeError:
        return []

    saved = []
    for i, button in enumerate(buttons, start=1):
        before = _download_snapshot(out_dir)
        await cdp.evaluate(
            f"window.__CHATGPT_DOWNLOAD_BUTTON_INDEX = {int(button['index'])}; true"
        )
        click_result = await cdp.evaluate(_CLICK_DOWNLOAD_BUTTON_JS)
        try:
            clicked = json.loads(click_result) if click_result else {}
        except json.JSONDecodeError:
            clicked = {}
        if not clicked.get("ok"):
            continue

        new_files = await _wait_for_new_downloads(out_dir, before)
        for path in new_files:
            safe_name = _safe_filename(path.name, fallback="download")
            stem = Path(safe_name).stem or "download"
            ext = Path(safe_name).suffix.lstrip(".") or "bin"
            target = _unique_path(out_dir, f"{prefix}_download_{i}_{stem}", ext)
            try:
                path.rename(target)
                saved.append(str(target))
            except OSError:
                saved.append(str(path))

    return saved


async def extract_code_blocks(cdp: CDPClient) -> list[dict]:
    """Extract all code blocks from the current page.

    Returns a list of {code, language} dicts.
    """
    result = await cdp.evaluate(_EXTRACT_CODE_JS)
    if not result:
        return []
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return []
    return result if isinstance(result, list) else []


async def extract_artifacts(cdp: CDPClient) -> list[dict]:
    """Extract generated images and downloadable file links from the page."""
    result = await cdp.evaluate(_EXTRACT_ARTIFACTS_JS, await_promise=True)
    if not result:
        return []
    if isinstance(result, str):
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            return []
    return result if isinstance(result, list) else []


async def save_code_blocks(
    cdp: CDPClient,
    prefix: str = "chatgpt",
    output_dir: str | None = None,
) -> list[str]:
    """Extract and save all code blocks plus downloadable artifacts.

    Args:
        cdp: Connected CDPClient.
        prefix: Filename prefix (e.g. "my_project" -> my_project_1.py).
        output_dir: Directory to save files (default: ~/chatgpt_downloads/)

    Returns: List of saved file paths.
    """
    blocks = await extract_code_blocks(cdp)
    out_dir = Path(output_dir or DEFAULT_DOWNLOAD_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    saved = []
    for i, block in enumerate(blocks):
        ext = _get_extension(block.get("language", "txt"))
        fpath = out_dir / f"{prefix}_{i + 1}.{ext}"
        fpath.write_text(block["code"], encoding="utf-8")
        saved.append(str(fpath))

    unsaved = []
    artifacts = await extract_artifacts(cdp)
    for i, artifact in enumerate(artifacts, start=1):
        kind = artifact.get("kind", "artifact")
        raw_name = artifact.get("filename") or artifact.get("text") or kind
        safe_name = _safe_filename(raw_name, fallback=kind)
        stem = Path(safe_name).stem or f"{kind}_{i}"

        try:
            data_url = artifact.get("dataUrl") or ""
            url = artifact.get("url") or ""
            if data_url:
                mime = artifact.get("mime") or data_url.split(":", 1)[-1].split(";", 1)[0]
                ext = Path(safe_name).suffix.lstrip(".") or _extension_from_mime(mime)
                fpath = _unique_path(out_dir, f"{prefix}_{kind}_{i}_{stem}", ext)
                _save_data_url(data_url, fpath)
                saved.append(str(fpath))
            elif url.startswith(("http://", "https://")):
                ext = Path(safe_name).suffix.lstrip(".") or _extension_from_url(url)
                fpath = _unique_path(out_dir, f"{prefix}_{kind}_{i}_{stem}", ext)
                _download_url(url, fpath)
                saved.append(str(fpath))
            else:
                unsaved.append({**artifact, "error": "Unsupported artifact URL"})
        except Exception as exc:
            unsaved.append({**artifact, "error": str(exc)})

    if unsaved:
        fpath = _unique_path(out_dir, f"{prefix}_artifact_manifest", "json")
        fpath.write_text(json.dumps(unsaved, indent=2), encoding="utf-8")
        saved.append(str(fpath))

    saved.extend(await _save_button_downloads(cdp, prefix, out_dir))

    return saved
