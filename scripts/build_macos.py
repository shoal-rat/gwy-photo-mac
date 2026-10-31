"""Build and smoke-test a self-contained, ad-hoc-signed macOS application."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import platform
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "GwyPhotoMac"


def main():
    if sys.platform != "darwin":
        raise SystemExit("macOS app bundles must be built on macOS.")
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    target = args.dist_dir.resolve()
    work = ROOT / "build" / "pyinstaller"
    licenses = ROOT / "build" / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    python_prefix = Path(sys.base_prefix).resolve()
    python_licenses = [Path(sysconfig.get_path("stdlib")) / "LICENSE.txt"]
    for parent in (python_prefix, *list(python_prefix.parents)[:4]):
        python_licenses.extend((parent / "LICENSE", parent / "LICENSE.txt"))
    python_license = next((path for path in python_licenses if path.is_file()), None)
    if python_license is None:
        raise SystemExit("Cannot locate the Python runtime license; refusing an incomplete bundle.")
    shutil.copy2(python_license, licenses / "PYTHON_LICENSE.txt")
    # Preserve dependency license texts and notices from the installed wheels.
    for name in ("Pillow", "numpy", "opencv-python-headless", "PySide6-Essentials", "shiboken6"):
        distribution = importlib.metadata.distribution(name)
        for entry in distribution.files or []:
            parts = str(entry).lower()
            if any(word in parts for word in ("license", "licence", "copying")):
                source = Path(distribution.locate_file(entry))
                if source.is_file():
                    destination = licenses / name / str(entry).replace("../", "")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, destination)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onedir",
        "--name",
        APP_NAME,
        "--osx-bundle-identifier",
        "io.github.shoal-rat.gwy-photo-mac",
        "--paths",
        str(ROOT / "src"),
        "--collect-data",
        "gwy_photo_mac",
        "--add-data",
        f"{licenses}:licenses",
        "--add-data",
        f"{ROOT / 'LICENSE'}:.",
        "--add-data",
        f"{ROOT / 'THIRD_PARTY_NOTICES.md'}:.",
        "--distpath",
        str(target),
        "--workpath",
        str(work),
        "--specpath",
        str(ROOT / "build"),
        str(ROOT / "scripts" / "app_launcher.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    app = target / f"{APP_NAME}.app"
    executable = app / "Contents" / "MacOS" / APP_NAME
    # Work only on the generated bundle. Finder/resource-fork metadata can break signing.
    # Ad-hoc signing needs no hardened-runtime option, identity, or Apple credentials.
    subprocess.run(["xattr", "-cr", str(app)], check=True)
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)
    subprocess.run([str(executable), "--smoke-test"], check=True, timeout=120)
    subprocess.run([str(executable), "--cli", "--version"], check=True, timeout=120)
    # Some macOS versions recreate FinderInfo on loaded framework directories.
    # It is not signed content; remove it again before strict verification/archive.
    subprocess.run(["xattr", "-cr", str(app)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    archive = (
        target
        / f"GwyPhotoMac-v{importlib.metadata.version('gwy-photo-mac')}-macOS-{platform.machine()}.zip"
    )
    subprocess.run(
        ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(archive)], check=True
    )
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n")
    print(f"Built and verified: {archive}")


if __name__ == "__main__":
    main()
