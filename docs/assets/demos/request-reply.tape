Output request-reply.gif
# Run through scripts/demos/record.py for an isolated Carrier service.
Set Shell "bash"
Set Width 1280
Set Height 800
Set FontFamily "Noto Sans Mono"
Set FontSize 22
Set Padding 24
Set Margin 12
Set MarginFill "#edf2fa"
Set BorderRadius 10
Set WindowBar Colorful
Set CursorBlink false
Set Framerate 15
Set TypingSpeed 22ms
Set WaitTimeout 20s
Set Theme { "name": "Carrier", "black": "#16243b", "red": "#ff8f9c", "green": "#81dcb8", "yellow": "#f5d586", "blue": "#559fff", "magenta": "#bca8ff", "cyan": "#70d8f3", "white": "#dce7f7", "brightBlack": "#92a8c7", "brightRed": "#ffafba", "brightGreen": "#a5efd3", "brightYellow": "#ffe6ab", "brightBlue": "#9ac4ff", "brightMagenta": "#d6c8ff", "brightCyan": "#b7ecfa", "brightWhite": "#ffffff", "background": "#0e1b2f", "foreground": "#dce7f7", "selection": "#24446e", "cursor": "#70d8f3" }
Hide
Type@1ms `cd "$CARRIER_RECORDING_WORKSPACE"; PS1='carrier $ '; unset PROMPT_COMMAND; set +o history; clear`
Enter
Wait+Line /carrier \$$/
Type@1ms "python -m asyncio"
Enter
Wait+Line />>>$/
Type@1ms `import os; from carrier import Client`
Enter
Wait+Line />>>$/
Type@1ms `requester = Client(url=os.environ["CARRIER_URL"], credentials=".carrier/requester.json")`
Enter
Wait+Line />>>$/
Type@1ms `reviewer = Client(url=os.environ["CARRIER_URL"], credentials=".carrier/reviewer.json")`
Enter
Wait+Line />>>$/
Ctrl+l
Show
Type "# Two authenticated inboxes. A real Python SDK exchange."
Enter
Sleep 2s
Type `question = await requester.send("Review change 42?", to="demo/reviewer")`
Enter
Wait+Line />>>$/
Type `incoming = (await reviewer.receive_pending()).messages[0]`
Enter
Wait+Line />>>$/
Type `print(f"Reviewer received #{incoming.id}: {incoming.content}")`
Enter
Wait+Screen /Reviewer received #1: Review change 42\?/
Sleep 5s
Type `reply = await incoming.reply("Ready to review.")`
Enter
Wait+Line />>>$/
Type `answer = await requester.wait_for_reply(question, timeout=5)`
Enter
Wait+Line />>>$/
Type `print(f"Reply to #{answer.reply_to}: {answer.content}")`
Enter
Wait+Screen /Reply to #1: Ready to review\./
Sleep 5s
Type "# Reading and replying have not acknowledged either message."
Enter
Type `print("Accepted:", incoming.acknowledged_at, answer.acknowledged_at)`
Enter
Wait+Screen /Accepted: None None/
Sleep 4s
Ctrl+l
Type "# Accept each message explicitly; keep the conversation history."
Enter
Type `request_ack = await incoming.ack()`
Enter
Wait+Line />>>$/
Type `reply_ack = await answer.ack()`
Enter
Wait+Line />>>$/
Type `print("Request:", request_ack["status"], "| Reply:", reply_ack["status"])`
Enter
Wait+Screen /Request: acknowledged \| Reply: acknowledged/
Type `print("Reviewer history:", len((await reviewer.receive()).messages))`
Enter
Wait+Screen /Reviewer history: 1/
Type `print("Requester history:", len((await requester.receive()).messages))`
Enter
Wait+Screen /Requester history: 1/
Sleep 7s
Screenshot request-reply-poster.png
Hide
Type@1ms "await requester.close(); await reviewer.close(); exit()"
Enter
Wait+Line /carrier \$$/
Hide
Type@1ms "touch recording-complete"
Enter
Wait+Line /carrier \$$/
