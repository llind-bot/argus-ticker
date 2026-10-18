"""Download and install a new ArgusTicker.exe in place (Windows, packaged app only).

Windows won't let a running exe be overwritten, but it can be renamed. So:
download the new exe next to the current one, check its SHA-256 against the
``.sha256`` file published with the release, rename the running exe to
``*.old.exe``, move the new one into its place, start it and quit. The next
start deletes the ``.old.exe``. The watchlist, settings and keys live outside
the exe and are untouched.
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Callable, Optional

from .providers.base import USER_AGENT

_log = logging.getLogger("ticker.selfupdate")
CHUNK = 256 * 1024


class UpdateError(Exception):
    pass


def current_exe() -> Optional[Path]:
    """The running ArgusTicker.exe, or None when running from source / not on Windows."""
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        return Path(sys.executable)
    return None


def can_self_update() -> bool:
    return current_exe() is not None


def _get(url: str, timeout: float = 30):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout)


def parse_sha256_file(text: str) -> str:
    """'<hex>  ArgusTicker.exe' (sha256sum / certutil style) → lower-case hex."""
    for token in text.replace("*", " ").split():
        t = token.strip().lower()
        if len(t) == 64 and all(c in "0123456789abcdef" for c in t):
            return t
    raise UpdateError("The release's checksum file is unreadable")


def download(url: str, dest: Path, expected_sha256: str, progress: Callable[[int, int], bool]) -> None:
    """Stream ``url`` to ``dest``; ``progress(done, total)`` returns False to cancel. Verifies SHA-256."""
    h = hashlib.sha256()
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with _get(url, 60) as r, open(tmp, "wb") as fh:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = r.read(CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if not progress(done, total):
                    raise UpdateError("Download cancelled")
        if total and done != total:
            raise UpdateError(f"Download incomplete ({done} of {total} bytes)")
        if h.hexdigest() != expected_sha256.lower():
            raise UpdateError("The download doesn't match the release's checksum — not installed")
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def fetch_sha256(url: str) -> str:
    with _get(url, 20) as r:
        return parse_sha256_file(r.read(4096).decode("utf-8", "replace"))


def swap_in(exe: Path, new: Path) -> Path:
    """Put ``new`` where ``exe`` is; the old one becomes ``*.old.exe``. Returns the old path.

    If the second step fails the original is moved back."""
    old = exe.with_name(exe.stem + ".old" + exe.suffix)
    if old.exists():
        old.unlink()
    os.replace(exe, old)                          # allowed while it runs
    try:
        os.replace(new, exe)
    except OSError:
        os.replace(old, exe)
        raise
    return old


def relaunch(exe: Path) -> None:
    """Start the new exe as a fresh process (PyInstaller onefile must not reuse our unpacked files)."""
    env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT="1")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(exe)], env=env, close_fds=True, creationflags=flags, cwd=str(exe.parent))


def install(exe_url: str, progress: Callable[[int, int], bool], sha256: Optional[str] = None,
            sha_url: Optional[str] = None, exe: Optional[Path] = None) -> Path:
    """Download, verify and swap in the new version; returns the exe path to relaunch."""
    exe = exe or current_exe()
    if exe is None:
        raise UpdateError("Automatic install only works in the Windows app")
    expected = sha256 or (fetch_sha256(sha_url) if sha_url else None)
    if not expected:
        raise UpdateError("The release has no checksum to verify the download against")
    new = exe.with_name(exe.stem + ".new" + exe.suffix)
    try:
        download(exe_url, new, expected, progress)
        try:
            swap_in(exe, new)
        except PermissionError as e:
            raise UpdateError(f"No permission to replace {exe} — move the app to a folder you own "
                              f"(e.g. Desktop or Documents) or update it by hand") from e
    finally:
        new.unlink(missing_ok=True)
    return exe


def cleanup_old(exe: Optional[Path] = None) -> None:
    """Delete the previous version left by an update (call at startup)."""
    exe = exe or current_exe()
    if exe is None:
        return
    old = exe.with_name(exe.stem + ".old" + exe.suffix)
    try:
        old.unlink(missing_ok=True)
    except OSError as e:                           # still running for a moment: next start
        _log.info("couldn't remove %s yet: %s", old, e)
