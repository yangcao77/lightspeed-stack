"""Minimal TLS-intercepting (MITM) proxy for e2e testing.

Implements a proxy that terminates TLS from the client, inspects the traffic,
and re-encrypts toward the destination using trustme-generated certificates.
This simulates a corporate interception proxy (SSL inspection).

The proxy generates a unique server certificate for each CONNECT target
using the trustme CA, so the client must trust the CA certificate to
successfully connect.

Usage::

    import trustme
    ca = trustme.CA()
    proxy = InterceptionProxy(ca=ca, port=8889)
    await proxy.start()
    # ... run tests with HTTPS_PROXY=http://localhost:8889
    #     and ca_cert_path pointing to the trustme CA cert ...
    await proxy.stop()
    assert proxy.intercepted_hosts  # verify interception happened
"""

import asyncio
import logging
import ssl
from pathlib import Path
from typing import Optional

import trustme

logger = logging.getLogger(__name__)


class InterceptionProxy:
    """Async TLS-intercepting proxy for testing.

    Attributes:
        host: Bind address for the proxy server.
        port: Port to listen on.
        ca: The trustme CA used to generate interception certificates.
        intercepted_hosts: Set of host:port targets that were intercepted.
        connect_count: Number of CONNECT requests handled.
    """

    def __init__(
        self,
        ca: trustme.CA,
        host: str = "127.0.0.1",
        port: int = 8889,
    ) -> None:
        """Initialize interception proxy."""
        self.host = host
        self.port = port
        self.ca = ca
        self.intercepted_hosts: set[str] = set()
        self.connect_count = 0
        self._server: Optional[asyncio.Server] = None

    def _make_server_ssl_context(self, hostname: str) -> ssl.SSLContext:
        """Create an SSL context with a certificate for the given hostname.

        Parameters:
            hostname: The hostname to generate a certificate for.

        Returns:
            An ssl.SSLContext configured for server-side TLS with a cert
            signed by the proxy's CA for the given hostname.
        """
        server_cert = self.ca.issue_cert(hostname)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_cert.configure_cert(ctx)
        self.ca.configure_trust(ctx)
        return ctx

    @staticmethod
    def _parse_target(target: str) -> tuple[str, int]:
        """Parse a host:port target string."""
        if ":" in target:
            host, port_str = target.rsplit(":", 1)
            return host, int(port_str)
        return target, 443

    async def _upgrade_to_tls(
        self,
        writer: asyncio.StreamWriter,
        hostname: str,
    ) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Upgrade a plaintext connection to TLS (server-side)."""
        server_ctx = self._make_server_ssl_context(hostname)
        transport = writer.transport
        loop = asyncio.get_event_loop()

        new_transport = await loop.start_tls(
            transport, transport.get_protocol(), server_ctx, server_side=True
        )
        assert new_transport is not None, "TLS handshake failed"

        tls_reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(tls_reader)
        new_transport.set_protocol(protocol)
        protocol.connection_made(new_transport)
        tls_writer = asyncio.StreamWriter(
            new_transport, protocol, tls_reader, loop  # type: ignore[arg-type]
        )
        return tls_reader, tls_writer

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle an incoming client connection."""
        try:
            request_line = await reader.readline()
            if not request_line:
                return

            parts = request_line.decode("utf-8", errors="replace").strip().split()

            if len(parts) < 2 or parts[0].upper() != "CONNECT":
                writer.write(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
                await writer.drain()
                return

            target = parts[1]
            self.connect_count += 1
            self.intercepted_hosts.add(target)
            target_host, target_port = self._parse_target(target)

            # Read and discard remaining headers
            while True:
                header_line = await reader.readline()
                if header_line in (b"\r\n", b"\n", b""):
                    break

            # Send 200 to tell client to start TLS
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()

            # Upgrade client connection to TLS
            tls_reader, tls_writer = await self._upgrade_to_tls(writer, target_host)

            # Connect to the real server with TLS
            try:
                remote_reader, remote_writer = await asyncio.open_connection(
                    target_host, target_port, ssl=True
                )
            except (OSError, ConnectionRefusedError, ssl.SSLError) as e:
                logger.warning("Failed to connect to %s: %s", target, e)
                tls_writer.close()
                return

            logger.info("Intercepting connection to %s", target)

            # Bidirectional relay over the two TLS connections
            await asyncio.gather(
                self._relay(tls_reader, remote_writer),
                self._relay(remote_reader, tls_writer),
                return_exceptions=True,
            )

            remote_writer.close()
            tls_writer.close()

        except (
            ConnectionResetError,
            BrokenPipeError,
            asyncio.IncompleteReadError,
            ssl.SSLError,
        ):
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
        """Start the interception proxy server."""
        self._server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )
        logger.info("Interception proxy listening on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        """Stop the interception proxy server."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("Interception proxy stopped")

    def export_ca_cert(self, path: Path) -> None:
        """Export the CA certificate to a PEM file.

        Parameters:
            path: File path to write the CA certificate PEM to.
        """
        self.ca.cert_pem.write_to_path(str(path))
        logger.info("Exported interception proxy CA cert to %s", path)

    def reset_counters(self) -> None:
        """Reset request counters."""
        self.connect_count = 0
        self.intercepted_hosts.clear()
