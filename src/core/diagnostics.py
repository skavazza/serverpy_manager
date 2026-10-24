"""Read-only DNS, TCP and HTTP checks for a single user-selected endpoint."""

import http.client
import ipaddress
import socket
import time


def diagnose_endpoint(host, port, use_tls=False):
    if not isinstance(host, str) or not host.strip() or len(host) > 253 or any(c.isspace() or c in '/\\@?#' for c in host):
        raise ValueError('Enter a hostname or IP address without a URL or port.')
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError('Enter a port from 1 to 65535.')
    rows = []
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        ips = list(dict.fromkeys(address[4][0] for address in addresses))
        if not ips:
            raise OSError('No addresses returned')
        rows.append(('Name resolution', 'OK', ', '.join(ips)))
    except OSError as error:
        return [('Name resolution', 'Failed', str(error))]

    started = time.monotonic()
    connected = False
    error = None
    for family, kind, protocol, _, address in addresses[:4]:
        remaining = 3 - (time.monotonic() - started)
        if remaining <= 0:
            break
        try:
            with socket.socket(family, kind, protocol) as connection:
                connection.settimeout(remaining)
                connection.connect(address)
            connected = True
            break
        except OSError as failure:
            error = failure
    if not connected:
        rows.append(('TCP connection', 'Failed', str(error or 'Connection timed out')))
        return rows
    rows.append(('TCP connection', 'OK', f'{(time.monotonic() - started) * 1000:.0f} ms'))
    connection = None
    tls_error = None
    try:
        connection_type = http.client.HTTPSConnection if use_tls else http.client.HTTPConnection
        connection = connection_type(host, port, timeout=3)
        connection.request('HEAD', '/')
        response = connection.getresponse()
        rows.append(('HTTPS response' if use_tls else 'HTTP response', 'Reachable', f'{response.status} {response.reason}'))
    except (OSError, http.client.HTTPException) as error:
        tls_error = error if use_tls else None
        rows.append(('HTTPS response' if use_tls else 'HTTP response', 'Failed', str(error)))
    finally:
        if connection is not None:
            connection.close()
    if tls_error is not None:
        fallback = None
        try:
            fallback = http.client.HTTPConnection(host, port, timeout=3)
            fallback.request('HEAD', '/')
            response = fallback.getresponse()
            local_endpoint = all(ipaddress.ip_address(ip).is_loopback for ip in ips)
            rows.append(('HTTP fallback', 'Reachable', f'{response.status} {response.reason}'))
            guidance = (
                'This local endpoint replied over HTTP, not HTTPS. '
                'Disable Use HTTPS; TLS usually terminates at Cloudflare.'
                if local_endpoint else
                'HTTP replied after HTTPS failed. Check the TLS setting and Cloudflare SSL/TLS mode.'
            )
            rows.append(('Protocol guidance', 'Use HTTP', guidance))
        except (OSError, http.client.HTTPException) as error:
            rows.append(('HTTP fallback', 'Failed', str(error)))
        finally:
            if fallback is not None:
                fallback.close()
    return rows
