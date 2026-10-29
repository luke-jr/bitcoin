#!/usr/bin/env python3
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://opensource.org/license/mit/.

"""Remove build times and filesystem metadata from unsigned Java archives."""

from pathlib import Path
import sys
import zipfile


for archive in sorted(Path(sys.argv[1]).rglob("*.jar")):
    if archive.is_symlink():
        continue
    with zipfile.ZipFile(archive) as original:
        entries = {name: original.read(name) for name in original.namelist() if not name.endswith("/")}
    temporary = archive.with_suffix(".jar.tmp")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as normalized:
        for name in sorted(entries, key=lambda name: (name != "META-INF/MANIFEST.MF", name)):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            normalized.writestr(info, entries[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    temporary.replace(archive)
