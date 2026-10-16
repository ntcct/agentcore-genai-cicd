"""Build a deterministic deployment zip for AgentCore direct code deployment.

- Installs dependencies as Linux ARM64 wheels (AgentCore runs on Graviton).
- Uses fixed timestamps and sorted entries so identical inputs produce an
  identical zip -> Terraform only redeploys when code/deps actually change.

Usage: python scripts/package.py   (works on Windows, macOS, Linux)
Output: dist/agent.zip
"""

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
ZIP_PATH = DIST / "agent.zip"
FIXED_TIME = (2020, 1, 1, 0, 0, 0)
EXCLUDE_DIRS = {"__pycache__", "bin"}


def main() -> None:
    shutil.rmtree(BUILD, ignore_errors=True)
    BUILD.mkdir(parents=True)
    DIST.mkdir(exist_ok=True)

    subprocess.check_call([
        sys.executable, "-m", "pip", "install",
        "-r", str(APP / "requirements.txt"),
        "--target", str(BUILD),
        "--platform", "manylinux2014_aarch64",
        "--implementation", "cp",
        "--python-version", "3.13",
        "--only-binary=:all:",
        "--no-compile",
        "--quiet",
    ])
    shutil.copy2(APP / "main.py", BUILD / "main.py")

    files = sorted(
        p for p in BUILD.rglob("*")
        if p.is_file() and not (EXCLUDE_DIRS & set(p.relative_to(BUILD).parts))
    )
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(BUILD).as_posix(), FIXED_TIME)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes())

    shutil.rmtree(BUILD, ignore_errors=True)
    print(f"built {ZIP_PATH} ({ZIP_PATH.stat().st_size / 1_048_576:.1f} MiB, {len(files)} files)")


if __name__ == "__main__":
    main()
