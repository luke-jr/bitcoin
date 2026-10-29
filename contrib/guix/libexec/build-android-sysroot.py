#!/usr/bin/env python3
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://opensource.org/license/mit/.

"""Build the arm64/API 28 linking sysroot from pinned AOSP sources.

The shared libraries produced here are NDK link-time stubs, not device
implementations. They must never be included in an application or module.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def run(*command):
    subprocess.run([str(item) for item in command], check=True)


def copy_headers(source, destination):
    for source_file in sorted(source.rglob("*.h")):
        target = destination / source_file.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("bionic", "logging", "jni", "crt", "ndkstubgen", "symbolfile", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--cc", required=True)
    parser.add_argument("--linker", required=True)
    parser.add_argument("--readelf", required=True)
    args = parser.parse_args()
    # Guix's native inputs advertise host headers through these variables.
    # A target sysroot must resolve only Bionic and Clang's builtin headers.
    for variable in ("C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "CPATH", "LIBRARY_PATH"):
        os.environ.pop(variable, None)
    args.output.mkdir(parents=True, exist_ok=True)
    include = args.output / "usr/include"
    library = args.output / "usr/lib/aarch64-linux-android/28"
    library.mkdir(parents=True, exist_ok=True)
    libc = args.bionic / "libc"
    copy_headers(libc / "include", include)
    for name in ("asm-generic", "drm", "linux", "misc", "mtd", "rdma", "scsi", "sound", "video", "xen"):
        copy_headers(libc / "kernel/uapi" / name, include / name)
    copy_headers(libc / "kernel/uapi/asm-arm64", include / "aarch64-linux-android")
    copy_headers(libc / "kernel/android/uapi/linux", include / "linux")
    copy_headers(libc / "kernel/android/scsi/scsi", include / "scsi")
    copy_headers(args.logging / "liblog/include/android", include / "android")
    copy_headers(args.jni, include)

    # ndkstubgen is two standard-library-only Python modules from Soong.
    work = Path("android-sysroot-build").resolve()
    work.mkdir()
    shutil.copyfile(args.ndkstubgen / "__init__.py", work / "ndkstubgen.py")
    shutil.copyfile(args.symbolfile / "__init__.py", work / "symbolfile.py")
    # These release maps contain numeric API levels. An unknown future codename
    # is intentionally an error, instead of silently widening the exposed ABI.
    (work / "api-map.json").write_text(json.dumps({}), encoding="utf-8")
    cc = [args.cc, "--target=aarch64-linux-android28", "--sysroot=" + str(args.output),
          "-fuse-ld=" + args.linker, "-fPIC", "-O2", "-mbranch-protection=standard"]
    maps = {
        "libc": libc / "libc.map.txt",
        "libm": args.bionic / "libm/libm.map.txt",
        "libdl": args.bionic / "libdl/libdl.map.txt",
        "liblog": args.logging / "liblog/liblog.map.txt",
    }
    for name, symbols in maps.items():
        source = work / (name + ".c")
        version = work / (name + ".map")
        run(sys.executable, work / "ndkstubgen.py", "--arch", "arm64", "--api", "28",
            "--api-map", work / "api-map.json", symbols, source, version, work / (name + ".symbols"))
        run(*cc, "-nostdlib", "-shared", "-fno-builtin", "-Wl,--build-id=sha1",
            "-Wl,-soname," + name + ".so", "-Wl,--version-script=" + str(version),
            "-Wl,-z,max-page-size=16384", source, "-o", library / (name + ".so"))

    crt_source = libc / "arch-common/bionic"
    for name, source in (("crtbegin_dynamic.o", "crtbegin.c"), ("crtbegin_so.o", "crtbegin_so.c"),
                         ("crtend_android.o", "crtend.S"), ("crtend_so.o", "crtend_so.S")):
        sources = [crt_source / source]
        if name.startswith("crtbegin"):
            sources.append(args.crt / "crtbrand.S")
        run(*cc, "-I" + str(libc), "-I" + str(crt_source), "-DPLATFORM_SDK_VERSION=28",
            '-DABI_NDK_VERSION="knots-source"', '-DABI_NDK_BUILD_NUMBER="0"',
            "-nostdlib", "-no-pie", "-Wl,-r", "-Wa,--noexecstack", "-Wl,-z,noexecstack",
            *sources, "-o", library / name)

    # Exercise headers, API filtering, CRT, and shared-library linking without
    # executing target code or requiring a prebuilt target runtime.
    smoke = work / "smoke.c"
    smoke.write_text('#include <jni.h>\n#include <pthread.h>\n#include <stdlib.h>\n'
                     '#include <android/log.h>\nvoid *knots_sysroot_probe(void) {'
                     ' __android_log_write(4, "knots", "sysroot"); return malloc(8); }\n', encoding="utf-8")
    probe = work / "smoke.so"
    run(*cc, "-shared", "-nostdlib", "-Wl,--no-undefined", "-Wl,-z,max-page-size=16384",
        library / "crtbegin_so.o", smoke, "-L" + str(library), "-lc", "-llog",
        library / "crtend_so.o", "-o", probe)
    report = subprocess.check_output([args.readelf, "-h", "-d", "-n", str(probe)], text=True)
    if "AArch64" not in report or "libc.so" not in report or "liblog.so" not in report or "Android" not in report:
        raise RuntimeError("sysroot probe is missing the target ABI, dependencies, or Android ELF note")
    (args.output / "LINK-TIME-STUBS-ONLY").write_text(
        "libc.so, libm.so, libdl.so and liblog.so are link-time NDK stubs.\n"
        "Do not ship these files in an Android application or native module.\n", encoding="utf-8")


if __name__ == "__main__":
    main()
