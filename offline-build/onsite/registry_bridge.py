"""Loopback transport bridge for relok8s 0.5.4 (which has no TLS flags)."""
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import ssl
import threading
from urllib.parse import urlsplit


class RegistryBridge:
    def __init__(self, config, private):
        self.config, self.private = config, Path(private)
        self.upstream = urlsplit(config['url'])
        self.context = ssl.create_default_context(cafile=config.get('ca_file') or None)
        if config.get('skip_tls_verify'):
            self.context.check_hostname = False
            self.context.verify_mode = ssl.CERT_NONE

    def __enter__(self):
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *_):
                pass  # URLs may contain registry upload tokens.

            def handle_request(self):
                connection = None
                try:
                    if not self.path.startswith('/') or self.path.startswith('//'):
                        raise ValueError('Invalid registry path')
                    up = bridge.upstream
                    cls = http.client.HTTPSConnection if up.scheme == 'https' else http.client.HTTPConnection
                    options = {'context': bridge.context} if up.scheme == 'https' else {}
                    connection = cls(up.hostname, up.port, timeout=300, **options)
                    headers = {k: v for k, v in self.headers.items()
                               if k.lower() not in ('host', 'connection', 'transfer-encoding', 'expect')}
                    headers['Host'] = up.netloc
                    chunked = 'chunked' in self.headers.get('Transfer-Encoding', '').lower()
                    length = int(self.headers.get('Content-Length', '0'))

                    def chunks():
                        remaining = length
                        while chunked or remaining:
                            count = int(self.rfile.readline().strip().split(b';')[0], 16) if chunked else min(1024**2, remaining)
                            if not count:
                                if chunked:
                                    while self.rfile.readline().strip():
                                        pass
                                break
                            left = count
                            while left:
                                block = self.rfile.read(min(left, 1024**2))
                                if not block:
                                    raise ValueError('Registry upload interrupted')
                                left -= len(block); remaining -= len(block)
                                yield block
                            if chunked and self.rfile.read(2) != b'\r\n':
                                raise ValueError('Malformed chunk')

                    connection.request(self.command, self.path, body=chunks() if chunked or length else None,
                                       headers=headers, encode_chunked=chunked)
                    response = connection.getresponse()
                    output_headers = []
                    for key, value in response.getheaders():
                        if key.lower() in ('transfer-encoding', 'connection'):
                            continue
                        if key.lower() == 'location':
                            location = urlsplit(value)
                            if location.netloc and location.netloc != up.netloc:
                                # Fail instead of sending upload credentials to an unexpected host.
                                raise ValueError('Cross-host registry upload redirect is unsupported')
                            if location.netloc:
                                value = 'http://' + bridge.address + location.path + ('?' + location.query if location.query else '')
                        if key.lower() == 'www-authenticate':
                            value = value.replace(bridge.config['url'], 'http://' + bridge.address)
                        output_headers.append((key, value))
                    self.send_response(response.status)
                    for key, value in output_headers: self.send_header(key, value)
                    self.send_header('Connection', 'close'); self.end_headers()
                    if self.command != 'HEAD':
                        while block := response.read(1024**2):
                            self.wfile.write(block)
                except Exception:
                    # No upstream URL/query/credentials in client diagnostics.
                    if not self.wfile.closed:
                        try:
                            self.send_error(502, 'Registry transport failed; check endpoint, TLS and authentication')
                        except OSError:
                            pass
                finally:
                    self.close_connection = True
                    if connection:
                        connection.close()

            do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = handle_request

        self.private.mkdir(parents=True, exist_ok=True, mode=0o700)
        auth_dir = self.config.get('docker_config_directory')
        auth = json.loads((Path(auth_dir) / 'config.json').read_text()) if auth_dir else {}
        # Do not silently drop credential helpers when aliasing a registry.
        if auth.get('credsStore') or auth.get('credHelpers'):
            raise ValueError('Use a restricted Docker auth config with inline auths for onsite relocation; credential-helper aliasing is unsupported')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.address = 'localhost:' + str(self.server.server_address[1])
        entries = auth.get('auths', {})
        match = next((v for k, v in entries.items() if k.rstrip('/').removeprefix('https://').removeprefix('http://') == self.upstream.netloc), {})
        path = self.private / 'config.json'
        path.write_text(json.dumps({'auths': {self.address: match, self.upstream.netloc: match}}))
        path.chmod(0o600)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        (self.private / 'config.json').unlink(missing_ok=True)
