#!/usr/bin/env python3
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying file COPYING.

"""Create a canonical ZIP, optionally aligning stored entries for an Android APK.

Names are sorted by UTF-8 bytes, all files use mode 0644, and timestamps derive
only from SOURCE_DATE_EPOCH. Native libraries and resources.arsc are stored.
Other entries use the build environment's pinned zlib at compression level 9.
This tool does not compile Android resources or sign the resulting archive.
Use --apk for 16-KiB native-library and 4-byte other stored-entry alignment.
"""

import argparse
import datetime
import os
from pathlib import Path
import shutil
import stat
import struct
import sys
import zipfile


def build_archive(source, output, epoch, apk=False):
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Input must be a directory, not a symlink")
    source = source.resolve()
    if output.resolve().is_relative_to(source):
        raise ValueError("Output must be outside the input directory")
    timestamp = datetime.datetime.fromtimestamp(max(epoch, 315532800), datetime.timezone.utc)
    if timestamp.year > 2107:
        raise ValueError("SOURCE_DATE_EPOCH is outside the ZIP timestamp range")
    date_time = (timestamp.year, timestamp.month, timestamp.day, timestamp.hour, timestamp.minute, timestamp.second & ~1)
    files = []
    for directory, directories, filenames in os.walk(source, followlinks=False):
        for name in directories + filenames:
            path = Path(directory) / name
            mode = path.lstat().st_mode
            if not stat.S_ISDIR(mode) and not stat.S_ISREG(mode):
                raise ValueError("Only regular files and directories are permitted")
            if stat.S_ISREG(mode):
                relative = path.relative_to(source).as_posix()
                if "\\" in relative or "\x00" in relative:
                    raise ValueError("Unsupported ZIP entry name")
                files.append((relative.encode("utf-8"), relative, path))
    files.sort()
    created = False
    try:
        with zipfile.ZipFile(output, "x", allowZip64=False, compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            created = True
            for _, name, path in files:
                info = zipfile.ZipInfo(name, date_time)
                info.create_system = 3
                info.create_version = info.extract_version = 20
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                info.compress_type = zipfile.ZIP_STORED if name.endswith(".so") or name == "resources.arsc" else zipfile.ZIP_DEFLATED
                if apk and info.compress_type == zipfile.ZIP_STORED:
                    alignment = 16384 if name.endswith(".so") else 4
                    offset = archive.fp.tell() + 30 + len(name.encode("utf-8"))
                    if offset % alignment:
                        # Android's 0xd935 ZIP extra field contains a uint16
                        # alignment followed by padding. Its header is 6 bytes.
                        padding = -(offset + 6) % alignment
                        info.extra = struct.pack("<HHH", 0xD935, padding + 2, alignment) + b"\0" * padding
                # ZipInfo supplied to open() does not inherit ZipFile's level.
                info._compresslevel = 9
                with path.open("rb") as input_stream:
                    before = os.fstat(input_stream.fileno())
                    info.file_size = before.st_size
                    with archive.open(info, "w") as output_stream:
                        shutil.copyfileobj(input_stream, output_stream, 1024 * 1024)
                    after = os.fstat(input_stream.fileno())
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or path.stat() != after:
                        raise ValueError("Input changed while the archive was being created")
    except BaseException:
        if created:
            output.unlink()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--epoch", type=int, default=os.environ.get("SOURCE_DATE_EPOCH"))
    parser.add_argument("--apk", action="store_true", help="align stored entries for direct APK loading")
    args = parser.parse_args()
    if args.epoch is None:
        parser.error("Set SOURCE_DATE_EPOCH or supply --epoch")
    build_archive(args.source, args.output, args.epoch, args.apk)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, OverflowError, zipfile.LargeZipFile) as error:
        sys.exit(f"APK ZIP: {error}")
