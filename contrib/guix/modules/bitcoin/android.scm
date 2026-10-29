;;; Copyright (c) 2026 The Bitcoin Knots developers
;;; Distributed under the MIT software license, see the accompanying
;;; file COPYING or https://opensource.org/license/mit/.

(define-module (bitcoin android)
  #:use-module (guix packages)
  #:use-module (bitcoin gitiles)
  #:use-module (guix gexp)
  #:use-module (guix search-paths)
  #:use-module (guix utils)
  #:use-module (guix build-system cmake)
  #:use-module (guix build-system gnu)
  #:use-module ((guix licenses) #:prefix license:)
  #:use-module (gnu packages bash)
  #:use-module (gnu packages cmake)
  #:use-module (gnu packages llvm)
  #:use-module (gnu packages python)
  #:use-module (srfi srfi-1))

;; Guix's native Clang intentionally hardcodes host libc and compiler-rt paths.
;; Android needs upstream --sysroot/-resource-dir behavior instead. Keep the
;; source bootstrap and the unrelated LLVM patches from the pinned package.
(define-public android-clang-18
  (package
    (inherit clang-18)
    (name "clang-android")
    (source
     (origin
       (inherit (package-source clang-18))
       (patches
        (filter (lambda (patch)
                  (not (string-suffix? "clang-18.0-libc-search-path.patch" patch)))
                (origin-patches (package-source clang-18))))))
    (arguments
     (substitute-keyword-arguments (package-arguments clang-18)
       ((#:tests? _ #t) #f)
       ((#:configure-flags flags)
        #~(append #$flags
                  (list "-DC_INCLUDE_DIRS=" "-DGCC_INSTALL_PREFIX="
                        "-DCLANG_INCLUDE_TESTS=OFF")))
       ((#:phases phases)
        #~(modify-phases #$phases
            (delete 'set-glibc-file-names)))))
    (synopsis "Source-built Clang with upstream Android sysroot behavior")))

;; Source trees only. Hash the extracted content because Gitiles archives
;; contain request timestamps. Neither SDK nor NDK binaries are build inputs.
(define (aosp-source project commit directory hash)
  (origin
    (method gitiles-fetch)
    (uri (string-append "https://android.googlesource.com/" project
                        "/+archive/" commit
                        (if directory (string-append "/" directory) "")
                        ".tar.gz"))
    (file-name (string-append (if directory (basename directory) (basename project))
                              "-" commit "-source"))
    (sha256 (base32 hash))))

(define bionic-source
  (aosp-source "platform/bionic" "09a271af557444c9a6b3f3146d6d474156fd6cdb" #f
               "1sm45k163fincf1gi1f0snhkhm6rnydj98g1ln5ihhvcyy3rq2l5"))
(define logging-source
  (aosp-source "platform/system/logging" "d78b713380007d3c0dde14712cbcbec27f491ad9" #f
               "0jcmnpbf8wvjs3hffwpi1xbq402mszp57vwsqxynqb6mgp0hx9s7"))
(define jni-source
  (aosp-source "platform/libnativehelper" "5c36ece5ac42b20f0e384d9e57400f2f22aad9fb" "include_jni"
               "0y3xb2q3dzqim5a0635ygv05s2c8dakx1v9i597gw6ghhmyim5lj"))
(define crt-source
  (aosp-source "platform/ndk" "805836ef53231ef86dd5fcc5652a1c28d74f4bc4" "sources/crt"
               "1ki5rjc0gywfmr8xgv0290vjri6vcjzjrbb29q1ij725i3945h15"))
(define ndkstubgen-source
  (aosp-source "platform/build/soong" "533c3c2c9166b49caa556518bb547d8f9acf9594" "cc/ndkstubgen"
               "02lixblgkp4a29qlj6m3x5m5hiji7d3g0f084rpv7g98rlsfxk2y"))
(define symbolfile-source
  (aosp-source "platform/build/soong" "533c3c2c9166b49caa556518bb547d8f9acf9594" "cc/symbolfile"
               "0xmay9hzrph31vphs3csfzhzw9v59j5azfvp78jrz8x1azvi3c8q"))

(define %sysroot-builder
  (local-file "../../libexec/build-android-sysroot.py"))

(define %toolchain-assembler
  (local-file "../../libexec/assemble-android-toolchain.py"))

(define %graphics-sysroot-builder
  (local-file "../../libexec/extend-android-sysroot.py"))

(define-public android-aarch64-sysroot
  (package
    (name "android-aarch64-sysroot")
    (version "16.0.0-api28")
    (source bionic-source)
    (build-system gnu-build-system)
    (arguments
     (list
      #:tests? #f ; The build includes a target ELF link probe; cannot run it on the host.
      #:phases
      #~(modify-phases %standard-phases
          (replace 'unpack
            (lambda* (#:key source inputs #:allow-other-keys)
              (for-each
               (lambda (entry)
                 (copy-recursively (cdr entry) (car entry) #:keep-mtime? #t))
               (list (cons "bionic" source)
                     (cons "logging" (assoc-ref inputs "logging-source"))
                     (cons "jni" (assoc-ref inputs "jni-source"))
                     (cons "crt" (assoc-ref inputs "crt-source"))
                     (cons "ndkstubgen" (assoc-ref inputs "ndkstubgen-source"))
                     (cons "symbolfile" (assoc-ref inputs "symbolfile-source"))))))
          (delete 'configure)
          (replace 'build
            (lambda _
              (invoke "python3" #$%sysroot-builder
                      "--bionic" (string-append (getcwd) "/bionic")
                      "--logging" (string-append (getcwd) "/logging")
                      "--jni" (string-append (getcwd) "/jni")
                      "--crt" (string-append (getcwd) "/crt")
                      "--ndkstubgen" (string-append (getcwd) "/ndkstubgen")
                      "--symbolfile" (string-append (getcwd) "/symbolfile")
                      "--cc" #$(file-append android-clang-18 "/bin/clang")
                      "--linker" #$(file-append lld-18 "/bin/ld.lld")
                      "--readelf" #$(file-append llvm-18 "/bin/llvm-readelf")
                      "--output" #$output)))
          (delete 'install)
          ;; Cross objects and stubs must not be processed by host strip.
          (delete 'strip))))
    (native-inputs
     (list (list "clang" android-clang-18)
           (list "lld" lld-18)
           (list "llvm" llvm-18)
           (list "python" python-minimal)
           (list "logging-source" logging-source)
           (list "jni-source" jni-source)
           (list "crt-source" crt-source)
           (list "ndkstubgen-source" ndkstubgen-source)
           (list "symbolfile-source" symbolfile-source)))
    (home-page "https://android.googlesource.com/platform/bionic/")
    (synopsis "Source-built Android arm64 API 28 linking sysroot")
    (description "This package compiles Android API 28 link-time library stubs
and CRT objects, and installs Bionic, JNI and Android logging source headers.
The stub libraries are build inputs and must never be shipped to a device.")
    (license (list license:bsd-2 license:bsd-3 license:asl2.0))))

(define-public android-aarch64-builtins
  (package
    (name "android-aarch64-builtins")
    (version (package-version llvm-18))
    (source (package-source llvm-18))
    (build-system cmake-build-system)
    (arguments
     (list
      #:tests? #f
      #:build-type "Release"
      #:configure-flags
      #~(list
         "-DCMAKE_SYSTEM_NAME=Android"
         ;; LLVM's own runtimes/cmake/android/Common.cmake uses version 1 to
         ;; disable CMake's NDK discovery while bootstrapping the NDK runtime.
         "-DCMAKE_SYSTEM_VERSION=1"
         "-DCMAKE_SYSTEM_PROCESSOR=aarch64"
         "-DCMAKE_C_COMPILER_TARGET=aarch64-linux-android28"
         "-DCMAKE_ASM_COMPILER_TARGET=aarch64-linux-android28"
         "-DCMAKE_TRY_COMPILE_TARGET_TYPE=STATIC_LIBRARY"
         (string-append "-DCMAKE_C_COMPILER=" #$(file-append android-clang-18 "/bin/clang"))
         (string-append "-DCMAKE_ASM_COMPILER=" #$(file-append android-clang-18 "/bin/clang"))
         (string-append "-DCMAKE_AR=" #$(file-append llvm-18 "/bin/llvm-ar"))
         (string-append "-DCMAKE_RANLIB=" #$(file-append llvm-18 "/bin/llvm-ranlib"))
         (string-append "-DCMAKE_SYSROOT=" #$android-aarch64-sysroot)
         (string-append "-DLLVM_CMAKE_DIR=" #$(file-append llvm-18 "/lib/cmake/llvm"))
         "-DCOMPILER_RT_DEFAULT_TARGET_ONLY=ON"
         "-DCOMPILER_RT_INCLUDE_TESTS=OFF"
         "-DCOMPILER_RT_EXCLUDE_ATOMIC_BUILTIN=OFF"
         "-DCOMPILER_RT_BUILTINS_ENABLE_PIC=ON")
      #:phases
      #~(modify-phases %standard-phases
          (add-after 'unpack 'enter-builtins
            (lambda _
              (chdir "compiler-rt/lib/builtins")))
          (add-after 'set-paths 'isolate-target-search-paths
            (lambda _
              (for-each unsetenv
                        '("C_INCLUDE_PATH" "CPLUS_INCLUDE_PATH" "CPATH" "LIBRARY_PATH"))))
          (delete 'strip))))
    (native-inputs (list android-clang-18 llvm-18 python-minimal android-aarch64-sysroot))
    (home-page "https://compiler-rt.llvm.org/")
    (synopsis "LLVM compiler runtime built for Android arm64")
    (description "This package compiles the LLVM compiler-rt builtins for Android
arm64 API 28, including Android emulated TLS and outline atomic helpers.")
    (license license:asl2.0)))

(define-public android-aarch64-cxx-runtime
  (package
    (name "android-aarch64-cxx-runtime")
    (version (package-version llvm-18))
    (source (package-source llvm-18))
    (build-system cmake-build-system)
    (arguments
     (list
      #:tests? #f ; The assembled toolchain links a C++ exception/thread probe.
      #:validate-runpath? #f ; Android loads its system libraries on the device.
      #:build-type "Release"
      #:configure-flags
      #~(let ((flags (string-append
                      "-resource-dir=" #$output "/lib/clang/18"
                      " -fuse-ld=" #$(file-append lld-18 "/bin/ld.lld")
                      " --rtlib=compiler-rt --unwindlib=none"
                      " -Wno-unused-command-line-argument")))
          (list
           "-DCMAKE_SYSTEM_NAME=Android"
           "-DCMAKE_SYSTEM_VERSION=1"
           "-DCMAKE_SYSTEM_PROCESSOR=aarch64"
           "-DCMAKE_POSITION_INDEPENDENT_CODE=ON"
           ;; Guix's native CMake defaults add $out/lib and input directories
           ;; to installed RUNPATHs. Android resolves these libraries itself.
           "-DCMAKE_SKIP_RPATH=ON"
           "-DCMAKE_C_COMPILER_TARGET=aarch64-linux-android28"
           "-DCMAKE_CXX_COMPILER_TARGET=aarch64-linux-android28"
           "-DCMAKE_ASM_COMPILER_TARGET=aarch64-linux-android28"
           ;; Keep real executable link checks here. STATIC_LIBRARY would make
           ;; check_library_exists incorrectly claim Android has libpthread.
           (string-append "-DCMAKE_C_COMPILER=" #$(file-append android-clang-18 "/bin/clang"))
           (string-append "-DCMAKE_CXX_COMPILER=" #$(file-append android-clang-18 "/bin/clang++"))
           (string-append "-DCMAKE_ASM_COMPILER=" #$(file-append android-clang-18 "/bin/clang"))
           (string-append "-DCMAKE_AR=" #$(file-append llvm-18 "/bin/llvm-ar"))
           (string-append "-DCMAKE_RANLIB=" #$(file-append llvm-18 "/bin/llvm-ranlib"))
           (string-append "-DCMAKE_SYSROOT=" #$android-aarch64-sysroot)
           (string-append "-DCMAKE_C_FLAGS=" flags)
           (string-append "-DCMAKE_CXX_FLAGS=" flags " -nostdlib++")
           "-DLLVM_ENABLE_RUNTIMES=libunwind;libcxxabi;libcxx"
           "-DLLVM_INCLUDE_TESTS=OFF"
           "-DLIBCXX_INCLUDE_TESTS=OFF"
           "-DLIBCXX_INCLUDE_BENCHMARKS=OFF"
           "-DLIBCXXABI_INCLUDE_TESTS=OFF"
           "-DLIBUNWIND_INCLUDE_TESTS=OFF"
           "-DLIBCXX_USE_COMPILER_RT=ON"
           "-DLIBCXXABI_USE_COMPILER_RT=ON"
           "-DLIBUNWIND_USE_COMPILER_RT=ON"
           "-DLIBCXX_ENABLE_SHARED=OFF"
           "-DLIBCXXABI_ENABLE_SHARED=OFF"
           "-DLIBUNWIND_ENABLE_SHARED=OFF"
           "-DLIBCXX_ENABLE_STATIC_ABI_LIBRARY=ON"
           "-DLIBCXXABI_USE_LLVM_UNWINDER=ON"
           "-DLIBCXXABI_ENABLE_STATIC_UNWINDER=ON"
           "-DLIBCXX_ABI_NAMESPACE=__ndk1"
           "-DLIBCXX_ENABLE_ABI_LINKER_SCRIPT=OFF"
           "-DANDROID_PLATFORM_LEVEL=28"))
      #:phases
      #~(modify-phases %standard-phases
          (add-after 'set-paths 'isolate-target-search-paths
            (lambda _
              (for-each unsetenv
                        '("C_INCLUDE_PATH" "CPLUS_INCLUDE_PATH" "CPATH" "LIBRARY_PATH"))))
          (add-after 'unpack 'prepare-runtime-bootstrap
            (lambda _
              ;; The standard license phase cannot locate components after
              ;; entering runtimes/ in this monorepo build. These notices also
              ;; accompany the static runtime embedded in the module AAR.
              (for-each
               (lambda (component)
                 (install-file (string-append component "/LICENSE.TXT")
                               (string-append #$output "/share/licenses/android-runtime/" component)))
               '("compiler-rt" "libcxx" "libcxxabi" "libunwind"))
              (let ((resource (string-append #$output "/lib/clang/18")))
                (mkdir-p (string-append resource "/lib/linux"))
                (symlink #$(file-append android-clang-18 "/lib/clang/18/include")
                         (string-append resource "/include"))
                (symlink #$(file-append android-aarch64-builtins
                                       "/lib/linux/libclang_rt.builtins-aarch64-android.a")
                         (string-append resource "/lib/linux/libclang_rt.builtins-aarch64-android.a")))
              (chdir "runtimes")))
          (delete 'strip))))
    (native-inputs (list android-clang-18 lld-18 llvm-18 python-minimal
                         android-aarch64-sysroot android-aarch64-builtins))
    (home-page "https://libcxx.llvm.org/")
    (synopsis "Source-built Android arm64 static C++ runtime")
    (description "This package cross-compiles position-independent libc++,
libc++abi and libunwind for Android arm64 API 28.  Its static libc++ archive
includes the ABI and unwinding objects for use in an embeddable native module.")
    (license license:asl2.0)))

(define-public android-aarch64-toolchain
  (package
    (name "android-aarch64-toolchain")
    (version "18.1.8-api28")
    (source #f)
    (build-system gnu-build-system)
    (arguments
     (list
      #:tests? #f ; The assembler runs a CMake target link/ELF probe.
      #:validate-runpath? #f ; Target ELF dependencies are checked by the probe.
      #:phases
      #~(modify-phases %standard-phases
          (delete 'unpack)
          (delete 'configure)
          (delete 'build)
          (replace 'install
            (lambda _
              (invoke "python3" #$%toolchain-assembler
                      "--output" #$output
                      "--sysroot" #$android-aarch64-sysroot
                      "--runtime" #$android-aarch64-cxx-runtime
                      "--clang" #$android-clang-18
                      "--llvm" #$llvm-18
                      "--linker" #$(file-append lld-18 "/bin/ld.lld")
                      "--shell" #$(file-append bash-minimal "/bin/bash")
                      "--cmake" #$(file-append cmake-minimal "/bin/cmake"))))
          (delete 'strip))))
    (native-inputs (list android-clang-18 llvm-18 lld-18 bash-minimal cmake-minimal python-minimal
                         android-aarch64-sysroot android-aarch64-cxx-runtime))
    (native-search-paths
     (list (search-path-specification
            (variable "ANDROID_NDK")
            (files '("lib/android-toolchain"))
            (separator #f))))
    (home-page "https://bitcoinknots.org/")
    (synopsis "Source-built Android arm64 native module toolchain")
    (description "This toolchain provides source-built LLVM compilers, Bionic
headers and link stubs, CRT objects, compiler-rt, and a static C++ runtime for
Android arm64 API 28.  It exposes an NDK-compatible directory layout for CMake
and depends, with generated compatibility metadata.  It is not a Google NDK
distribution and does not contain Android SDK tools or an Android Java API.")
    (license (list license:expat license:asl2.0 license:bsd-2 license:bsd-3))))

(define %graphics-sources
  (list
   (list "framework-android"
         (aosp-source "platform/frameworks/base" "99b01a65cc4c104933788b3143285ab6bae65827" "native/android"
                      "0502b1w12dxmx9pn7aqr9i5mr4sx9fdfbc34vrg00gjy5hsckakw"))
   (list "framework-graphics"
         (aosp-source "platform/frameworks/base" "99b01a65cc4c104933788b3143285ab6bae65827" "native/graphics"
                      "19l5b6jla8yx78v53ahism3bwxx2zbsjqpdx0lk7ywsr8hnagm64"))
   (list "native-include"
         (aosp-source "platform/frameworks/native" "2827a4a16b0340ecd07c2d5a6c89991799b362bb" "include"
                      "1zi15b5vzyzwhcg0ljphs0yrhklkccb2cld8n6hwhv7fhdfybj2i"))
   (list "native-opengl"
         (aosp-source "platform/frameworks/native" "2827a4a16b0340ecd07c2d5a6c89991799b362bb" "opengl"
                      "1hdpdszp5cxaqj2h0gv07qc8ikhazia6kcc0i43qcszva02q96c5"))
   (list "native-window"
         (aosp-source "platform/frameworks/native" "2827a4a16b0340ecd07c2d5a6c89991799b362bb" "libs/nativewindow"
                      "0r212yzz64vxxhnvkq2pzga8cvq5psz8qzhyk9j8g9q669pfyn63"))
   (list "native-rect"
         (aosp-source "platform/frameworks/native" "2827a4a16b0340ecd07c2d5a6c89991799b362bb" "libs/arect"
                      "118mm7a3879dj6jxgbjy6fiz14nxzzsa0kfg75vr2bbx5sbjz529"))))

(define-public android-aarch64-gui-sysroot
  (package
    (inherit android-aarch64-sysroot)
    (name "android-aarch64-gui-sysroot")
    (source #f)
    (arguments
     (list
      #:tests? #f
      #:phases
      #~(modify-phases %standard-phases
          (replace 'unpack
            (lambda* (#:key inputs #:allow-other-keys)
              (for-each
               (lambda (name)
                 (copy-recursively (assoc-ref inputs name) name #:keep-mtime? #t))
               '("ndkstubgen" "symbolfile" "framework-android" "framework-graphics"
                 "native-include" "native-opengl" "native-window" "native-rect"))))
          (delete 'configure)
          (replace 'build
            (lambda _
              (apply invoke "python3" #$%graphics-sysroot-builder
                     "--base" #$android-aarch64-sysroot "--output" #$output
                     "--cc" #$(file-append android-clang-18 "/bin/clang")
                     "--linker" #$(file-append lld-18 "/bin/ld.lld")
                     (apply append
                      (map (lambda (name) (list (string-append "--" name)
                                              (string-append (getcwd) "/" name)))
                           '("ndkstubgen" "symbolfile" "framework-android" "framework-graphics"
                             "native-include" "native-opengl" "native-window" "native-rect"))))))
          (delete 'install)
          (delete 'strip))))
    (native-inputs
     (append (list (list "clang" android-clang-18)
                   (list "lld" lld-18)
                   (list "python" python-minimal)
                   (list "sysroot" android-aarch64-sysroot)
                   (list "ndkstubgen" ndkstubgen-source)
                   (list "symbolfile" symbolfile-source))
             %graphics-sources))
    (synopsis "Source-built Android arm64 GUI linking sysroot")
    (description "This package extends the native-module sysroot with AOSP
Android, native-window, JNI graphics, EGL and OpenGL ES source headers and API
28 link-time stubs.  It honors AOSP's unversioned legacy graphics interfaces.")
    (license (list license:bsd-2 license:bsd-3 license:asl2.0))))

(define-public android-aarch64-gui-cxx-runtime
  (package
    (inherit android-aarch64-cxx-runtime)
    (name "android-aarch64-gui-cxx-runtime")
    (arguments
     (substitute-keyword-arguments (package-arguments android-aarch64-cxx-runtime)
       ((#:configure-flags flags)
        #~(append #$flags
                  (list "-DLIBCXX_ENABLE_SHARED=ON"
                        "-DLIBCXX_SHARED_OUTPUT_NAME=c++_shared"
                        "-DCMAKE_SHARED_LINKER_FLAGS=-Wl,-z,max-page-size=16384")))
       ((#:phases phases)
        #~(modify-phases #$phases
            (add-before 'prepare-runtime-bootstrap 'android-shared-library-name
              (lambda _
                ;; Android packages use libc++_shared.so, not an ELF .so.1
                ;; symlink chain. The ABI namespace remains __ndk1.
                (substitute* "libcxx/src/CMakeLists.txt"
                  (("      VERSION       .*\n") "")
                  (("      SOVERSION     .*\n") ""))))))))
    (synopsis "Source-built Android arm64 shared and static C++ runtimes")))

(define-public android-aarch64-gui-toolchain
  (package
    (inherit android-aarch64-toolchain)
    (name "android-aarch64-gui-toolchain")
    (arguments
     (substitute-keyword-arguments (package-arguments android-aarch64-toolchain)
       ((#:phases phases)
        #~(modify-phases #$phases
            (replace 'install
              (lambda _
                (invoke "python3" #$%toolchain-assembler "--shared"
                        "--output" #$output
                        "--sysroot" #$android-aarch64-gui-sysroot
                        "--runtime" #$android-aarch64-gui-cxx-runtime
                        "--clang" #$android-clang-18 "--llvm" #$llvm-18
                        "--linker" #$(file-append lld-18 "/bin/ld.lld")
                        "--shell" #$(file-append bash-minimal "/bin/bash")
                        "--cmake" #$(file-append cmake-minimal "/bin/cmake"))))))))
    (native-inputs
     (list android-clang-18 llvm-18 lld-18 bash-minimal cmake-minimal python-minimal
           android-aarch64-gui-sysroot android-aarch64-gui-cxx-runtime))
    (synopsis "Source-built Android arm64 GUI native toolchain")))

