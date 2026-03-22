"""Vehicle error code expansion plugin.

This ports the legacy ``OVMS::Server::VECE`` module by loading ``*.vece``
INI files and exposing the ``VECE_Expansion`` function.
"""

from __future__ import annotations

import configparser
from pathlib import Path

from py.server.ovms_server import BasePlugin, LOGGER


class VECE(BasePlugin):
    """Provide vehicle error code text expansion."""

    def __init__(self, server) -> None:
        super().__init__(server)
        self.config = configparser.ConfigParser(interpolation=None, strict=False)
        self.config.optionxform = str
        self._load_vece_files()
        self.server.plugins.register_function("VECE_Expansion", self.expansion)

    def _load_vece_files(self) -> None:
        """Load every VECE file from the legacy location."""

        for vece_path in sorted(Path("v3/server/vece").glob("*.vece")):
            LOGGER.info("- - - loading %s", vece_path)
            parser = configparser.ConfigParser(interpolation=None, strict=False)
            parser.optionxform = str
            parser.read(vece_path, encoding="utf-8")
            for section in parser.sections():
                if not self.config.has_section(section):
                    self.config.add_section(section)
                for key, value in parser.items(section):
                    self.config.set(section, key, value)

    def expansion(self, vehicletype: str, errorcode: int | str, errordata: int) -> str:
        """Expand an error code to a readable alert message.

        :param vehicletype: Vehicle type prefix used for fallback lookup.
        :param errorcode: Numeric error code.
        :param errordata: Payload value passed into template placeholders.
        :returns: Expanded alert text.
        """

        code_key = str(errorcode)
        car = vehicletype
        while car:
            if self.config.has_option(car, code_key):
                template = self.config.get(car, code_key)
                try:
                    message = template % errordata
                except Exception:
                    message = template
                return f"Vehicle Alert #{code_key}: {message}"
            car = car[:-1]
        return f"Vehicle Alert Code: {vehicletype}/{int(errorcode)} ({int(errordata):08x})"
