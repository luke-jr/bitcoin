#!/usr/bin/env python3
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or https://opensource.org/license/mit/.

"""Assemble source-built Guix outputs into the Android native toolchain."""

import argparse
import json
from pathlib import Path
import shlex
import shutil
import subprocess


def check_android_elf(readelf, library, allowed_libraries, soname=None):
    report = subprocess.check_output([str(readelf), "-h", "-d", "-l", str(library)], text=True)
    if "AArch64" not in report:
        raise RuntimeError(f"{library}: expected arm64 code")
    if "(RPATH)" in report or "(RUNPATH)" in report:
        raise RuntimeError(f"{library}: Android payload must not have a host library search path")
    if soname and not any("(SONAME)" in line and "[" + soname + "]" in line
                          for line in report.splitlines()):
        raise RuntimeError(f"{library}: unexpected SONAME")
    loads = 0
    for line in report.splitlines():
        if "(NEEDED)" in line and not any("[" + name + "]" in line for name in allowed_libraries):
            raise RuntimeError(f"{library}: unexpected runtime dependency: " + line)
        if line.strip().startswith("LOAD"):
            loads += 1
            if line.split()[-1] != "0x4000":
                raise RuntimeError(f"{library}: missing 16 KiB page alignment: " + line)
    if not loads:
        raise RuntimeError(f"{library}: no ELF load segments")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "sysroot", "runtime", "clang", "llvm", "linker", "shell", "cmake"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--shared", action="store_true", help="also provide the GUI shared C++ runtime")
    args = parser.parse_args()
    if args.shared:
        check_android_elf(args.llvm / "bin/llvm-readelf", args.runtime / "lib/libc++_shared.so",
                          ("libc.so", "libm.so", "libdl.so"), "libc++_shared.so")
    shutil.copytree(args.runtime / "share/licenses/android-runtime",
                    args.output / "share/licenses/android-runtime")
    ndk = args.output / "lib/android-toolchain"
    toolchain = ndk / "toolchains/llvm/prebuilt/linux-x86_64"
    binary = toolchain / "bin"
    binary.mkdir(parents=True)
    sysroot = toolchain / "sysroot"
    shutil.copytree(args.sysroot, sysroot, symlinks=True)
    for directory in [sysroot, *sysroot.rglob("*")]:
        if directory.is_dir() and not directory.is_symlink():
            directory.chmod(directory.stat().st_mode | 0o200)
    cxx_include = sysroot / "usr/include/c++/v1"
    cxx_include.parent.mkdir(parents=True)
    cxx_include.symlink_to(args.runtime / "include/c++/v1")
    library = sysroot / "usr/lib/aarch64-linux-android"
    for name in ("libc++.a", "libc++abi.a", "libunwind.a"):
        (library / name).symlink_to(args.runtime / "lib" / name)
    (library / "libc++_static.a").symlink_to("libc++.a")
    if args.shared:
        (library / "libc++_shared.so").symlink_to(args.runtime / "lib/libc++_shared.so")
        (library / "libc++.so").symlink_to("libc++_shared.so")
    resource = args.runtime / "lib/clang/18"
    # CMake's Android platform adds -latomic. These functions are compiled in
    # compiler-rt (COMPILER_RT_EXCLUDE_ATOMIC_BUILTIN=OFF), as in modern NDKs.
    (library / "libatomic.a").symlink_to(resource / "lib/linux/libclang_rt.builtins-aarch64-android.a")
    for name in ("llvm-ar", "llvm-ranlib", "llvm-nm", "llvm-strip", "llvm-objcopy", "llvm-objdump", "llvm-readelf", "llvm-readobj"):
        (binary / name).symlink_to(args.llvm / "bin" / name)
    (binary / "ld.lld").symlink_to(args.linker)

    # Upstream Clang does not use the NDK's default compiler-rt configuration.
    # Explicit paths also prevent the host Guix C/C++ search paths leaking into
    # target builds. This toolchain supports arm64/API 28 only.
    common = ["--target=aarch64-linux-android28", "--start-no-unused-arguments",
              "--sysroot=" + str(sysroot), "-resource-dir=" + str(resource),
              "-fuse-ld=" + str(args.linker), "--rtlib=compiler-rt", "--unwindlib=libunwind",
              "-nostdinc", "-Wno-unused-command-line-argument",
              "-L" + str(library), "-Wl,--no-undefined", "-Wl,-z,max-page-size=16384"]
    for name in ("clang", "clang++"):
        flags = common.copy()
        if name == "clang++":
            flags.extend(["-stdlib=libc++", "-isystem", str(cxx_include)])
            if not args.shared:
                flags.append("-static-libstdc++")
        flags.extend(["-isystem", str(resource / "include"),
                      "-isystem", str(sysroot / "usr/include/aarch64-linux-android"),
                      "-isystem", str(sysroot / "usr/include"), "--end-no-unused-arguments"])
        command = [str(args.clang / "bin" / name), *flags]
        wrapper = binary / name
        wrapper.write_text("#!" + str(args.shell) + "\n"
                           "unset C_INCLUDE_PATH CPLUS_INCLUDE_PATH CPATH LIBRARY_PATH\n"
                           "exec " + shlex.join(command) + ' "$@"\n', encoding="utf-8")
        wrapper.chmod(0o755)
        for prefix in ("aarch64-linux-android28-", "aarch64-linux-android-"):
            (binary / (prefix + name)).symlink_to(name)
            exported = args.output / "bin" / (prefix + name)
            exported.parent.mkdir(exist_ok=True)
            exported.symlink_to(binary / (prefix + name))

    # CMake requires the first field to be literally "Android NDK". The numeric
    # revision belongs to our layout; it is not a Google NDK release number.
    (ndk / "source.properties").write_text(
        "Pkg.Desc = Android NDK\nPkg.Revision = 1.0.0\n"
        "Pkg.Source = Bitcoin Knots source-built native toolchain\n", encoding="utf-8")
    (ndk / "README").write_text(
        "Bitcoin Knots source-built native toolchain\n"
        "LLVM 18.1.8; Android arm64 API 28; source libc++ with LLVM unwinding.\n"
        "CMake compatibility metadata revision 1.0.0 describes this layout.\n"
        "This is not a Google NDK distribution or a complete Android SDK.\n"
        "System .so files in the sysroot are link-time stubs, never payloads.\n", encoding="utf-8")
    metadata = ndk / "meta"
    metadata.mkdir()
    (metadata / "platforms.json").write_text(json.dumps({"min": 28, "max": 28, "aliases": {}}, sort_keys=True) + "\n", encoding="utf-8")
    (metadata / "abis.json").write_text(json.dumps({"arm64-v8a": {
        "bitness": 64, "default": True, "deprecated": False, "proc": "aarch64",
        "arch": "arm64", "triple": "aarch64-linux-android", "llvm_triple": "aarch64-linux-android"}}, sort_keys=True) + "\n", encoding="utf-8")
    cmake_metadata = ndk / "build/cmake"
    cmake_metadata.mkdir(parents=True)
    (cmake_metadata / "platforms.cmake").write_text(
        "set(NDK_MIN_PLATFORM_LEVEL 28)\nset(NDK_MAX_PLATFORM_LEVEL 28)\n", encoding="utf-8")
    stl = "c++_shared" if args.shared else "c++_static"
    (cmake_metadata / "android.toolchain.cmake").write_text(
        "# Bitcoin Knots source-built Android toolchain, compatibility layout 1.0.0.\n"
        "set(CMAKE_SYSTEM_NAME Android)\nset(CMAKE_SYSTEM_VERSION 28)\n"
        'set(CMAKE_ANDROID_NDK "' + str(ndk) + '")\n'
        'set(CMAKE_SYSROOT "' + str(sysroot) + '")\n'
        "set(CMAKE_ANDROID_ARCH_ABI arm64-v8a)\n"
        "set(ANDROID_ABI arm64-v8a)\nset(ANDROID_NATIVE_API_LEVEL 28)\n"
        "set(ANDROID_PLATFORM android-28)\nset(ANDROID_NDK_REVISION 1.0.0)\n"
        'set(ANDROID_NDK_ROOT "' + str(ndk) + '")\n'
        'set(ANDROID_NDK "' + str(ndk) + '")\n'
        'set(ANDROID_TOOLCHAIN_ROOT "' + str(toolchain) + '")\n'
        "set(ANDROID_NDK_HOST_SYSTEM_NAME linux-x86_64)\nset(ANDROID_HOST_TAG linux-x86_64)\n"
        'set(ANDROID_STL "' + stl + '" CACHE STRING "Android C++ runtime")\n'
        'set(CMAKE_ANDROID_STL_TYPE "${ANDROID_STL}")\n', encoding="utf-8")

    # Verify the public interface through CMake's built-in Android support.
    # This catches compiler defaults, accidental host libraries, missing CRT,
    # static runtime PIC errors, and incomplete exception/thread dependencies.
    probe = Path("android-toolchain-probe").resolve()
    probe.mkdir()
    (probe / "CMakeLists.txt").write_text(
        "cmake_minimum_required(VERSION 3.22)\nproject(AndroidProbe LANGUAGES C CXX)\n"
        "add_library(probe SHARED probe.cpp)\n"
        "target_compile_features(probe PRIVATE cxx_std_20)\n"
        "target_link_options(probe PRIVATE -Wl,--no-undefined)\n", encoding="utf-8")
    (probe / "probe.cpp").write_text(
        '#include <atomic>\n#include <filesystem>\n#include <string>\n#include <thread>\n#include <vector>\n'
        'extern "C" int knots_runtime_probe() {\n'
        '  struct Wide { unsigned words[8]; }; std::atomic<Wide> wide{};\n'
        '  std::vector<std::string> values{"source", "runtime"};\n'
        '  std::thread worker([&] { values.push_back(std::filesystem::path("/data").string()); });\n'
        '  worker.join();\n'
        '  try { throw values.size(); } catch (std::size_t n) { return static_cast<int>(n + wide.load().words[0]); }\n}\n', encoding="utf-8")
    subprocess.run([str(args.cmake), "-S", str(probe), "-B", str(probe / "build"),
                    "-DCMAKE_SYSTEM_NAME=Android", "-DCMAKE_SYSTEM_VERSION=28",
                    "-DCMAKE_ANDROID_ARCH_ABI=arm64-v8a", "-DCMAKE_ANDROID_STL_TYPE=" + stl,
                    "-DCMAKE_ANDROID_NDK=" + str(ndk)], check=True)
    subprocess.run([str(args.cmake), "--build", str(probe / "build"), "--parallel", "2"], check=True)
    allowed = ("libc.so", "libm.so", "libdl.so") + (("libc++_shared.so",) if args.shared else ())
    check_android_elf(binary / "llvm-readelf", probe / "build/libprobe.so", allowed)


if __name__ == "__main__":
    main()
