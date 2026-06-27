"""Example 1: Basic usage — send a prompt and get a response.

The simplest possible usage. This is all a small LLM needs to know:

    from chatgpt_browser_use import ChatGPT

    bot = ChatGPT()
    bot.start()
    reply = bot.send("What is 2+2?")
    print(reply)
    bot.stop()
"""

from chatgpt_browser_use import ChatGPT


def main():
    # Create and start the bot
    bot = ChatGPT()

    # Use context manager for automatic cleanup
    with bot:
        print("Sending prompt to ChatGPT...")

        # Send a simple prompt
        reply = bot.send("What is 2+2? Just the number.")
        print(f"Response: {reply}")

        # Send a follow-up (same conversation)
        reply = bot.send("Now multiply that by 10. Just the number.")
        print(f"Follow-up: {reply}")

        # Get all messages
        all_msgs = bot.messages()
        print(f"\nConversation has {len(all_msgs)} messages:")
        for msg in all_msgs:
            print(f"  [{msg['role']}] {msg['text'][:80]}")

        # Get the conversation URL (for bookmarking)
        print(f"\nConversation URL: {bot.url()}")


if __name__ == "__main__":
    main()