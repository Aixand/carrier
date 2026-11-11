Output mcp-exchange.gif
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
Show
Type "# Scripted MCP clients; real Carrier tools. No model calls."
Enter
Type "python mcp_exchange.py --pace 3"
Enter
Wait+Screen /Stored request #1/
Wait+Screen /Received: Review change 42\?/
Wait+Screen /Reply #2: Ready to review\./
Wait+Screen /Matched reply to request #1/
Wait+Screen /Request delivery: acknowledged/
Wait+Screen /Both messages accepted; history retained\./
Wait+Line /carrier \$$/
Sleep 9s
Screenshot mcp-exchange-poster.png
Hide
Type@1ms "touch recording-complete"
Enter
Wait+Line /carrier \$$/
