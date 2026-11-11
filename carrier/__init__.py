"""Carrier: durable addressed messaging for programs and agent conversations."""
__version__ = "0.1.0-beta"

from .errors import (AuthenticationError, CarrierError, ConflictError, HTTPError,
                     ProtocolError, TransportError, UnacknowledgedMessage, UnsupportedFeatureError)
from .models import Message, MessagePage, WaitResult
from .sdk import Client
from .provision import ensure_session

__all__ = ["Client", "ensure_session", "Message", "MessagePage", "WaitResult", "CarrierError", "HTTPError",
           "AuthenticationError", "ConflictError", "ProtocolError", "TransportError",
           "UnsupportedFeatureError", "UnacknowledgedMessage"]
