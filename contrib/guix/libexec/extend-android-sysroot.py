#!/usr/bin/env python3
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://opensource.org/license/mit/.

"""Add source-derived Android graphics/windowing link interfaces to a sysroot."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "output", "ndkstubgen", "symbolfile", "framework-android", "framework-graphics",
                 "native-include", "native-opengl", "native-window", "native-rect"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--cc", required=True)
    parser.add_argument("--linker", required=True)
    args = parser.parse_args()
    for variable in ("C_INCLUDE_PATH", "CPLUS_INCLUDE_PATH", "CPATH", "LIBRARY_PATH"):
        os.environ.pop(variable, None)
    shutil.copytree(args.base, args.output, symlinks=True)
    for directory in [args.output, *args.output.rglob("*")]:
        if directory.is_dir() and not directory.is_symlink():
            directory.chmod(directory.stat().st_mode | 0o200)
    include = args.output / "usr/include"
    library = args.output / "usr/lib/aarch64-linux-android/28"
    for source in (args.native_include / "android", args.native_window / "include/android", args.native_rect / "include/android"):
        for header in sorted(source.rglob("*.h")):
            target = include / "android" / header.relative_to(source)
            target.parent.mkdir(exist_ok=True, parents=True)
            shutil.copyfile(header, target)
    for name in ("EGL", "GLES", "GLES2", "GLES3", "KHR"):
        source = args.native_opengl / "include" / name
        for header in sorted(source.rglob("*.h")):
            target = include / name / header.relative_to(source)
            target.parent.mkdir(exist_ok=True, parents=True)
            shutil.copyfile(header, target)
    work = Path("android-graphics-build").resolve()
    work.mkdir(exist_ok=True)
    shutil.copyfile(args.ndkstubgen / "__init__.py", work / "ndkstubgen.py")
    shutil.copyfile(args.symbolfile / "__init__.py", work / "symbolfile.py")
    # Final API levels from android/api_levels.go at the same pinned Soong
    # revision as ndkstubgen. Unknown codenames remain hard errors.
    (work / "api-map.json").write_text(json.dumps({
        "Tiramisu": 33, "UpsideDownCake": 34, "VanillaIceCream": 35}), encoding="utf-8")
    # AOSP sets unversioned_until=current on the legacy graphics libraries;
    # adding ELF versions to them would fail on actual API 28 devices.
    maps = [("libandroid", args.framework_android / "libandroid.map.txt", False),
            ("libjnigraphics", args.framework_graphics / "jni/libjnigraphics.map.txt", False),
            ("libnativewindow", args.native_window / "libnativewindow.map.txt", True)]
    maps += [(name, args.native_opengl / "libs" / (name + ".map.txt"), False)
             for name in ("libEGL", "libGLESv1_CM", "libGLESv2", "libGLESv3")]
    cc = [args.cc, "--target=aarch64-linux-android28", "--sysroot=" + str(args.output),
          "-fuse-ld=" + args.linker, "-fPIC", "-O2"]
    for name, symbols, versioned in maps:
        source, version = work / (name + ".c"), work / (name + ".map")
        subprocess.run([sys.executable, str(work / "ndkstubgen.py"), "--arch", "arm64", "--api", "28",
                        "--api-map", str(work / "api-map.json"), str(symbols), str(source), str(version),
                        str(work / (name + ".symbols"))], check=True)
        flags = ["-Wl,--version-script=" + str(version)] if versioned else []
        subprocess.run([*cc, "-nostdlib", "-shared", "-fno-builtin", "-Wl,--build-id=sha1",
                        "-Wl,-soname," + name + ".so", "-Wl,-z,max-page-size=16384", *flags,
                        str(source), "-o", str(library / (name + ".so"))], check=True)
    probe = work / "probe.c"
    probe.write_text('#include <android/asset_manager.h>\n#include <android/bitmap.h>\n'
                     '#include <EGL/egl.h>\n#include <GLES2/gl2.h>\n'
                     'void *knots_graphics_probe(JNIEnv *e, jobject b) { AndroidBitmapInfo i;\n'
                     'AndroidBitmap_getInfo(e,b,&i); glFinish(); eglGetDisplay(EGL_DEFAULT_DISPLAY);\n'
                     'return AAssetManager_open(0,"probe",AASSET_MODE_UNKNOWN); }\n', encoding="utf-8")
    subprocess.run([*cc, "-nostdlib", "-shared", "-Wl,--no-undefined", str(probe),
                    "-L" + str(library), "-landroid", "-ljnigraphics", "-lEGL", "-lGLESv2",
                    "-o", str(work / "probe.so")], check=True)


if __name__ == "__main__":
    main()
