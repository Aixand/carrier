# Choose a Carrier example

Start with [SDK setup and isolated inboxes](../guides/example-setup.md). Examples
use real Carrier storage and transport. Manager fixtures and live providers are
identified separately.

## Learn the messaging contract

| Goal | Example | Proves |
| --- | --- | --- |
| First exchange | [Quick start](../quickstart.md) | Request, correlated reply and explicit acknowledgments |
| Background worker | [CI report](request-report.md) | JSON protocol and sequential consumer |
| Producer recovery | [Retry-safe event](retry-safe-send.md) | Same key returns the original stored message |
| Consumer recovery | [Offline archiver](offline-recovery.md) | Pagination and commit-before-ack |
| Agent tool transport | [MCP exchange](mcp-exchange.md) | Real stdio tools; no model needed |

## Compose Manager Suite

| Goal | Example | Provider requirement |
| --- | --- | --- |
| Send prepared task content | [Prompt handoff](prompt-handoff.md) | None |
| Publish checked work | [Skill result](skill-result.md) | None; application executes trusted fixture |
| Prepare an agent's tools | [MCP definition](mcp-definition.md) | None; resolution only |
| Publish retained-turn evidence | [Conversation result](conversation-result.md) | Injected offline fixture |
| Keep the backend alive | [Persistent service](persistent-service.md) | Undercurrent daemon; no model |
| Ask a program to do work | [Managed API caller](managed-api-caller.md) | Authenticated Codex and prepared HTTP worker |
| Separate production and acceptance | [Worker and reviewer](agentic-review.md) | Authenticated Codex; independent artifact check |

Use [integration ownership](../integrations/manager-suite.md) to choose APIs.
A stored message, an acknowledgment, a running process and an accepted business
result are different observations. Each example names its own success check.
