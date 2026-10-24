"""
Cross-platform system detection and capability helpers for Windows and Linux.
"""

import os
import platform
import shutil
import sys


def is_windows() -> bool:
    """Check if the current host operating system is Windows."""
    return sys.platform == "win32"


def is_linux() -> bool:
    """Check if the current host operating system is Linux."""
    return sys.platform.startswith("linux")


def is_macos() -> bool:
    """Check if the current host operating system is macOS."""
    return sys.platform == "darwin"


def is_windows_10_or_11() -> bool:
    """
    Check if the current host operating system is Windows 10 or 11
    (or equivalent Windows Server).
    """
    if not is_windows():
        return False
    try:
        winver = getattr(sys, "getwindowsversion", None)
        if callable(winver):
            return winver().major >= 10
    except Exception:
        pass
    try:
        rel = platform.release()
        return platform.system() == "Windows" and (rel in ("10", "11") or (rel.isdigit() and int(rel) >= 10))
    except Exception:
        return False


def is_platform_supported() -> bool:
    """
    Check if the current platform is supported for desktop system integration
    (Windows 10/11 or Linux).
    """
    if is_windows():
        return is_windows_10_or_11()
    if is_linux():
        return True
    return False


def get_os_display_name() -> str:
    """Return a human-friendly name for the current operating system."""
    if is_windows():
        rel = platform.release()
        return f"Windows {rel}" if rel else "Windows"
    elif is_linux():
        return "Linux"
    elif is_macos():
        return "macOS"
    return platform.system() or sys.platform


def is_tool_available(tool_name: str) -> bool:
    """Check if an external executable tool is available in PATH."""
    return shutil.which(tool_name) is not None
