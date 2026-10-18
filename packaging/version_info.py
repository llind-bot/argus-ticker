"""Writes the Windows version resource for PyInstaller (--version-file).

Windows shows FileDescription as the app name in notification headers, Task
Manager and file properties; without it, notifications say "ArgusTicker.exe".

    python packaging/version_info.py build/version_info.txt
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ticker import __version__  # noqa: E402

TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                    subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Argus'),
      StringStruct('FileDescription', 'Argus Ticker'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'ArgusTicker'),
      StringStruct('OriginalFilename', 'ArgusTicker.exe'),
      StringStruct('ProductName', 'Argus Ticker'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def render(version: str = __version__) -> str:
    parts = [int(x) for x in version.split(".")][:4]
    return TEMPLATE.format(t=tuple(parts + [0] * (4 - len(parts))), v=version)


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "version_info.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render())
    print(f"wrote {out} (Argus Ticker {__version__})")
