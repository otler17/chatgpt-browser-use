"""Example 3: CLI usage — no Python needed.

This file documents the CLI commands. To actually run them,
use the `chatgpt` command in your terminal (after pip install).

The CLI is designed for LLM agents that can run shell commands but
don't know Python. 7 commands, no flags, no options.
"""

# --- CLI Quick Reference (for LLM agents) ---
#
# 1. Start the server (launches browser, connects to ChatGPT):
#      chatgpt start
#
# 2. Send a prompt and get the response:
#      chatgpt send "What is the capital of France?"
#
# 3. Send a multi-line prompt from a file:
#      chatgpt send @prompt.txt
#
# 4. Get the last response (without sending a new message):
#      chatgpt response
#
# 5. See all messages in the conversation:
#      chatgpt messages
#
# 6. Start a new conversation:
#      chatgpt new
#
# 7. Download code blocks from the conversation:
#      chatgpt download my_project
#
# 8. Get the conversation URL:
#      chatgpt url
#
# 9. Stop the server and close the browser:
#      chatgpt stop
#
# 10. Check if the server is running:
#      chatgpt status
#
# --- Typical LLM agent flow ---
#
# chatgpt start
# chatgpt send "Write a Python script that..."
# chatgpt download my_script
# chatgpt send "Now add error handling"
# chatgpt download my_script_v2
# chatgpt stop
#
# That's the entire API. No browser-use commands, no CDP, no ProseMirror,
# no execCommand, no Xvfb, no pitfalls. Just send and receive.

if __name__ == "__main__":
    print(__doc__)