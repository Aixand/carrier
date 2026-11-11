"""Messages retain their receiving client for explicit replies and acknowledgments."""
from dataclasses import dataclass, field
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .sdk import Client


@dataclass
class Message:
    id: int
    sender: str
    recipient: str
    content: str
    created_at: str
    idempotency_key: str | None
    reply_to: int | None
    acknowledged_at: str | None
    _client: "Client" = field(repr=False, compare=False)

    @classmethod
    def from_dict(cls, value, client):
        return cls(id=value["id"], sender=value["sender"], recipient=value["recipient"],
                   content=value["content"], created_at=value["created_at"],
                   idempotency_key=value.get("message_id"), reply_to=value.get("reply_to"),
                   acknowledged_at=value.get("acknowledged_at"), _client=client)

    def to_dict(self):
        """Return the HTTP/MCP representation (message_id is the retry key)."""
        return dict(id=self.id, sender=self.sender, recipient=self.recipient, content=self.content,
                    created_at=self.created_at, message_id=self.idempotency_key,
                    reply_to=self.reply_to, acknowledged_at=self.acknowledged_at)

    def json(self) -> Any:
        """Explicitly decode the text body; ordinary text is never auto-decoded."""
        return json.loads(self.content)

    async def ack(self):
        result = await self._client.ack(self.id)
        self.acknowledged_at = result["acknowledged_at"]
        return result

    async def reply(self, content: str, *, idempotency_key: str | None = None):
        """Send a correlated reply. This does not acknowledge this message."""
        if self._client.address != self.recipient:
            raise ValueError("Only a received message can be replied to")
        return await self._client.send(content, to=self.sender, reply_to=self.id,
                                       idempotency_key=idempotency_key)

    async def reply_json(self, content: Any, *, idempotency_key: str | None = None):
        return await self.reply(json.dumps(content, ensure_ascii=False, allow_nan=False, sort_keys=True),
                                idempotency_key=idempotency_key)


@dataclass
class MessagePage:
    messages: list[Message]
    next_after: int | None

    def to_dict(self):
        return {"messages": [message.to_dict() for message in self.messages], "next_after": self.next_after}


@dataclass
class WaitResult(MessagePage):
    status: str

    def to_dict(self):
        return {"status": self.status, **super().to_dict()}
