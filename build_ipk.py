#!/usr/bin/env python3
# build_ipk.py - Baut ein Enigma2-IPK-Paket fuer StreamAnything

import os
import tarfile
import io

PLUGIN_NAME  = "enigma2-plugin-extensions-streamanything"
ARCHITECTURE = "all"
MAINTAINER   = "saufsoldat"
HOMEPAGE     = "https://github.com/boingbasti/e2-streamanything"
DESCRIPTION  = "Eigene Streams konfigurieren und abspielen – vollstaendig per WebIF verwaltbar"
INSTALL_PATH = "/usr/lib/enigma2/python/Plugins/Extensions/StreamAnything"

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
PLUGIN_SRC  = os.path.join(SCRIPT_DIR, "StreamAnything")

import xml.etree.ElementTree as _ET
VERSION = _ET.parse(os.path.join(SCRIPT_DIR, "StreamAnything", "meta.xml")).findtext("version") or "unknown"

OUTPUT_FILE = os.path.join(SCRIPT_DIR, f"{PLUGIN_NAME}_{VERSION}_{ARCHITECTURE}.ipk")

# Logos die zum Plugin gehoeren und bei Updates ersetzt werden duerfen.
# Alle anderen PNGs in logos/ sind User-Uploads und werden gesichert/wiederhergestellt.
SYSTEM_LOGOS = "type_stream.png|type_folder.png|sel.png"

PREINST_SCRIPT = f"""#!/bin/sh
LOGO_DIR="{INSTALL_PATH}/logos"
BACKUP_DIR="/tmp/streamanything_logo_backup"
if [ -d "$LOGO_DIR" ]; then
    rm -rf "$BACKUP_DIR"
    mkdir -p "$BACKUP_DIR"
    for f in "$LOGO_DIR"/*.png; do
        [ -f "$f" ] || continue
        cp "$f" "$BACKUP_DIR/$(basename "$f")"
    done
fi
"""

POSTINST_SCRIPT = f"""#!/bin/sh
rm -f {INSTALL_PATH}/*.pyo {INSTALL_PATH}/*.pyc
LOGO_DIR="{INSTALL_PATH}/logos"
BACKUP_DIR="/tmp/streamanything_logo_backup"
if [ -d "$BACKUP_DIR" ]; then
    for f in "$BACKUP_DIR"/*.png; do
        [ -f "$f" ] || continue
        fname=$(basename "$f")
        case "$fname" in
            {SYSTEM_LOGOS}) continue ;;
        esac
        cp "$f" "$LOGO_DIR/$fname"
    done
    rm -rf "$BACKUP_DIR"
fi
"""


def build_control_tar():
    control_content = f"""Package: {PLUGIN_NAME}
Version: {VERSION}
Architecture: {ARCHITECTURE}
Maintainer: {MAINTAINER}
Homepage: {HOMEPAGE}
Section: misc
Priority: optional
License: GPL-2.0
Description: {DESCRIPTION}
""".encode("utf-8")

    preinst_content  = PREINST_SCRIPT.encode("utf-8")
    postinst_content = POSTINST_SCRIPT.encode("utf-8")

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.GNU_FORMAT) as tar:
        info = tarfile.TarInfo(name="./control")
        info.size = len(control_content)
        tar.addfile(info, io.BytesIO(control_content))

        info = tarfile.TarInfo(name="./preinst")
        info.size = len(preinst_content)
        info.mode = 0o755
        tar.addfile(info, io.BytesIO(preinst_content))

        info = tarfile.TarInfo(name="./postinst")
        info.size = len(postinst_content)
        info.mode = 0o755
        tar.addfile(info, io.BytesIO(postinst_content))

    return buf.getvalue()


def build_data_tar():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.GNU_FORMAT) as tar:
        for root, dirs, files in os.walk(PLUGIN_SRC):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            rel_dir = os.path.relpath(root, PLUGIN_SRC)
            if rel_dir == ".":
                arcdir = "./" + INSTALL_PATH.lstrip("/")
            else:
                arcdir = "./" + INSTALL_PATH.lstrip("/") + "/" + rel_dir.replace("\\", "/")
            dir_info = tarfile.TarInfo(name=arcdir)
            dir_info.type = tarfile.DIRTYPE
            dir_info.mode = 0o755
            tar.addfile(dir_info)
            for fname in sorted(files):
                if fname.endswith(".pyc") or fname.endswith(".pyo"):
                    continue
                fpath = os.path.join(root, fname)
                rel = os.path.relpath(fpath, PLUGIN_SRC)
                arcname = "./" + INSTALL_PATH.lstrip("/") + "/" + rel.replace("\\", "/")
                tar.add(fpath, arcname=arcname)
    return buf.getvalue()


def write_ar(path, members):
    with open(path, "wb") as f:
        f.write(b"!<arch>\n")
        for name, data in members:
            name_b  = name.encode("utf-8").ljust(16)[:16]
            mtime_b = b"0".ljust(12)
            uid_b   = b"0".ljust(6)
            gid_b   = b"0".ljust(6)
            mode_b  = b"100644".ljust(8)
            size_b  = str(len(data)).encode("utf-8").ljust(10)
            magic_b = b"\x60\x0a"
            f.write(name_b + mtime_b + uid_b + gid_b + mode_b + size_b + magic_b)
            f.write(data)
            if len(data) % 2 != 0:
                f.write(b"\n")


def main():
    print("Baue control.tar.gz ...")
    control_tar = build_control_tar()

    print("Baue data.tar.gz ...")
    data_tar = build_data_tar()

    print(f"Schreibe {OUTPUT_FILE} ...")
    write_ar(OUTPUT_FILE, [
        ("debian-binary", b"2.0\n"),
        ("control.tar.gz", control_tar),
        ("data.tar.gz", data_tar),
    ])

    size_kb = os.path.getsize(OUTPUT_FILE) // 1024
    print(f"Fertig: {os.path.basename(OUTPUT_FILE)} ({size_kb} KB)")


if __name__ == "__main__":
    main()
