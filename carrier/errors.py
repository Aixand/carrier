"""Public SDK errors. Failed mutations are never automatically replayed."""


class CarrierError(Exception):
    """Base error for Carrier SDK operations."""


class HTTPError(CarrierError):
    def __init__(self, status_code, detail):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Carrier HTTP {status_code}: {detail}")


class AuthenticationError(HTTPError):
    pass


class ConflictError(HTTPError):
    pass


class TransportError(CarrierError):
    """No response was confirmed. A mutation may have reached the service."""


class ProtocolError(CarrierError):
    pass


class UnsupportedFeatureError(CarrierError):
    pass


class UnacknowledgedMessage(CarrierError):
    def __init__(self, message_id):
        self.message_id = message_id
        super().__init__(f"Consumer returned without acknowledging message {message_id}; consumption stopped")
