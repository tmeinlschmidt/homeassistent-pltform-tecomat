"""PlcComS client for Tecomat Foxtrot PLCs.

This module implements the PlcComS protocol for communicating with
Tecomat Foxtrot PLCs over TCP/IP.

Protocol reference:
- Commands are text-based, ending with CRLF (\\r\\n)
- Encoding: Windows-1250 (Central European)
- Default port: 5010

Commands:
- GET:<variable> - Get value of variable
- SET:<variable>,<value> - Set variable value
- LIST: - Get list of all public variables
- EN:<variable> [delta] - Enable monitoring for variable
- DI:<variable> - Disable monitoring for variable
- GETINFO:[param] - Get server/PLC information
"""
from __future__ import annotations

import asyncio
import codecs
import logging
from typing import Any, Callable

_LOGGER = logging.getLogger(__name__)

# Protocol constants
ENCODING = "cp1250"
LINE_TERMINATOR = "\r\n"
DEFAULT_PORT = 5010
RECONNECT_INTERVAL = 4  # seconds


class PlcComSError(Exception):
    """Base exception for PlcComS errors."""


class PlcComSConnectionError(PlcComSError):
    """Connection error."""


class PlcComSProtocolError(PlcComSError):
    """Protocol error."""


class PlcComSClient:
    """Async client for PlcComS protocol."""

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        reconnect: bool = True,
    ) -> None:
        """Initialize the PlcComS client.

        Args:
            host: Hostname or IP address of the PLC
            port: TCP port (default 5010)
            reconnect: Whether to automatically reconnect on disconnect
        """
        self.host = host
        self.port = port
        self._reconnect_enabled = reconnect
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False
        self._callbacks: dict[str, list[Callable[[str, Any], None]]] = {}
        self._global_callbacks: list[Callable[[str, Any], None]] = []
        self._read_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._buffer = ""
        self._variables: dict[str, Any] = {}
        self._pending_responses: dict[str, asyncio.Future] = {}
        self._response_lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        """Return True if connected to PLC."""
        return self._connected

    @property
    def variables(self) -> dict[str, Any]:
        """Return cached variable values."""
        return self._variables.copy()

    async def connect(self) -> None:
        """Connect to the PLC.

        Raises:
            PlcComSConnectionError: If connection fails
        """
        if self._connected:
            return

        try:
            _LOGGER.debug("Connecting to PlcComS at %s:%s", self.host, self.port)
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=10,
            )
            self._connected = True
            self._buffer = ""
            _LOGGER.info("Connected to PlcComS at %s:%s", self.host, self.port)

            # Start the read loop
            self._read_task = asyncio.create_task(self._read_loop())

        except asyncio.TimeoutError as err:
            raise PlcComSConnectionError(
                f"Connection timeout to {self.host}:{self.port}"
            ) from err
        except OSError as err:
            raise PlcComSConnectionError(
                f"Failed to connect to {self.host}:{self.port}: {err}"
            ) from err

    async def disconnect(self) -> None:
        """Disconnect from the PLC."""
        self._connected = False
        self._reconnect_enabled = False

        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
            self._read_task = None

        if self._reconnect_task:
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None

        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

        # Cancel pending responses
        for future in self._pending_responses.values():
            if not future.done():
                future.cancel()
        self._pending_responses.clear()

        _LOGGER.info("Disconnected from PlcComS")

    async def _read_loop(self) -> None:
        """Read data from the PLC continuously."""
        decoder = codecs.getdecoder(ENCODING)

        while self._connected and self._reader:
            try:
                data = await self._reader.read(4096)
                if not data:
                    _LOGGER.warning("Connection closed by PLC")
                    await self._handle_disconnect()
                    return

                # Decode and add to buffer
                decoded = decoder(data, "replace")[0]
                self._buffer += decoded

                # Process complete lines
                while LINE_TERMINATOR in self._buffer:
                    line, self._buffer = self._buffer.split(LINE_TERMINATOR, 1)
                    if line:
                        await self._process_response(line)

            except asyncio.CancelledError:
                return
            except Exception as err:
                _LOGGER.error("Error reading from PLC: %s", err)
                await self._handle_disconnect()
                return

    async def _handle_disconnect(self) -> None:
        """Handle unexpected disconnect."""
        self._connected = False
        if self._writer:
            self._writer.close()
            self._writer = None
            self._reader = None

        # Cancel pending responses
        for future in self._pending_responses.values():
            if not future.done():
                future.set_exception(PlcComSConnectionError("Connection lost"))
        self._pending_responses.clear()

        # Attempt reconnect if enabled
        if self._reconnect_enabled:
            self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def _reconnect_loop(self) -> None:
        """Attempt to reconnect to the PLC."""
        while self._reconnect_enabled and not self._connected:
            _LOGGER.info("Attempting to reconnect to PlcComS...")
            try:
                await asyncio.sleep(RECONNECT_INTERVAL)
                await self.connect()
                # Re-enable monitoring for all subscribed variables
                for var_name in self._callbacks:
                    await self._send_command(f"EN:{var_name}")
            except PlcComSConnectionError as err:
                _LOGGER.warning("Reconnection failed: %s", err)
            except asyncio.CancelledError:
                return

    async def _process_response(self, line: str) -> None:
        """Process a response line from the PLC.

        Args:
            line: The response line (without CRLF)
        """
        _LOGGER.debug("Received: %s", line)

        if ":" not in line:
            _LOGGER.warning("Invalid response format: %s", line)
            return

        cmd, params = line.split(":", 1)
        cmd = cmd.upper()

        if cmd == "GET":
            await self._handle_get_response(params)
        elif cmd == "DIFF":
            await self._handle_diff_response(params)
        elif cmd == "LIST":
            await self._handle_list_response(params)
        elif cmd == "ERROR":
            _LOGGER.error("PlcComS error: %s", params)
            # Check if there's a pending request waiting
            async with self._response_lock:
                if "error" in self._pending_responses:
                    future = self._pending_responses.pop("error")
                    if not future.done():
                        future.set_exception(PlcComSProtocolError(params))
        elif cmd == "WARNING":
            _LOGGER.warning("PlcComS warning: %s", params)
        elif cmd == "GETINFO":
            await self._handle_getinfo_response(params)
        else:
            _LOGGER.debug("Unhandled response: %s", line)

    async def _handle_get_response(self, params: str) -> None:
        """Handle GET response."""
        if "," not in params:
            return

        var_name, raw_value = params.split(",", 1)
        value = self._parse_value(raw_value)
        self._variables[var_name] = value

        # Check for pending request
        async with self._response_lock:
            key = f"GET:{var_name}"
            if key in self._pending_responses:
                future = self._pending_responses.pop(key)
                if not future.done():
                    future.set_result(value)

        # Notify callbacks
        await self._notify_callbacks(var_name, value)

    async def _handle_diff_response(self, params: str) -> None:
        """Handle DIFF response (value change notification)."""
        if "," not in params:
            return

        var_name, raw_value = params.split(",", 1)
        value = self._parse_value(raw_value)
        self._variables[var_name] = value

        # Notify callbacks
        await self._notify_callbacks(var_name, value)

    async def _handle_list_response(self, params: str) -> None:
        """Handle LIST response.

        Format: LIST:variable_name,TYPE*
        Example: LIST:RO01_01_VCHOD,BOOL*
        """
        params = params.strip()
        if not params:
            return

        # Parse variable name and type
        if "," in params:
            var_name, var_type = params.rsplit(",", 1)
            var_type = var_type.rstrip("*")  # Remove trailing *
        else:
            var_name = params
            var_type = "UNKNOWN"

        # Store that this variable exists
        if var_name not in self._variables:
            self._variables[var_name] = None

        async with self._response_lock:
            if "LIST" in self._pending_responses:
                future = self._pending_responses["LIST"]
                if hasattr(future, "_var_list"):
                    future._var_list.append({"name": var_name, "type": var_type})

    async def _handle_getinfo_response(self, params: str) -> None:
        """Handle GETINFO response."""
        async with self._response_lock:
            if "GETINFO" in self._pending_responses:
                future = self._pending_responses.pop("GETINFO")
                if not future.done():
                    future.set_result(params)

    def _parse_value(self, raw_value: str) -> Any:
        """Parse a value from the PLC response.

        Args:
            raw_value: Raw string value from PLC

        Returns:
            Parsed value (str, int, float, or bool)
        """
        raw_value = raw_value.strip()

        # String value (quoted)
        if raw_value.startswith('"') and raw_value.endswith('"'):
            return raw_value[1:-1]

        # Boolean
        if raw_value.lower() == "true":
            return True
        if raw_value.lower() == "false":
            return False

        # Numeric
        try:
            if "." in raw_value:
                return float(raw_value)
            return int(raw_value)
        except ValueError:
            return raw_value

    def _format_value(self, value: Any) -> str:
        """Format a value for sending to the PLC.

        Args:
            value: Value to format

        Returns:
            Formatted string value
        """
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            return f'"{value}"'
        return str(value)

    async def _send_command(self, command: str) -> None:
        """Send a command to the PLC.

        Args:
            command: Command to send (without CRLF)

        Raises:
            PlcComSConnectionError: If not connected
        """
        if not self._connected or not self._writer:
            raise PlcComSConnectionError("Not connected to PLC")

        try:
            encoder = codecs.getencoder(ENCODING)
            data = encoder(f"{command}{LINE_TERMINATOR}")[0]
            self._writer.write(data)
            await self._writer.drain()
            _LOGGER.debug("Sent: %s", command)
        except Exception as err:
            raise PlcComSConnectionError(f"Failed to send command: {err}") from err

    async def _notify_callbacks(self, var_name: str, value: Any) -> None:
        """Notify registered callbacks of a value change."""
        # Variable-specific callbacks
        if var_name in self._callbacks:
            for callback in self._callbacks[var_name]:
                try:
                    callback(var_name, value)
                except Exception as err:
                    _LOGGER.error("Error in callback for %s: %s", var_name, err)

        # Global callbacks
        for callback in self._global_callbacks:
            try:
                callback(var_name, value)
            except Exception as err:
                _LOGGER.error("Error in global callback: %s", err)

    # Public API methods

    async def get_variable(self, name: str, timeout: float = 5.0) -> Any:
        """Get the value of a variable.

        Args:
            name: Variable name
            timeout: Response timeout in seconds

        Returns:
            Variable value

        Raises:
            PlcComSConnectionError: If not connected
            PlcComSProtocolError: If variable not found or error
            asyncio.TimeoutError: If response timeout
        """
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        key = f"GET:{name}"

        async with self._response_lock:
            self._pending_responses[key] = future

        try:
            await self._send_command(f"GET:{name}")
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            async with self._response_lock:
                self._pending_responses.pop(key, None)
            raise
        finally:
            async with self._response_lock:
                self._pending_responses.pop(key, None)

    async def set_variable(self, name: str, value: Any) -> None:
        """Set the value of a variable.

        Args:
            name: Variable name
            value: Value to set

        Raises:
            PlcComSConnectionError: If not connected
        """
        formatted = self._format_value(value)
        await self._send_command(f"SET:{name},{formatted}")

    async def list_variables(self, timeout: float = 10.0) -> list[dict[str, str]]:
        """Get list of all public variables with their types.

        Args:
            timeout: Response timeout in seconds

        Returns:
            List of dicts with 'name' and 'type' keys

        Raises:
            PlcComSConnectionError: If not connected
            asyncio.TimeoutError: If response timeout
        """
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        future._var_list = []  # type: ignore

        async with self._response_lock:
            self._pending_responses["LIST"] = future

        try:
            await self._send_command("LIST:")
            # Wait for all LIST responses (terminated by empty line or timeout)
            await asyncio.sleep(timeout)
            return future._var_list  # type: ignore
        finally:
            async with self._response_lock:
                self._pending_responses.pop("LIST", None)

    async def enable_monitoring(
        self,
        name: str,
        delta: float = 0,
        callback: Callable[[str, Any], None] | None = None,
    ) -> None:
        """Enable monitoring for a variable.

        When enabled, the PLC will send DIFF responses when the variable
        value changes (optionally filtered by delta threshold).

        Args:
            name: Variable name
            delta: Minimum change threshold (0 = report all changes)
            callback: Optional callback function(var_name, value)

        Raises:
            PlcComSConnectionError: If not connected
        """
        if callback:
            if name not in self._callbacks:
                self._callbacks[name] = []
            self._callbacks[name].append(callback)

        cmd = f"EN:{name}"
        if delta > 0:
            cmd += f" {delta}"
        await self._send_command(cmd)

    async def disable_monitoring(self, name: str) -> None:
        """Disable monitoring for a variable.

        Args:
            name: Variable name

        Raises:
            PlcComSConnectionError: If not connected
        """
        self._callbacks.pop(name, None)
        await self._send_command(f"DI:{name}")

    async def get_info(self, param: str = "", timeout: float = 5.0) -> str:
        """Get server/PLC information.

        Args:
            param: Info parameter (version, ipaddr, serial, etc.)
            timeout: Response timeout in seconds

        Returns:
            Info string

        Raises:
            PlcComSConnectionError: If not connected
            asyncio.TimeoutError: If response timeout
        """
        future: asyncio.Future = asyncio.get_event_loop().create_future()

        async with self._response_lock:
            self._pending_responses["GETINFO"] = future

        try:
            await self._send_command(f"GETINFO:{param}")
            return await asyncio.wait_for(future, timeout=timeout)
        finally:
            async with self._response_lock:
                self._pending_responses.pop("GETINFO", None)

    def register_callback(
        self,
        callback: Callable[[str, Any], None],
        var_name: str | None = None,
    ) -> None:
        """Register a callback for variable updates.

        Args:
            callback: Callback function(var_name, value)
            var_name: Optional specific variable name (None = all variables)
        """
        if var_name:
            if var_name not in self._callbacks:
                self._callbacks[var_name] = []
            self._callbacks[var_name].append(callback)
        else:
            self._global_callbacks.append(callback)

    def unregister_callback(
        self,
        callback: Callable[[str, Any], None],
        var_name: str | None = None,
    ) -> None:
        """Unregister a callback.

        Args:
            callback: Callback function to remove
            var_name: Optional specific variable name (None = global callback)
        """
        if var_name:
            if var_name in self._callbacks:
                try:
                    self._callbacks[var_name].remove(callback)
                except ValueError:
                    pass
        else:
            try:
                self._global_callbacks.remove(callback)
            except ValueError:
                pass
