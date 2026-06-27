# Baby-Step Guide

This guide assumes you are starting from this project folder:

```powershell
C:\Users\gasss\Downloads\Chatbrowser
```

The short version is:

1. Install the Python package.
2. Open the special Chrome profile once and log in to ChatGPT.
3. Start the `chatgpt` helper.
4. Send prompts from the terminal.
5. Stop the helper when done.

## Windows: First-Time Setup

### 1. Open PowerShell in the project folder

```powershell
cd C:\Users\gasss\Downloads\Chatbrowser
```

### 2. Create or use the virtual environment

If `.venv` already exists, use it:

```powershell
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run this instead:

```powershell
.\.venv\Scripts\python.exe --version
```

If `.venv` does not exist, create it:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

### 3. Log in to ChatGPT once

Run this command:

```powershell
& "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="$env:LOCALAPPDATA\chatgpt-browser-use\chrome-profile" https://chatgpt.com
```

Chrome will open.

In that Chrome window:

1. Log in to ChatGPT.
2. Make sure you can see the normal ChatGPT message box.
3. Close that Chrome window.

This saves your login cookies in the special project profile.

## Windows: Use It

### 1. Start the browser helper

```powershell
.\.venv\Scripts\chatgpt.exe start
```

Expected result:

```text
Server started.
URL: https://chatgpt.com/
```

### 2. Send a test message

```powershell
.\.venv\Scripts\chatgpt.exe send "Reply with exactly: OK"
```

Expected result:

```text
Sending prompt to ChatGPT... (this may take a while)
OK
```

### 3. Send a normal prompt

```powershell
.\.venv\Scripts\chatgpt.exe send "Write a Python function that adds two numbers."
```

The reply will print directly in PowerShell.

### 4. See the latest reply again

```powershell
.\.venv\Scripts\chatgpt.exe response
```

### 5. See the full conversation

```powershell
.\.venv\Scripts\chatgpt.exe messages
```

### 6. Start a new chat

```powershell
.\.venv\Scripts\chatgpt.exe new
```

### 7. Download code blocks, images, PDFs, ZIPs, audio, video, or files from the conversation

Ask ChatGPT for code, an image, a PDF, a ZIP, audio, video, or another downloadable file first, then run:

```powershell
.\.venv\Scripts\chatgpt.exe download my_project
```

Saved files go to:

```text
C:\Users\<your-user>\chatgpt_downloads
```

If ChatGPT generated an image-only reply, the terminal may show something like:

```text
[1 image available]
```

That is normal. Run `download` to save it.

### 8. Stop the helper

When you are done:

```powershell
.\.venv\Scripts\chatgpt.exe stop
```

Expected result:

```text
Server stopped.
```

## Daily Windows Routine

After the first-time setup, your normal flow is just:

```powershell
cd C:\Users\gasss\Downloads\Chatbrowser
.\.venv\Scripts\chatgpt.exe start
.\.venv\Scripts\chatgpt.exe send "Your prompt here"
.\.venv\Scripts\chatgpt.exe stop
```

## Multi-Line Prompts

Create a text file:

```powershell
notepad prompt.txt
```

Put your prompt in it, save, then run:

```powershell
.\.venv\Scripts\chatgpt.exe send @prompt.txt
```

## Long Tasks

By default, `chatgpt send` waits up to 30 minutes.

For a longer task, set a bigger timeout before sending:

```powershell
$env:CHATGPT_BROWSER_USE_SEND_TIMEOUT = "3600"
.\.venv\Scripts\chatgpt.exe send "Do a long task"
```

`3600` means one hour.

## Python Usage

Create a file named `try_chatgpt.py`:

```python
from chatgpt_browser_use import ChatGPT

bot = ChatGPT()
bot.start()

reply = bot.send("Reply with exactly: hello from Python")
print(reply)

bot.stop()
```

Run it:

```powershell
.\.venv\Scripts\python.exe try_chatgpt.py
```

## Troubleshooting

### Server is not running

Start it:

```powershell
.\.venv\Scripts\chatgpt.exe start
```

### ChatGPT asks you to log in

Run the login command again:

```powershell
& "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="$env:LOCALAPPDATA\chatgpt-browser-use\chrome-profile" https://chatgpt.com
```

Log in, close Chrome, then run:

```powershell
.\.venv\Scripts\chatgpt.exe start
```

### Port 9222 is already used

Close the Chrome window opened by this tool, then try again.

If it still happens, rebooting clears old Chrome debug processes.

### Stop did not close Chrome

Run:

```powershell
.\.venv\Scripts\chatgpt.exe stop
```

If Chrome is still open, close the Chrome window manually.

## Linux Quick Start

Install prerequisites:

```bash
sudo snap install chromium
sudo apt install xvfb
pip install -e .
```

Log in once:

```bash
DISPLAY=:99 /snap/bin/chromium --no-sandbox --user-data-dir=~/snap/chromium/common/chromium https://chatgpt.com
```

Use it:

```bash
chatgpt start
chatgpt send "Reply with exactly: OK"
chatgpt stop
```
