"""HTTP download endpoint for locally-created temporary file grants."""

import html
import urllib.parse

from .temp_links import DOWNLOAD_PREFIX, LinkError


LINK_RESPONSE_HEADERS = {
    'Cache-Control': 'private, no-store',
    'Referrer-Policy': 'no-referrer',
    'X-Content-Type-Options': 'nosniff',
    'Content-Security-Policy': "default-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'; style-src 'unsafe-inline'",
}
LINK_RESERVED_HEADERS = {key.lower() for key in LINK_RESPONSE_HEADERS} | {
    'content-type', 'content-length', 'content-disposition',
}


class TemporaryLinkHTTP:
    def is_link_request(self):
        return not self.url_prefix and getattr(self, 'path', '').split('?', 1)[0].startswith(DOWNLOAD_PREFIX)

    def link_text(self, text):
        portuguese = self.headers.get('Accept-Language', '').lower().startswith('pt')
        if not portuguese:
            return text
        return {
            'Protected download': 'Download protegido',
            'Enter the link password to download this file.': 'Informe a senha do link para baixar este arquivo.',
            'Link password': 'Senha do link',
            'Download file': 'Baixar arquivo',
            'Incorrect link password.': 'Senha do link incorreta.',
            'Too many password attempts. Try again in a minute.': 'Muitas tentativas de senha. Tente novamente em um minuto.',
        }.get(text, text)

    def password_form(self, status=200, error=''):
        route = urllib.parse.urlsplit(self.path).path
        title = html.escape(self.link_text('Protected download'))
        message = html.escape(self.link_text('Enter the link password to download this file.'))
        error = html.escape(self.link_text(error))
        label = html.escape(self.link_text('Link password'))
        button = html.escape(self.link_text('Download file'))
        language = 'pt-BR' if self.headers.get('Accept-Language', '').lower().startswith('pt') else 'en'
        content = f'''<!doctype html><html lang="{language}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>ServerPy - {title}</title>
<style>body{{font:16px system-ui;background:#182231;color:#f0f4fa;margin:0;padding:24px}}main{{max-width:420px;margin:8vh auto}}input,button{{box-sizing:border-box;width:100%;font:inherit;padding:12px;margin-top:10px;border-radius:6px;border:1px solid #788394}}button{{background:#9ed7ff;color:#102030;cursor:pointer}}.error{{color:#ffb4b4}}</style></head>
<body><main><h1>{title}</h1><p>{message}</p><p class="error" role="alert">{error}</p>
<form method="post" action="{html.escape(route, quote=True)}"><label for="password">{label}</label>
<input id="password" name="password" type="password" maxlength="256" autocomplete="off" required autofocus>
<button type="submit">{button}</button></form></main></body></html>'''.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        if status == 429:
            self.send_header('Retry-After', '60')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(content)

    def serve_temporary_link(self):
        if not self.is_link_request():
            return False
        if self.command not in ('GET', 'HEAD', 'POST'):
            self.send_response(405)
            self.send_header('Allow', 'GET, HEAD, POST')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return True
        token = urllib.parse.urlsplit(self.path).path[len(DOWNLOAD_PREFIX):]
        try:
            info = self.server.links.info(token)
            if info['protected'] and self.command != 'POST':
                self.password_form()
                return True
            password = None
            if self.command == 'POST':
                if self.headers.get('Content-Type', '').split(';', 1)[0].strip().lower() != 'application/x-www-form-urlencoded':
                    self.send_error(415, 'Form data required')
                    return True
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 <= length <= 4096:
                        self.send_error(413, 'Password form is too large')
                        return True
                    body = self.rfile.read(length)
                    if len(body) != length:
                        raise ValueError('Incomplete form')
                    form = urllib.parse.parse_qs(body.decode('utf-8'), max_num_fields=4, keep_blank_values=True)
                    password = form.get('password', [''])[0]
                except (ValueError, UnicodeError):
                    self.send_error(400, 'Invalid password form')
                    return True
            stream, filename, size = self.server.links.open_download(token, password, self.client_ip)
            with stream:
                self.send_response(200)
                self.send_header('Content-Type', 'application/octet-stream')
                self.send_header('Content-Length', str(size))
                self.send_header('Content-Disposition', "attachment; filename=\"download\"; filename*=UTF-8''" + urllib.parse.quote(filename, safe=''))
                self.end_headers()
                if self.command != 'HEAD':
                    self.copyfile(stream, self.wfile)
        except LinkError as error:
            if error.status in (403, 429):
                self.password_form(error.status, str(error))
            else:
                self.send_error(error.status, str(error))
        return True
