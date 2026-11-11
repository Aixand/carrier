"""Async messaging and local consumers; no knowledge of the delivery target."""
import asyncio
import inspect
import json
import math
from pathlib import Path
from typing import Awaitable, Callable

import httpx

from .errors import (AuthenticationError, CarrierError, ConflictError, HTTPError,
                     ProtocolError, TransportError, UnacknowledgedMessage, UnsupportedFeatureError)
from .models import Message, MessagePage, WaitResult

Handler = Callable[[Message], Awaitable[None]]


def positive_seconds(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return value


class Client:
    """One authenticated mailbox. Context exit closes HTTP connections, not the service.

    Credentials must already exist. Each process/conversation needs its own identity;
    only one active reader may own an inbox. There are no automatic mutation retries.
    """

    def __init__(self, *, url="http://127.0.0.1:8765", credentials=None, token=None,
                 request_timeout=15.0, transport=None):
        if (credentials is None) == (token is None):
            raise ValueError("Supply exactly one of credentials or token")
        positive_seconds(request_timeout, "request_timeout")
        self._expected_address = None
        if credentials is not None:
            try:
                data = json.loads(Path(credentials).expanduser().read_text())
                token, self._expected_address = data["token"], data["address"]
                if not isinstance(self._expected_address, str) or not self._expected_address:
                    raise ValueError()
            except (OSError, ValueError, KeyError, TypeError):
                raise ValueError("Cannot load Carrier credentials; expected an existing address/token file") from None
        if not isinstance(token, str) or not token:
            raise ValueError("Carrier token must be a nonempty string")
        parsed = httpx.URL(url)
        if parsed.scheme not in ("http", "https") or not parsed.host or parsed.userinfo or parsed.query or parsed.fragment:
            raise ValueError("Carrier URL must be HTTP(S), without credentials, query, or fragment")
        self.url = str(parsed).rstrip("/")
        self._token = token
        self._request_timeout = request_timeout
        self._transport = transport
        self._http = None
        self._identity = None
        self._features = None
        self._opening = asyncio.Lock()
        self._closed = False
        self._handler = None
        self._consuming = False

    @property
    def address(self):
        if self._identity is None:
            raise CarrierError("Open the client before reading its authenticated address")
        return self._identity["address"]

    async def __aenter__(self):
        await self.open()
        return self

    async def __aexit__(self, *_):
        await self.close()

    async def open(self):
        async with self._opening:
            if self._closed:
                raise CarrierError("Carrier client is closed; create a new client")
            if self._identity is not None:
                return self
            if self._http is None:
                self._http = httpx.AsyncClient(base_url=self.url + "/", timeout=self._request_timeout,
                    trust_env=False, follow_redirects=False, transport=self._transport,
                    headers={"Authorization": f"Bearer {self._token}"})
            try:
                identity = await self._perform("GET", "/whoami")
                if not isinstance(identity.get("address"), str) or not identity["address"]:
                    raise ProtocolError("Carrier returned an invalid identity")
                if self._expected_address is not None and identity["address"] != self._expected_address:
                    raise AuthenticationError(401, "Credential address does not match the authenticated identity")
                self._identity = identity
            except BaseException:
                await self._http.aclose()
                self._http = None
                raise
            return self

    async def close(self):
        async with self._opening:
            self._closed = True
            if self._http is not None:
                await self._http.aclose()
                self._http = None

    async def _perform(self, method, path, **kwargs):
        try:
            response = await self._http.request(method, path.lstrip("/"), **kwargs)
        except httpx.RequestError:
            raise TransportError("Carrier service is unavailable or the request timed out; mutation delivery may be unknown") from None
        if not response.is_success:
            try:
                detail = response.json().get("detail", "Request failed")
            except (ValueError, AttributeError):
                detail = "Request failed"
            error = AuthenticationError if response.status_code in (401, 403) else ConflictError if response.status_code == 409 else HTTPError
            raise error(response.status_code, detail)
        try:
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except ValueError:
            raise ProtocolError("Carrier returned an invalid JSON object; mutation delivery may be unknown") from None

    async def _request(self, method, path, **kwargs):
        await self.open()
        return await self._perform(method, path, **kwargs)

    async def _require(self, feature):
        if self._features is None:
            try:
                info = await self._request("GET", "/capabilities")
            except HTTPError as error:
                if error.status_code != 404:
                    raise
                info = {}
            features = info.get("features", [])
            if not isinstance(features, list) or not all(isinstance(item, str) for item in features):
                raise ProtocolError("Carrier returned invalid capabilities")
            self._features = set(features)
        if feature not in self._features:
            raise UnsupportedFeatureError(f"Carrier service does not support {feature}; upgrade the service")

    async def whoami(self):
        return await self._request("GET", "/whoami")

    async def list_sessions(self, *, after="", limit=50):
        return await self._request("GET", "/sessions", params={"after": after, "limit": limit})

    async def rename(self, name):
        return await self._request("POST", "/rename", json={"name": name})

    async def connect(self, to):
        """Legacy: persist a selected recipient. Prefer send(to=...) for concurrent sends."""
        return await self._request("POST", "/connect", json={"to": to})

    async def send(self, content: str, *, to=None, reply_to=None, idempotency_key=None):
        """Store text; a key makes identical retries return the original message.

        Keys are scoped to this sender. Persist a key before sending if the caller
        needs crash recovery. No key means each invocation can create a new message.
        """
        if to is not None:
            await self._require("addressed_send")
        if reply_to is not None:
            await self._require("reply_to")
        result = await self._request("POST", "/send", json={"content": content, "to": to,
                                     "reply_to": reply_to, "message_id": idempotency_key})
        return Message.from_dict(result, self)

    async def send_json(self, content, **kwargs):
        return await self.send(json.dumps(content, ensure_ascii=False, allow_nan=False, sort_keys=True), **kwargs)

    async def ack(self, message_id: int):
        return await self._request("POST", "/ack", json={"message_id": message_id})

    async def delivery_status(self, idempotency_key: str):
        return await self._request("GET", "/delivery_status", params={"message_id": idempotency_key})

    async def _receive(self, path, after, limit, reply_to):
        params = {"after": after, "limit": limit}
        if reply_to is not None:
            await self._require("reply_to")
            params["reply_to"] = reply_to
        result = await self._request("GET", path, params=params)
        return MessagePage([Message.from_dict(row, self) for row in result["messages"]], result["next_after"])

    async def receive(self, *, after=0, limit=50, reply_to=None):
        """Read history, including acknowledged messages. Nothing is consumed."""
        return await self._receive("/receive", after, limit, reply_to)

    async def receive_sent(self, *, after=0, limit=50, reply_to=None):
        """Read this identity's retained outgoing history, including external sends.

        Requires a service with the /sent endpoint. A 404 from an older service
        is reported to the caller; it is not mistaken for an empty outbox.
        """
        return await self._receive("/sent", after, limit, reply_to)

    async def receive_pending(self, *, after=0, limit=50, reply_to=None):
        """Read pending messages. Start each new scan at zero, not a saved high-water mark."""
        return await self._receive("/receive_pending", after, limit, reply_to)

    async def wait(self, *, timeout=45.0, limit=50, poll_interval=0.5, reply_to=None):
        """Cancellable inbox polling. Timeout is a result; service errors remain errors."""
        positive_seconds(timeout, "timeout")
        positive_seconds(poll_interval, "poll_interval")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
        try:
            async with asyncio.timeout(timeout):
                while True:
                    page = await self.receive_pending(limit=limit, reply_to=reply_to)
                    if page.messages:
                        return WaitResult(page.messages, page.next_after, "messages")
                    await asyncio.sleep(poll_interval)
        except TimeoutError:
            return WaitResult([], None, "timeout")

    async def wait_for_reply(self, message: Message, *, timeout=45.0, poll_interval=0.5):
        """Return the first pending reply to our send without acknowledging it."""
        await self.open()
        if message.sender != self.address:
            raise ValueError("Expected a message sent by this identity")
        result = await self.wait(timeout=timeout, limit=1, poll_interval=poll_interval, reply_to=message.id)
        if result.status == "timeout":
            raise TimeoutError(f"No pending reply to Carrier message {message.id} within {timeout} seconds")
        return result.messages[0]

    def consumer(self):
        """Register one async handler locally. Registration performs no network I/O."""
        def register(handler: Handler):
            if self._handler is not None:
                raise ValueError("This client already has a consumer")
            if not inspect.iscoroutinefunction(handler):
                raise TypeError("A consumer must be an async function")
            self._handler = handler
            return handler
        return register

    async def run(self, *, poll_interval=0.5):
        if self._handler is None:
            raise ValueError("Register a consumer before calling run()")
        await self.consume(self._handler, poll_interval=poll_interval)

    async def consume(self, handler: Handler, *, poll_interval=0.5):
        """Handle one pending message at a time until cancelled or an error occurs.

        Handlers explicitly await message.ack(). A failure stops consumption and
        leaves unacknowledged messages pending. An already acknowledged message is
        never restored by a later handler failure. There are no leases or retries.
        """
        positive_seconds(poll_interval, "poll_interval")
        if self._consuming:
            raise CarrierError("This client already has an active consumer")
        self._consuming = True
        try:
            while True:
                result = await self.wait(limit=1, poll_interval=poll_interval)
                for message in result.messages:
                    await handler(message)
                    if message.acknowledged_at is None:
                        raise UnacknowledgedMessage(message.id)
        finally:
            self._consuming = False
