#!/usr/bin/env python3
# build_cacert_ipk.py - Baut ein IPK-Paket das das Mozilla CA-Zertifikatsbundle aktualisiert

import os
import tarfile
import io

PLUGIN_NAME  = "ca-certificates-mozilla"
VERSION      = "2026.05.30"
ARCHITECTURE = "all"
MAINTAINER   = "saufsoldat"
HOMEPAGE     = "https://github.com/boingbasti/e2-streamanything"
DESCRIPTION  = "Aktuelles Mozilla CA-Zertifikatsbundle (Stand 2026.05.30). Ersetzt das veraltete CA-Bundle auf VTI-Images (Stand 2014). Ermoeglicht HTTPS-Verbindungen zu modernen Servern fuer curl und Python."
DEST_PATH    = "/etc/ssl/certs/ca-certificates.crt"

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
CACERT_FILE = os.path.join(SCRIPT_DIR, "cacert.pem")
OUTPUT_FILE = os.path.join(SCRIPT_DIR, f"{PLUGIN_NAME}_{VERSION}_{ARCHITECTURE}.ipk")

PREINST_SCRIPT = f"""#!/bin/sh
if [ -f {DEST_PATH} ] && [ ! -f {DEST_PATH}.bak ]; then
    cp {DEST_PATH} {DEST_PATH}.bak
fi
"""

POSTINST_SCRIPT = """#!/bin/sh
"""

PRERM_SCRIPT = f"""#!/bin/sh
if [ -f {DEST_PATH}.bak ]; then
    cp {DEST_PATH}.bak {DEST_PATH}
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
Description: {DESCRIPTION}
""".encode("utf-8")

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.GNU_FORMAT) as tar:
        info = tarfile.TarInfo(name="./control")
        info.size = len(control_content)
        tar.addfile(info, io.BytesIO(control_content))

        for script_name, script_content in [
            ("preinst",  PREINST_SCRIPT),
            ("postinst", POSTINST_SCRIPT),
            ("prerm",    PRERM_SCRIPT),
        ]:
            data = script_content.encode("utf-8")
            info = tarfile.TarInfo(name="./" + script_name)
            info.size = len(data)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(data))

    return buf.getvalue()


def build_data_tar():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.GNU_FORMAT) as tar:
        arcname = "./" + DEST_PATH.lstrip("/")
        tar.add(CACERT_FILE, arcname=arcname)
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
    if not os.path.isfile(CACERT_FILE):
        print(f"FEHLER: {CACERT_FILE} nicht gefunden.")
        return

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
