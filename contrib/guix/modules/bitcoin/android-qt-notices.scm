;;; Copyright (c) 2026 The Bitcoin Knots developers
;;; Distributed under the MIT software license, see the accompanying
;;; file COPYING or https://opensource.org/license/mit/.

(define-module (bitcoin android-qt-notices)
  #:use-module (guix packages)
  #:use-module (guix build-system copy)
  #:use-module ((guix licenses) #:prefix license:)
  #:use-module (bitcoin android-qt)
  #:export (qtbase-android-notices))

(define-public qtbase-android-notices
  (package
    (name "qtbase-android-notices")
    (version (package-version qtbase-android))
    (source (package-source qtbase-android))
    (build-system copy-build-system)
    (arguments
     '(#:install-plan
       '(("src/3rdparty/pcre2/" "share/licenses/qt6/third-party/pcre2"
         #:include ("LICENCE.md" "LICENSE-SLJIT" "qt_attribution.json"))
        ("src/3rdparty/freetype/" "share/licenses/qt6/third-party/freetype"
         #:include ("LICENSE.txt" "BDF-LICENSE.txt" "PCF-LICENSE.txt" "ZLIB-LICENSE.txt"
                    "qt_attribution.json"))
        ("src/3rdparty/harfbuzz-ng/" "share/licenses/qt6/third-party/harfbuzz-ng"
         #:include ("COPYING" "qt_attribution.json"))
        ("src/3rdparty/libjpeg/" "share/licenses/qt6/third-party/libjpeg"
         #:include ("LICENSE" "COPYRIGHT.txt" "qt_attribution.json"))
        ("src/3rdparty/libpng/" "share/licenses/qt6/third-party/libpng"
         #:include ("LICENSE" "qt_attribution.json"))
        ("src/3rdparty/zlib/" "share/licenses/qt6/third-party/zlib"
         #:include ("LICENSE" "qt_attribution.json")))))
    (home-page (package-home-page qtbase-android))
    (synopsis "Original notices for Qt's bundled Android libraries")
    (description
     "This package installs the original license and copyright notices for
the PCRE2, FreeType, HarfBuzz, JPEG, PNG and zlib sources bundled into the
Android Qt build.  Their source attribution records retain the complete author
lists.  These files complement Qt's generic license texts without rebuilding
the Qt libraries or introducing generated build metadata.")
    (license
     (list license:bsd-2 license:bsd-3 license:freetype license:gpl2
           license:expat license:ijg license:zlib
           (license:x11-style
            "https://github.com/harfbuzz/harfbuzz/blob/14.6.0/COPYING"
            "HarfBuzz's Old MIT license.")
           (license:non-copyleft
            "https://github.com/PCRE2Project/pcre2/blob/pcre2-10.49/LICENCE.md"
            "BSD 3-clause license with PCRE2 binary-like packages exception.")
           (license:non-copyleft
            "https://github.com/pnggroup/libpng/blob/v1.6.59/LICENSE"
            "libpng license and PNG Reference Library license version 2.")))))
