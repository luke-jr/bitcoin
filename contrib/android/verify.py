#!/usr/bin/env python3
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying file COPYING.
"""Check arm64 ELF and APK library alignment without extracting the package."""

import argparse
import struct
import zipfile
from pathlib import Path


def verify(path):
    count = 0
    with zipfile.ZipFile(path) as archive, path.open("rb") as raw:
        for entry in archive.infolist():
            if not entry.filename.endswith(".so"):
                continue
            count += 1
            if "/arm64-v8a/" not in entry.filename:
                raise ValueError(f"Unexpected native ABI: {entry.filename}")
            data = archive.read(entry)
            if data[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", data, 18)[0] != 183:
                raise ValueError(f"Expected little-endian arm64 ELF: {entry.filename}")
            offset = struct.unpack_from("<Q", data, 32)[0]
            size, number = struct.unpack_from("<HH", data, 54)
            loads = 0
            for index in range(number):
                header = offset + size * index
                if struct.unpack_from("<I", data, header)[0] != 1:
                    continue
                loads += 1
                file_offset, address = struct.unpack_from("<QQ", data, header + 8)
                alignment = struct.unpack_from("<Q", data, header + 48)[0]
                if alignment < 16384 or file_offset % 16384 != address % 16384:
                    raise ValueError(f"ELF load segment is not 16 KB compatible: {entry.filename}")
            if not loads:
                raise ValueError(f"No ELF load segments: {entry.filename}")
            if path.suffix == ".apk" and entry.compress_type == zipfile.ZIP_STORED:
                raw.seek(entry.header_offset + 26)
                name_size, extra_size = struct.unpack("<HH", raw.read(4))
                payload = entry.header_offset + 30 + name_size + extra_size
                if payload % 16384:
                    raise ValueError(f"Uncompressed APK library is not 16 KB aligned: {entry.filename}")
    if not count:
        raise ValueError("Package contains no native libraries")
    checks = "ELF alignment passed"
    if path.suffix == ".apk":
        checks += "; APK library alignment passed"
    print(f"{path.name}: {count} arm64 libraries; {checks}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packages", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.packages:
        try:
            verify(path)
        except (OSError, ValueError, struct.error, zipfile.BadZipFile) as error:
            parser.exit(1, f"{path}: {error}\n")


if __name__ == "__main__":
    main()
