#!/usr/bin/env python3
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying file COPYING.

"""Corruption fixtures for the Android ELF release checks; no target code runs."""

import importlib.util
import hashlib
from pathlib import Path
import struct
import tempfile
import unittest
import zipfile
import zlib

spec = importlib.util.spec_from_file_location('android_verify', Path(__file__).with_name('verify.py'))
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


def fixture(tags=None, dependency=b'libc.so'):
    data = bytearray(1024)
    data[:16] = b'\x7fELF\x02\x01\x01' + bytes(9)
    struct.pack_into('<HHIQQQIHHHHHH', data, 16,
                     3, 183, 1, 0, 64, 0, 0, 64, 56, 4, 0, 0, 0)
    headers = [
        (1, 6, 0, 0, 0, len(data), len(data), 16384),
        (2, 6, 512, 512, 0, 128, 128, 8),
        (0x6474e551, 6, 0, 0, 0, 0, 0, 16),
        (0x6474e552, 4, 512, 512, 0, 128, 128, 1),
    ]
    for index, header in enumerate(headers):
        struct.pack_into('<II6Q', data, 64 + 56 * index, *header)
    strings = b'\0' + dependency + b'\0'
    data[896:896 + len(strings)] = strings
    if tags is None:
        tags = [(30, 8)]
    dynamic = [(5, 896), (10, len(strings)), (1, 1)] + tags + [(0, 0)]
    for index, entry in enumerate(dynamic):
        struct.pack_into('<qQ', data, 512 + index * 16, *entry)
    return data


class NativeSecurityTests(unittest.TestCase):
    def test_dex_header_digests(self):
        data = bytearray(192)
        data[:8] = b'dex\n039\0'
        struct.pack_into('<II', data, 32, len(data), 112)
        data[12:32] = hashlib.sha1(data[32:]).digest()
        struct.pack_into('<I', data, 8, zlib.adler32(data[12:]) & 0xffffffff)
        verify.check_dex(data)
        # The pinned D8 bug omitted the final 52 bytes from its SHA-1 range.
        data[12:32] = hashlib.sha1(data[32:-52]).digest()
        struct.pack_into('<I', data, 8, zlib.adler32(data[12:]) & 0xffffffff)
        with self.assertRaisesRegex(ValueError, 'SHA-1'):
            verify.check_dex(data)
        data[12:32] = hashlib.sha1(data[32:]).digest()
        with self.assertRaisesRegex(ValueError, 'Adler-32'):
            verify.check_dex(data)

    def test_binding_variants_and_dependency_closure(self):
        for flags in ([(30, 8)], [(0x6ffffffb, 1)], [(24, 0)]):
            self.assertEqual(verify.check_native_security(fixture(flags), set()), {'libc.so'})
        data = fixture(dependency=b'libQt6Core_arm64-v8a.so')
        verify.check_native_security(data, {'libQt6Core_arm64-v8a.so'})
        with self.assertRaisesRegex(ValueError, 'Unresolved'):
            verify.check_native_security(data, set())
        with self.assertRaisesRegex(ValueError, 'contains a path'):
            verify.check_native_security(fixture(dependency=b'/tmp/libc.so'), set())

    def test_dynamic_hardening_tags(self):
        for tags, error in (
            ([], 'NOW'), ([(30, 0)], 'NOW'), ([(0x6ffffffb, 0)], 'NOW'),
            ([(30, 8), (15, 1)], 'RPATH'), ([(30, 8), (29, 1)], 'RUNPATH'),
            ([(30, 12)], 'text relocations'), ([(24, 0), (22, 0)], 'text relocations'),
            ([(30, 8), (30, 8)], 'Duplicate'),
        ):
            with self.subTest(tags=tags), self.assertRaisesRegex(ValueError, error):
                verify.check_native_security(fixture(tags), set())

    def test_program_header_corruptions(self):
        cases = (
            (16, '<H', 2, 'ET_DYN'),
            (64 + 4, '<I', 7, 'Writable executable'),
            (64 + 56 * 2 + 4, '<I', 7, 'non-executable GNU_STACK'),
            (64 + 56 * 2, '<I', 0, 'non-executable GNU_STACK'),
            (64 + 56 * 3, '<I', 0, 'GNU_RELRO'),
            (64 + 56 * 3 + 16, '<Q', 4096, 'GNU_RELRO'),
            (64 + 56 + 32, '<Q', 127, 'dynamic segment'),
            (64 + 56 + 16, '<Q', 600, 'unmapped ELF dynamic'),
            (54, '<H', 55, 'program header table'),
            (32, '<Q', 1024, 'program header table'),
            (64 + 32, '<Q', 1025, 'file bounds'),
        )
        for offset, kind, value, error in cases:
            data = fixture()
            struct.pack_into(kind, data, offset, value)
            with self.subTest(offset=offset, value=value), self.assertRaisesRegex(ValueError, error):
                verify.check_native_security(data, set())
        with self.assertRaisesRegex(ValueError, 'arm64 ELF'):
            verify.check_native_security(fixture()[:63], set())

    def test_dynamic_string_and_termination_corruptions(self):
        for offset, value, error in (
            (520, 4096, 'string table mapping'),
            (536, 0, 'Missing ELF dynamic string table'),
            (552, 1000, 'DT_NEEDED string offset'),
        ):
            data = fixture()
            struct.pack_into('<Q', data, offset, value)
            with self.subTest(offset=offset), self.assertRaisesRegex(ValueError, error):
                verify.check_native_security(data, set())
        data = fixture()
        for offset in range(512, 640, 16):
            struct.pack_into('<qQ', data, offset, 1, 1)
        with self.assertRaisesRegex(ValueError, 'Unterminated'):
            verify.check_native_security(data, set())

    def test_package_rejects_missing_and_duplicate_runtime(self):
        with tempfile.TemporaryDirectory() as directory:
            for names, error in (
                (['jni/arm64-v8a/libapp.so'], 'Unresolved'),
                (['jni/arm64-v8a/libapp.so', 'jni/arm64-v8a/sub/libdep.so'], 'outside'),
                (['jni/arm64-v8a/libapp.so', 'other/arm64-v8a/libapp.so'], 'Duplicate'),
                (['jni/arm64-v8a/libc.so'], 'system library'),
            ):
                path = Path(directory) / 'fixture.aar'
                with zipfile.ZipFile(path, 'w') as archive:
                    for name in names:
                        archive.writestr(name, fixture(dependency=b'libmissing.so'))
                with self.subTest(names=names), self.assertRaisesRegex(ValueError, error):
                    verify.verify(path, check_security=True)
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('jni/arm64-v8a/libapp.so', fixture(dependency=b'libdep.so'))
                archive.writestr('jni/arm64-v8a/libdep.so', fixture())
            verify.verify(path, check_security=True)


if __name__ == '__main__':
    unittest.main()
