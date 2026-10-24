"""Serve bundled PWA assets independently of the shared directory."""
from pathlib import Path

PWA_PREFIX = '/_serverpy/pwa/'
ASSETS = {
    'manifest.webmanifest': 'application/manifest+json; charset=utf-8',
    'pwa.js': 'text/javascript; charset=utf-8',
    'latency.js': 'text/javascript; charset=utf-8',
    'sw.js': 'text/javascript; charset=utf-8',
    'offline.html': 'text/html; charset=utf-8',
    'icon-192.png': 'image/png',
    'icon-512.png': 'image/png',
}


def load_asset(route):
    name = route.removeprefix(PWA_PREFIX)
    if name not in ASSETS:
        return None
    path = Path(__file__).resolve().parents[1] / 'templates' / 'pwa' / name
    return path.read_bytes(), ASSETS[name]
