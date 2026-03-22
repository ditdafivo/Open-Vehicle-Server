"""Simple plaintext authentication plugin."""

from __future__ import annotations

from py.server.ovms_server import BasePlugin, LOGGER


class AuthDbSimple(BasePlugin):
    """Authenticate using owner table clear-text passwords."""

    def __init__(self, server) -> None:
        super().__init__(server)
        self.server.plugins.register_function("Authenticate", self.authenticate)

    def authenticate(self, user: str, password: str) -> str:
        """Authenticate a user and return permission flags."""

        rec = self.server.plugins.function_call("DbGetOwner", user)
        if not rec:
            return ""
        dbpass = rec.get("pass")
        if dbpass is None:
            return ""
        if password == dbpass:
            LOGGER.debug("- - - Authentication via username+password")
            return "*"
        return ""
