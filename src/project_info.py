"""Developer information displayed by the desktop application."""
import json
from pathlib import Path


def get_project_info():
    return json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))
