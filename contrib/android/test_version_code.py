#!/usr/bin/env python3
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying file COPYING.

"""Check Android release ordering with CMake alone; no Android SDK required."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


HELPER = Path(__file__).resolve().parents[2] / 'cmake/module/AndroidVersionCode.cmake'


@unittest.skipUnless(shutil.which('cmake'), 'CMake required')
class VersionCodeTests(unittest.TestCase):
    def compute(self, suffix='.knots20260508', rc='0', override='', valid=True):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'check.cmake'
            result = Path(directory) / 'result'
            script.write_text(f'include("{HELPER}")\n'
                              'compute_android_version_code(code "${SUFFIX}" "${RC}" "${OVERRIDE}")\n'
                              f'file(WRITE "{result}" "${{code}}")\n')
            completed = subprocess.run(['cmake', '-DSUFFIX=' + suffix, '-DRC=' + rc,
                                        '-DOVERRIDE=' + override, '-P', str(script)],
                                       text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if valid:
                self.assertEqual(completed.returncode, 0, completed.stdout)
                return int(result.read_text())
            self.assertNotEqual(completed.returncode, 0, completed.stdout)

    def test_release_order(self):
        first = self.compute(rc='1')
        last = self.compute(rc='98')
        final = self.compute()
        next_release = self.compute(suffix='.knots20260509', rc='1')
        self.assertEqual(first, 2026050801)
        self.assertEqual(final, 2026050899)
        self.assertLess(first, last)
        self.assertLess(last, final)
        self.assertLess(final, next_release)
        self.assertGreater(first, 29040300)

    def test_override(self):
        for value in ('1', '00042', '2100000000'):
            self.assertEqual(self.compute(suffix='custom', override=value), int(value))

    def test_limits(self):
        self.assertEqual(self.compute(suffix='.knots20240229'), 2024022999)
        self.assertEqual(self.compute(suffix='.knots20991231'), 2099123199)
        self.compute(suffix='.knots21000101', valid=False)
        for value in ('0', '000', '-1', '+1', '1.5', '1e3', '0x10', ' 1', '2100000001', '9' * 80):
            with self.subTest(override=value):
                self.compute(override=value, valid=False)

    def test_invalid_default(self):
        for suffix in ('custom', '.knots2026050', '.knots202605080', '.knots20260508-dev',
                       '.knots00000101', '.knots20260001', '.knots20261301', '.knots20260100',
                       '.knots20260229', '.knots20260431'):
            with self.subTest(suffix=suffix):
                self.compute(suffix=suffix, valid=False)
        for rc in ('-1', '99', '100', '01', 'abc'):
            with self.subTest(rc=rc):
                self.compute(rc=rc, valid=False)


if __name__ == '__main__':
    unittest.main()
