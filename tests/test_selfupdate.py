import hashlib

import pytest

from ticker import selfupdate, updates

REL = {"tag_name": "v0.4.0", "html_url": "page", "assets": [
    {"name": "ArgusTicker.exe", "browser_download_url": "exe-url", "digest": "sha256:" + "AB" * 32},
    {"name": "ArgusTicker.exe.sha256", "browser_download_url": "sha-url"}]}


def test_parse_release():
    info = updates.parse_release(REL, "0.3.0")
    assert info.newer and info.installable
    assert (info.exe_url, info.sha256, info.sha_url) == ("exe-url", "ab" * 32, "sha-url")
    bare = updates.parse_release({"tag_name": "v0.4.0"}, "0.3.0")
    assert bare.newer and not bare.installable


def test_parse_sha256_file():
    h = "0f" * 32
    assert selfupdate.parse_sha256_file(f"{h}  ArgusTicker.exe\n") == h
    assert selfupdate.parse_sha256_file(f"{h.upper()} *ArgusTicker.exe") == h
    with pytest.raises(selfupdate.UpdateError):
        selfupdate.parse_sha256_file("nothing here")


@pytest.fixture
def release(tmp_path):
    new = tmp_path / "srv" / "ArgusTicker.exe"
    new.parent.mkdir()
    new.write_bytes(b"new version " * 1000)
    return new, hashlib.sha256(new.read_bytes()).hexdigest()


def test_download_verifies_checksum(tmp_path, release):
    src, sha = release
    seen = []
    dest = tmp_path / "out.exe"
    selfupdate.download(src.as_uri(), dest, sha, lambda d, t: seen.append((d, t)) or True)
    assert dest.read_bytes() == src.read_bytes() and seen[-1][0] == src.stat().st_size
    with pytest.raises(selfupdate.UpdateError, match="checksum"):
        selfupdate.download(src.as_uri(), tmp_path / "bad.exe", "00" * 32, lambda d, t: True)
    with pytest.raises(selfupdate.UpdateError, match="cancelled"):
        selfupdate.download(src.as_uri(), tmp_path / "c.exe", sha, lambda d, t: False)
    assert not (tmp_path / "bad.exe").exists() and not list(tmp_path.glob("*.part"))


def test_install_swaps_and_cleanup(tmp_path, release):
    src, sha = release
    app = tmp_path / "app" / "ArgusTicker.exe"
    app.parent.mkdir()
    app.write_bytes(b"old version")
    shafile = tmp_path / "srv" / "ArgusTicker.exe.sha256"
    shafile.write_text(f"{sha}  ArgusTicker.exe\n")
    out = selfupdate.install(src.as_uri(), lambda d, t: True, sha_url=shafile.as_uri(), exe=app)
    assert out == app and app.read_bytes() == src.read_bytes()
    old = app.with_name("ArgusTicker.old.exe")
    assert old.read_bytes() == b"old version"
    assert not app.with_name("ArgusTicker.new.exe").exists()
    selfupdate.cleanup_old(app)
    assert not old.exists()


def test_failed_install_keeps_current(tmp_path, release):
    src, _ = release
    app = tmp_path / "ArgusTicker.exe"
    app.write_bytes(b"old version")
    with pytest.raises(selfupdate.UpdateError):
        selfupdate.install(src.as_uri(), lambda d, t: True, sha256="00" * 32, exe=app)
    assert app.read_bytes() == b"old version" and list(tmp_path.glob("ArgusTicker*")) == [app]


def test_not_frozen_cannot_self_update():
    assert not selfupdate.can_self_update()
    with pytest.raises(selfupdate.UpdateError):
        selfupdate.install("x", lambda d, t: True, sha256="00" * 32)


def test_windows_version_resource_names_the_app():
    import ast
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "version_info", Path(__file__).resolve().parent.parent / "packaging" / "version_info.py")
    vi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vi)
    text = vi.render("0.6.1")
    assert "StringStruct('FileDescription', 'Argus Ticker')" in text and "filevers=(0, 6, 1, 0)" in text
    ast.parse(text)                                   # PyInstaller evals it as Python
