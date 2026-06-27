"""Example 2: Multi-line prompt — send a complex spec.

Shows that multi-line prompts work correctly.
The library handles all the ProseMirror/execCommand complexity internally.
"""

from chatgpt_browser_use import ChatGPT


def main():
    bot = ChatGPT()

    with bot:
        # A multi-line prompt with newlines, indentation, and special chars
        prompt = """Write a Python function called `parse_config` that:
1. Reads a YAML file from a given path
2. Validates it against a schema (keys: name, version, items)
3. Returns a dict with the parsed config
4. Raises ValueError if validation fails

Include type hints and a docstring. Just the function, no explanation."""

        print("Sending multi-line prompt...")
        reply = bot.send(prompt)
        print(f"Response:\n{reply}")

        # Download the code blocks
        files = bot.download(prefix="parse_config")
        print(f"\nDownloaded {len(files)} files:")
        for f in files:
            print(f"  {f}")


if __name__ == "__main__":
    main()