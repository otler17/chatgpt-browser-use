# chatgpt-browser-use

Drive ChatGPT (chatgpt.com) from a real browser session. **Designed for small local LLMs.**

New here? Start with the [baby-step guide](BABYSTEP_GUIDE.md).

## Why this exists

Automating ChatGPT through a browser has 27+ documented pitfalls — ProseMirror editors, React state sync, Cloudflare blocks, snap Chromium confinement, empty-bubble render races, streaming detection, and more. Small local LLMs (7B-14B) can't reason about all of these simultaneously. This library handles every pitfall internally so the LLM only needs to know 5 methods.

## Install

```bash
git clone https://github.com/otler17/chatgpt-browser-use.git
cd chatgpt-browser-use
pip install -e .
```

Prerequisites (one-time, Linux):
```bash
sudo snap install chromium    # or: pip install playwright && playwright install chromium
sudo apt install xvfb          # virtual display (for headless servers)
pip install websockets         # CDP communication
```

Prerequisites (one-time, Windows):
```powershell
# Python 3.10+ and Google Chrome or Microsoft Edge
py -3.11 -m pip install -e .
```

You also need to log into ChatGPT once manually in the browser profile used by this tool so the session cookies are saved.

Linux:
```bash
# Launch Chromium, go to chatgpt.com, log in, then close it
DISPLAY=:99 /snap/bin/chromium --no-sandbox --user-data-dir=~/snap/chromium/common/chromium https://chatgpt.com
```

Windows PowerShell:
```powershell
# Launch Chrome, go to chatgpt.com, log in, then close it
& "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="$env:LOCALAPPDATA\chatgpt-browser-use\chrome-profile" https://chatgpt.com
```

## Usage — Python (5 methods)

```python
from chatgpt_browser_use import ChatGPT

bot = ChatGPT()
bot.start()                          # Launch browser + connect
reply = bot.send("Hello!")           # Send prompt, get response
print(reply)

reply = bot.send("Follow up?")       # Continue conversation
print(reply)

msgs = bot.messages()                # Get all messages
url = bot.url()                      # Get conversation URL
bot.stop()                           # Clean up
```

That's the entire API. Five methods. No asyncio, no callbacks, no error handling the LLM needs to reason about.

### Context manager (auto cleanup)

```python
with ChatGPT() as bot:
    reply = bot.send("What is 2+2?")
    print(reply)
```

## Usage — CLI (7 commands)

For LLM agents that run shell commands:

```bash
chatgpt start                              # Launch browser
chatgpt send "Write a Python function"     # Send prompt, print response
chatgpt send @prompt.txt                   # Send multi-line prompt from file
chatgpt response                           # Get last response
chatgpt messages                           # See all messages
chatgpt new                                # Start new conversation
chatgpt download my_project                # Save code, images, PDFs, ZIPs, audio, video, and files
chatgpt stop                               # Close browser
```

### Typical agent flow

```bash
chatgpt start
chatgpt send "Write a Python script that fetches weather data"
chatgpt download weather_script
chatgpt send "Now add error handling and retry logic"
chatgpt download weather_script_v2
chatgpt stop
```

### Long-running prompts

`chatgpt send` waits up to 30 minutes by default. For longer tasks, set
`CHATGPT_BROWSER_USE_SEND_TIMEOUT` to the number of seconds you want:

```bash
CHATGPT_BROWSER_USE_SEND_TIMEOUT=3600 chatgpt send "Do a long task"
```

Windows PowerShell:

```powershell
$env:CHATGPT_BROWSER_USE_SEND_TIMEOUT = "3600"
.\.venv\Scripts\chatgpt.exe send "Do a long task"
```

## What pitfalls does this handle?

Everything. The LLM doesn't need to know about any of these:

1. **Cloudflare blocks** → real Chrome on Xvfb (never headless)
2. **Snap Chromium confinement** → correct user-data-dir
3. **ProseMirror editor** → execCommand('insertText') per line
4. **React state sync** → execCommand, not DOM mutation
5. **Multi-line prompts** → insertParagraph between lines (not Enter)
6. **Submit button disabled** → verification + retry after paste
7. **Empty response bubble** → auto-reload + re-check
8. **Long-running responses** → waits while ChatGPT is still generating
9. **Streaming detection** → content stabilization polling
10. **Stale SingletonLock** → auto-cleanup on startup
11. **CDP port not ready** → retry with timeout
12. **Conversation URL bookmarking** → bot.url() method
13. **Code block extraction** → CodeMirror + standard pre/code
14. **Image/file replies** → stable placeholders instead of empty-response crashes
15. **Language detection** → wrapper text parsing + class names
16. **Artifact downloads** → code, images, PDFs, ZIPs, audio, video, and files saved to ~/chatgpt_downloads/

## How it works

```
LLM agent
    │
    ├── Python: bot.send("prompt") ──────┐
    │                                     ├── ChatGPT class (5 methods)
    └── CLI: chatgpt send "prompt" ──────┘
                                              │
                    ┌─────────────────────────┴──────────────────────┐
                    │             Internal modules                     │
                    │                                                  │
                    │  browser.py    Chrome/Edge + CDP connection        │
                    │  composer.py   ProseMirror paste + submit         │
                    │  response.py   Streaming poll + empty-bubble fix  │
                    │  downloads.py  Code block extraction              │
                    │  server.py     Persistent socket server (CLI)     │
                    └──────────────────────────────────────────────────┘
                                              │
                                     Real Chromium browser
                                              │
                                      chatgpt.com (logged in)
```

## Configuration

```python
# Custom Chrome profile (e.g. if you have cookies elsewhere)
bot = ChatGPT(user_data_dir="/path/to/chrome/profile")

# Custom Chromium binary
bot = ChatGPT(chromium_bin="/usr/bin/google-chrome")

# Windows custom Chrome/Edge binary
bot = ChatGPT(chromium_bin=r"C:\Program Files\Google\Chrome\Application\chrome.exe")

# Custom CDP port (if 9222 is taken)
bot = ChatGPT(cdp_port=9333)
```

## Requirements

- Windows or Linux
- Chromium-family browser (Google Chrome, Microsoft Edge, Chromium, or Playwright Chromium)
- Xvfb on Linux (`sudo apt install xvfb`)
- Python 3.10+
- websockets (`pip install websockets`)
- ChatGPT account (free or Plus) — log in once manually

## License

MIT

## Why not just use browser-use / Playwright directly?

You can, but:

1. **browser-use CLI** has 27 documented pitfalls for ChatGPT specifically. Small LLMs hit each one and don't know how to recover.
2. **Playwright Python API** requires understanding CDP, ProseMirror, React state sync, and Cloudflare bypass. That's too much for a 7B model.
3. **Selenium** has similar issues plus weaker anti-detection.

This library is a thin wrapper that encodes all that knowledge into 5 methods. The LLM just calls `bot.send("prompt")` and gets back a string.
