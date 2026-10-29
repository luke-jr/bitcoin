#!/usr/bin/env python3
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying file COPYING.
"""Check DEX integrity, arm64 alignment and optional native release hardening.

Dependency checks cover library names, not individual symbol availability at the
minimum Android API. The source-built target sysroot controls that API boundary.
"""

import argparse
import hashlib
import struct
import zipfile
import zlib
from pathlib import Path


# Public NDK libraries available by the application's minimum Android API 28.
# libc++_shared.so is deliberately absent: it must be supplied in the package.
SYSTEM_LIBRARIES = frozenset({
    'libc.so', 'libm.so', 'libdl.so', 'liblog.so', 'libandroid.so', 'libz.so',
    'libEGL.so', 'libGLESv1_CM.so', 'libGLESv2.so', 'libGLESv3.so',
    'libjnigraphics.so', 'libnativewindow.so', 'libvulkan.so', 'libOpenSLES.so',
    'libOpenMAXAL.so', 'libaaudio.so', 'libmediandk.so', 'libcamera2ndk.so',
    'libneuralnetworks.so', 'libsync.so',
})


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_dex(data):
    require(len(data) >= 112 and data[:4] == b'dex\n' and data[7] == 0
            and data[4:7] in (b'035', b'037', b'038', b'039', b'040'),
            'Unsupported DEX header')
    require(struct.unpack_from('<II', data, 32) == (len(data), 112), 'Invalid DEX file size or header size')
    require(hashlib.sha1(data[32:]).digest() == data[12:32], 'Invalid DEX SHA-1 signature')
    require(zlib.adler32(data[12:]) & 0xffffffff == struct.unpack_from('<I', data, 8)[0],
            'Invalid DEX Adler-32 checksum')


def program_headers(data, strict=False):
    require(len(data) >= 64 and data[:6] == b'\x7fELF\x02\x01'
            and struct.unpack_from('<H', data, 18)[0] == 183,
            'Expected little-endian arm64 ELF')
    if strict:
        require(data[6] == 1 and struct.unpack_from('<I', data, 20)[0] == 1,
                'Unsupported ELF version')
    offset = struct.unpack_from('<Q', data, 32)[0]
    header_size, size, number = struct.unpack_from('<HHH', data, 52)
    require(header_size == 64 and size == 56 and 0 < number < 0xffff
            and offset >= 64 and offset + size * number <= len(data),
            'Invalid ELF program header table')
    headers = []
    for index in range(number):
        kind, flags, file_offset, address, _, file_size, memory_size, alignment = struct.unpack_from(
            '<II6Q', data, offset + size * index)
        require(file_offset + file_size <= len(data), 'ELF segment exceeds file bounds')
        if kind == 1:
            require(file_size <= memory_size and address + memory_size < 2**64,
                    'Invalid ELF load segment size')
        headers.append((kind, flags, file_offset, address, file_size, memory_size, alignment))
    require(any(header[0] == 1 for header in headers), 'No ELF load segments')
    return headers


def check_native_security(data, packaged_libraries):
    """Validate ELF64 program/dynamic headers without executing target code."""
    headers = program_headers(data, strict=True)
    require(struct.unpack_from('<H', data, 16)[0] == 3, 'Expected ET_DYN shared library')
    loads = [header for header in headers if header[0] == 1]
    require(all(header[1] & 3 != 3 for header in loads), 'Writable executable ELF load segment')
    stacks = [header for header in headers if header[0] == 0x6474e551]
    require(len(stacks) == 1 and not stacks[0][1] & 1, 'Missing non-executable GNU_STACK')
    relro = [header for header in headers if header[0] == 0x6474e552]
    require(len(relro) == 1 and relro[0][5] > 0 and any(
        load[3] <= relro[0][3] and relro[0][3] + relro[0][5] <= load[3] + load[5]
        for load in loads), 'Missing or unmapped GNU_RELRO')
    dynamics = [header for header in headers if header[0] == 2]
    require(len(dynamics) == 1, 'Expected one ELF dynamic segment')
    dynamic = dynamics[0]
    require(dynamic[4] > 0 and dynamic[4] % 16 == 0 and any(
        load[2] <= dynamic[2] and dynamic[2] + dynamic[4] <= load[2] + load[4]
        and dynamic[3] - load[3] == dynamic[2] - load[2]
        for load in loads), 'Invalid or unmapped ELF dynamic segment')
    tags = {}
    for offset in range(dynamic[2], dynamic[2] + dynamic[4], 16):
        tag, value = struct.unpack_from('<qQ', data, offset)
        if tag == 0:
            break
        tags.setdefault(tag, []).append(value)
    else:
        raise ValueError('Unterminated ELF dynamic segment')
    for tag in (5, 10, 15, 22, 24, 29, 30, 0x6ffffffb):
        require(len(tags.get(tag, [])) <= 1, 'Duplicate ELF dynamic singleton tag')
    flags = tags.get(30, [0])[0]
    flags1 = tags.get(0x6ffffffb, [0])[0]
    require(15 not in tags and 29 not in tags, 'ELF RPATH or RUNPATH is forbidden')
    require(22 not in tags and not flags & 4, 'ELF text relocations are forbidden')
    require(24 in tags or flags & 8 or flags1 & 1, 'Missing immediate binding (NOW)')
    require(5 in tags and 10 in tags and tags[10][0] > 0, 'Missing ELF dynamic string table')
    address, length = tags[5][0], tags[10][0]
    mappings = [load[2] + address - load[3] for load in loads
                if load[3] <= address and address + length <= load[3] + load[4]]
    require(len(mappings) == 1, 'Invalid ELF dynamic string table mapping')
    strings = data[mappings[0]:mappings[0] + length]
    require(strings[0] == 0 and strings[-1] == 0, 'Invalid ELF dynamic string table')
    needed = set()
    for offset in tags.get(1, []):
        require(offset < length, 'Invalid DT_NEEDED string offset')
        end = strings.find(b'\0', offset)
        require(end > offset, 'Empty or unterminated DT_NEEDED name')
        try:
            name = strings[offset:end].decode('ascii')
        except UnicodeDecodeError as error:
            raise ValueError('Non-ASCII DT_NEEDED name') from error
        require('/' not in name and '\\' not in name and name not in ('.', '..'),
                'DT_NEEDED contains a path')
        require(name not in needed, 'Duplicate DT_NEEDED library')
        needed.add(name)
        require(name in SYSTEM_LIBRARIES or name in packaged_libraries,
                f'Unresolved Android native dependency: {name}')
    return needed


def verify(path, check_security=False):
    count = 0
    with zipfile.ZipFile(path) as archive, path.open("rb") as raw:
        native_entries = [entry for entry in archive.infolist() if entry.filename.endswith('.so')]
        packaged_libraries = {Path(entry.filename).name for entry in native_entries}
        if check_security:
            require(len(packaged_libraries) == len(native_entries), 'Duplicate native library name')
            require(not packaged_libraries & SYSTEM_LIBRARIES, 'Packaged Android system library or linking stub')
            require(all(Path(entry.filename).parent.name == 'arm64-v8a'
                        for entry in native_entries), 'Native library outside the arm64 library directory')
        for entry in archive.infolist():
            if entry.filename.endswith('.dex'):
                try:
                    check_dex(archive.read(entry))
                except ValueError as error:
                    raise ValueError(f'{entry.filename}: {error}') from error
            if not entry.filename.endswith(".so"):
                continue
            count += 1
            if "/arm64-v8a/" not in entry.filename:
                raise ValueError(f"Unexpected native ABI: {entry.filename}")
            data = archive.read(entry)
            try:
                headers = program_headers(data)
                if check_security:
                    check_native_security(data, packaged_libraries)
            except ValueError as error:
                raise ValueError(f'{entry.filename}: {error}') from error
            for kind, _, file_offset, address, _, _, alignment in headers:
                if kind != 1:
                    continue
                if alignment < 16384 or file_offset % 16384 != address % 16384:
                    raise ValueError(f"ELF load segment is not 16 KB compatible: {entry.filename}")
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
    if check_security:
        checks += '; native dependency and hardening checks passed'
    print(f"{path.name}: {count} arm64 libraries; {checks}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-security', action='store_true')
    parser.add_argument("packages", nargs="+", type=Path)
    args = parser.parse_args()
    for path in args.packages:
        try:
            verify(path, check_security=args.check_security)
        except (OSError, ValueError, struct.error, zipfile.BadZipFile) as error:
            parser.exit(1, f"{path}: {error}\n")


if __name__ == "__main__":
    main()
