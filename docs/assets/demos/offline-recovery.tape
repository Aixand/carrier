Output offline-recovery.gif
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
Type "# Carrier is running; the event consumer is offline."
Enter
Type `python publish_build_event.py build-1842 --url "$CARRIER_URL"`
Enter
Wait+Screen /Message 1: stored/
Type `python publish_build_event.py build-1843 --url "$CARRIER_URL"`
Enter
Wait+Screen /Message 2: stored/
Type `python publish_build_event.py build-1844 --url "$CARRIER_URL"`
Enter
Wait+Screen /Message 3: stored/
Sleep 4s
Type "python inbox.py"
Enter
Wait+Screen /Pending events: 3/
Sleep 5s
Ctrl+l
Type "# Start the consumer. Read two-message pages; commit before ack."
Enter
Type `python archive_events.py --url "$CARRIER_URL" --page-size 2`
Enter
Wait+Screen /Accepted 3 pending event/
Sleep 5s
Type "# Run again: no pending work, no duplicate archived rows."
Enter
Type `python archive_events.py --url "$CARRIER_URL" --page-size 2`
Enter
Wait+Screen /Accepted 0 pending event/
Sleep 5s
Type "python inbox.py"
Enter
Wait+Screen /Pending events: 0/
Wait+Screen /Retained messages: 3/
Wait+Line /carrier \$$/
Sleep 7s
Screenshot offline-recovery-poster.png
Hide
Type@1ms "touch recording-complete"
Enter
Wait+Line /carrier \$$/
