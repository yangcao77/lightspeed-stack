"""Minimal HTTP CONNECT tunnel proxy for e2e testing.

Implements a simple HTTP proxy that supports the CONNECT method for HTTPS
tunneling. The proxy creates a TCP tunnel between the client and the
destination server without inspecting the traffic.

Usage::

    proxy = TunnelProxy(port=8888)
    await proxy.start()
    # ... run tests with HTTPS_PROXY=http://localhost:8888 ...
    await proxy.stop()
    assert proxy.connect_count > 0  # verify proxy was used
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class TunnelProxy:
    """Async HTTP CONNECT tunnel proxy for testing.

    Attributes:
        host: Bind address for the proxy server.
        port: Port to listen on.
        connect_count: Number of CONNECT requests handled.
        last_connect_target: The last host:port that was tunneled to.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8888) -> None:
        """Initialize tunnel proxy configuration."""
        self.host = host
        self.port = port
        self.connect_count = 0
        self.last_connect_target: Optional[str] = None
        self._server: Optional[asyncio.Server] = None

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle an incoming client connection."""
        try:
            request_line = await reader.readline()
            if not request_line:
                return

            request_str = request_line.decode("utf-8", errors="replace").strip()
            parts = request_str.split()

            if len(parts) < 2:
                writer.write(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                await writer.drain()
                return

            method = parts[0].upper()

            if method != "CONNECT":
                writer.write(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
                await writer.drain()
                return

            target = parts[1]
            self.connect_count += 1
            self.last_connect_target = target

            # Parse target host:port
            if ":" in target:
                target_host, target_port_str = target.rsplit(":", 1)
                target_port = int(target_port_str)
            else:
                target_host = target
                target_port = 443

            # Read and discard remaining headers
            while True:
                header_line = await reader.readline()
                if header_line in (b"\r\n", b"\n", b""):
                    break

            # Connect to the target
            try:
                remote_reader, remote_writer = await asyncio.open_connection(
                    target_host, target_port
                )
            except (OSError, ConnectionRefusedError) as e:
                logger.warning("Failed to connect to %s: %s", target, e)
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
                await writer.drain()
                return

            # Send 200 Connection Established
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()

            logger.info("Tunnel established to %s", target)

            # Bidirectional relay
            await asyncio.gather(
                self._relay(reader, remote_writer),
                self._relay(remote_reader, writer),
                return_exceptions=True,
            )

            remote_writer.close()

        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()

    @staticmethod
    async def _relay(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Relay data from reader to writer until EOF."""
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError, asyncio.IncompleteReadError):
            pass

    async def start(self) -> None:
        """Start the proxy server."""
        self._server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )
        logger.info("Tunnel proxy listening on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        """Stop the proxy server."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("Tunnel proxy stopped")

    def reset_counters(self) -> None:
        """Reset request counters."""
        self.connect_count = 0
        self.last_connect_target = None
