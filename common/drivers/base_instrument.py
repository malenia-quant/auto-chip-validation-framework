"""BaseInstrument: Standardized Instrument Abstract Base Class.

Supports PyVISA and Raw TCP Socket communications with:
- Context manager support (__enter__ / __exit__)
- Configurable retry mechanism with backoff for pyvisa.VisaIOError & TransportError
- Standardized logging without emoji
- Explicit connection lifecycle and resource cleanup

Author: mozial
"""

import logging
import socket
import time
from abc import ABC, abstractmethod
from typing import Any, Optional, Tuple

try:
    import pyvisa
except ImportError:
    pyvisa = None

from drivers.exceptions import (
    InstrumentCommandError,
    InstrumentCommunicationError,
    InstrumentConnectionError,
    InstrumentIdentityError,
    TransportError,
)


class BaseInstrument(ABC):
    """Abstract base class for all test and measurement instruments."""

    def __init__(
        self,
        name: str,
        resource_name: Optional[str] = None,
        host: Optional[str] = None,
        port: Optional[int] = None,
        timeout_ms: int = 5000,
        max_retries: int = 3,
        retry_delay_s: float = 0.5,
    ):
        self.name = name
        self.resource_name = resource_name
        self.host = host
        self.port = port
        self.timeout_ms = timeout_ms
        self.max_retries = max_retries
        self.retry_delay_s = retry_delay_s

        self.logger = logging.getLogger(f"Driver.{name}")
        self._is_connected = False
        self._visa_rm = None
        self._visa_inst = None
        self._socket = None

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def connect(self) -> bool:
        """Establish connection via PyVISA or TCP Socket."""
        self.logger.info(f"Connecting to instrument '{self.name}'...")
        if self._is_connected:
            self.logger.warning(f"Instrument '{self.name}' is already connected.")
            return True

        try:
            if self.resource_name:
                self._connect_visa()
            elif self.host and self.port:
                self._connect_tcp()
            else:
                raise InstrumentConnectionError(
                    f"[{self.name}] No resource_name or (host, port) provided for connection."
                )

            self._is_connected = True
            idn = self.get_idn()
            self.logger.info(f"Instrument '{self.name}' connected successfully. IDN: {idn}")
            self._post_connect()
            return True
        except Exception as e:
            self._is_connected = False
            self.logger.error(f"Failed to connect to instrument '{self.name}': {e}")
            self.close()
            raise

    def _connect_visa(self):
        if pyvisa is None:
            raise ImportError("pyvisa package is required for VISA communication.")
        self._visa_rm = pyvisa.ResourceManager()
        self._visa_inst = self._visa_rm.open_resource(self.resource_name)
        self._visa_inst.timeout = self.timeout_ms

    def _connect_tcp(self):
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.settimeout(self.timeout_ms / 1000.0)
        self._socket.connect((self.host, self.port))

    def _post_connect(self):
        """Hook called immediately after connection establishment."""
        pass

    def close(self):
        """Safely close instrument session and release resources."""
        self.logger.info(f"Closing instrument session for '{self.name}'...")
        if self._visa_inst is not None:
            try:
                self._visa_inst.close()
            except Exception as e:
                self.logger.warning(f"Error closing VISA session for '{self.name}': {e}")
            finally:
                self._visa_inst = None

        if self._visa_rm is not None:
            try:
                self._visa_rm.close()
            except Exception as e:
                self.logger.warning(f"Error closing VISA resource manager: {e}")
            finally:
                self._visa_rm = None

        if self._socket is not None:
            try:
                self._socket.close()
            except Exception as e:
                self.logger.warning(f"Error closing TCP socket for '{self.name}': {e}")
            finally:
                self._socket = None

        self._is_connected = False
        self.logger.info(f"Instrument session for '{self.name}' closed.")

    def write(self, command: str):
        """Write SCPI command with retry logic."""
        if not self._is_connected:
            raise InstrumentConnectionError(f"Cannot write: instrument '{self.name}' is not connected.")

        attempts = 0
        while attempts <= self.max_retries:
            try:
                if self._visa_inst is not None:
                    self._visa_inst.write(command)
                elif self._socket is not None:
                    payload = (command + "\n").encode("utf-8")
                    self._socket.sendall(payload)
                self.logger.debug(f"[{self.name}] WRITE: {command}")
                return
            except Exception as err:
                attempts += 1
                self.logger.warning(
                    f"[{self.name}] Write '{command}' failed (attempt {attempts}/{self.max_retries}): {err}"
                )
                if attempts > self.max_retries:
                    raise InstrumentCommunicationError(
                        f"[{self.name}] Failed to write command '{command}' after {self.max_retries} retries."
                    ) from err
                time.sleep(self.retry_delay_s)

    def write_raw(self, data: bytes):
        """Write raw binary payload with retry logic."""
        if not self._is_connected:
            raise InstrumentConnectionError(f"Cannot write_raw: instrument '{self.name}' is not connected.")

        attempts = 0
        while attempts <= self.max_retries:
            try:
                if self._visa_inst is not None:
                    self._visa_inst.write_raw(data)
                elif self._socket is not None:
                    self._socket.sendall(data)
                self.logger.debug(f"[{self.name}] WRITE_RAW: {len(data)} bytes")
                return
            except Exception as err:
                attempts += 1
                self.logger.warning(
                    f"[{self.name}] Write_raw ({len(data)} bytes) failed (attempt {attempts}/{self.max_retries}): {err}"
                )
                if attempts > self.max_retries:
                    raise InstrumentCommunicationError(
                        f"[{self.name}] Failed write_raw after {self.max_retries} retries."
                    ) from err
                time.sleep(self.retry_delay_s)

    def query(self, command: str) -> str:
        """Query instrument (write command + read response) with retry logic."""
        if not self._is_connected:
            raise InstrumentConnectionError(f"Cannot query: instrument '{self.name}' is not connected.")

        attempts = 0
        while attempts <= self.max_retries:
            try:
                if self._visa_inst is not None:
                    res = self._visa_inst.query(command).strip()
                elif self._socket is not None:
                    payload = (command + "\n").encode("utf-8")
                    self._socket.sendall(payload)
                    res = self._read_socket_line().strip()
                else:
                    raise InstrumentConnectionError(f"[{self.name}] No valid transport available.")

                self.logger.debug(f"[{self.name}] QUERY: '{command}' -> '{res}'")
                return res
            except Exception as err:
                attempts += 1
                self.logger.warning(
                    f"[{self.name}] Query '{command}' failed (attempt {attempts}/{self.max_retries}): {err}"
                )
                if attempts > self.max_retries:
                    raise InstrumentCommunicationError(
                        f"[{self.name}] Failed to query '{command}' after {self.max_retries} retries."
                    ) from err
                time.sleep(self.retry_delay_s)

    def read_raw(self) -> bytes:
        """Read raw bytes from instrument."""
        if not self._is_connected:
            raise InstrumentConnectionError(f"Cannot read_raw: instrument '{self.name}' is not connected.")

        try:
            if self._visa_inst is not None:
                return self._visa_inst.read_raw()
            elif self._socket is not None:
                chunks = []
                while True:
                    chunk = self._socket.recv(4096)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    if len(chunk) < 4096:
                        break
                return b"".join(chunks)
            else:
                raise InstrumentConnectionError(f"[{self.name}] No valid transport available.")
        except Exception as e:
            raise InstrumentCommunicationError(f"[{self.name}] Read raw failed: {e}") from e

    def _read_socket_line(self) -> str:
        """Read a newline terminated ASCII string from socket."""
        buffer = []
        while True:
            char = self._socket.recv(1)
            if not char:
                break
            if char == b"\n":
                break
            buffer.append(char)
        return b"".join(buffer).decode("utf-8", errors="replace")

    def get_idn(self) -> str:
        """Query standard *IDN? identification string."""
        return self.query("*IDN?")

    def reset(self):
        """Reset instrument to default factory state (*RST)."""
        self.write("*RST")
        time.sleep(0.5)

    def clear_status(self):
        """Clear instrument status register (*CLS)."""
        self.write("*CLS")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
