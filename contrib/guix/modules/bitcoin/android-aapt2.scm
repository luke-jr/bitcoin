;; Copyright (c) 2026 The Bitcoin Knots developers
;; Distributed under the MIT software license, see the accompanying file COPYING.

(define-module (bitcoin android-aapt2)
  #:use-module (gnu packages check)
  #:use-module (gnu packages compression)
  #:use-module (gnu packages image)
  #:use-module (gnu packages llvm)
  #:use-module (gnu packages pretty-print)
  #:use-module (gnu packages protobuf)
  #:use-module (gnu packages xml)
  #:use-module (guix build-system cmake)
  #:use-module (bitcoin gitiles)
  #:use-module (guix gexp)
  #:use-module ((guix licenses) #:prefix license:)
  #:use-module (guix packages))

;; Fetch pinned AOSP source trees via Gitiles, hashing extracted content rather
;; than request timestamps in archive headers. Subtree archives avoid fetching the
;; enormous Android OS checkout and unused framework runtime resources. Only
;; listed C/C++ sources are built; upstream binary test data is never a tool.
(define (aosp-source name repository commit subtree hash)
  (origin
    (method gitiles-fetch)
    (uri (string-append "https://android.googlesource.com/platform/"
                        repository "/+archive/" commit subtree ".tar.gz"))
    (file-name (string-append "android-" name "-" commit "-source"))
    (sha256 (base32 hash))))

(define frameworks-base-commit "299fe6f5d6fc6f1af7c3411dcf4e5efdf7217368")

(define aapt2-source
  (aosp-source "aapt2" "frameworks/base" frameworks-base-commit "/tools/aapt2"
               "067grv1nzrxj6hksfvk6hfdxs9qkbzrb5kaiz42vlnqyvvi5xyz0"))

(define extra-sources
  (list
   (list "androidfw-source"
         (aosp-source "androidfw" "frameworks/base" frameworks-base-commit "/libs/androidfw"
                      "12z4113glp7sbzx5mhdrkmpkrcnkysfxgb2j7r65gisi7wswjjx4"))
   (list "idmap-policies-source"
         (aosp-source "idmap-policies" "frameworks/base" frameworks-base-commit
                      "/cmds/idmap2/libidmap2_policies"
                      "1vj4qwfjf7scxf5z2vc2246g6mrd2km6im7p5v25az7d73w110sm"))
   (list "frameworks-native-source"
         (aosp-source "frameworks-native" "frameworks/native"
                      "bfcf75076e562945bae131a4929f29a90d0d2481" ""
                      "03cw8ddmhdnjq4v29ik7133nw49k1gk3sk171f3fn95m965rx8jf"))
   (list "system-core-source"
         (aosp-source "system-core" "system/core"
                      "b8e07c25c4190f4338a6ce0394497925128d2609" ""
                      "00206g1am8n4xcaw7i6vrybpwibm4bq5f6b4y707lcygn1yr0la2"))
   (list "libbase-source"
         (aosp-source "libbase" "system/libbase"
                      "b082e1445ae49943bdff3f0799ed00f7bee61325" ""
                      "0fqm8wx1r48jz6d83vipjhk2nfh8nswd4bj98dx3zy4gixx97l4x"))
   (list "libziparchive-source"
         (aosp-source "libziparchive" "system/libziparchive"
                      "f3ee062b6f56f0bfb1add915a17f245376bd7155" ""
                      "0470x0nnisbilh27m0qmr3h6m9647gbpwsa8x94i9y82wjj10q2v"))
   (list "logging-source"
         (aosp-source "logging" "system/logging"
                      "0d18f57987b1dbf3494ca7d2b13645eac002d3cd" ""
                      "0w09r22d7xmmp2amws81kx2ha6rlyhn0hn9zn577hky09fv06px9"))
   (list "incremental-delivery-source"
         (aosp-source "incremental-delivery" "system/incremental_delivery"
                      "bc06633bbd1f011682a65b153ff4323a1b4c31df" ""
                      "1cyn76v6dg86gz50b2h3jgbdkk815bswb228jja44icalzq8jhwq"))))

(define cmake-source
  (local-file "../../libexec/android-aapt2.CMakeLists.txt"))

(define host-patch
  (local-file "../../patches/android-aapt2-host.patch"))

(define-public android-aapt2
  (package
    (name "android-aapt2")
    (version "14.0.0-r1")
    (source aapt2-source)
    (build-system cmake-build-system)
    (arguments
     (list
      #:modules '((guix build cmake-build-system)
                  (guix build utils)
                  (rnrs io ports))
      #:configure-flags
      #~(list
         (string-append "-DCMAKE_C_COMPILER="
                        #$(file-append clang-toolchain-18 "/bin/clang"))
         (string-append "-DCMAKE_CXX_COMPILER="
                        #$(file-append clang-toolchain-18 "/bin/clang++"))
         (string-append "-DGTEST_INCLUDE_DIR="
                        #$(file-append googletest "/include")))
      #:phases
      #~(modify-phases %standard-phases
          (replace 'unpack
            (lambda* (#:key source inputs #:allow-other-keys)
              (define (copy-source tree directory)
                (copy-recursively tree directory #:keep-mtime? #t)
                (for-each make-file-writable
                          (find-files directory
                                      (lambda (_ stat)
                                        (eq? (stat:type stat) 'regular)))))
              (mkdir "source")
              (chdir "source")
              (copy-source source "frameworks/base/tools/aapt2")
              (for-each
               (lambda (entry)
                 (copy-source (assoc-ref inputs (car entry)) (cadr entry)))
               '(("androidfw-source" "frameworks/base/libs/androidfw")
                 ("idmap-policies-source" "frameworks/base/cmds/idmap2/libidmap2_policies")
                 ("frameworks-native-source" "frameworks/native")
                 ("system-core-source" "system/core")
                 ("libbase-source" "system/libbase")
                 ("libziparchive-source" "system/libziparchive")
                 ("logging-source" "system/logging")
                 ("incremental-delivery-source" "system/incremental_delivery")))
              (copy-file #$cmake-source "CMakeLists.txt")
              (invoke "patch" "-p1" "--input" #$host-patch)))
          (replace 'check
            (lambda* (#:key tests? #:allow-other-keys)
              (when tests?
                (invoke "./aapt2" "version")
                (mkdir-p "smoke/res/values")
                (mkdir-p "smoke/res/drawable")
                (call-with-output-file "smoke/res/values/strings.xml"
                  (lambda (port)
                    (display "<resources><string name=\"app_name\">Source build fixture</string></resources>\n" port)))
                (call-with-output-file "smoke/res/drawable/pixel.png"
                  (lambda (port)
                    (put-bytevector port
                                    #vu8(137 80 78 71 13 10 26 10 0 0 0 13 73 72 68 82
                                         0 0 0 1 0 0 0 1 8 6 0 0 0 31 21 196 137
                                         0 0 0 13 73 68 65 84 120 156 99 248 207 192
                                         240 31 0 5 0 1 255 137 153 61 29 0 0 0 0
                                         73 69 78 68 174 66 96 130))))
                (call-with-output-file "smoke/AndroidManifest.xml"
                  (lambda (port)
                    (display "<manifest package=\"org.bitcoinknots.fixture\"><application/></manifest>\n" port)))
                ;; This fixture intentionally imports no framework resources;
                ;; the separately source-built SDK supplies Android attributes.
                (invoke "./aapt2" "compile" "--dir" "smoke/res"
                        "-o" "smoke/compiled.zip")
                (invoke "./aapt2" "link" "--manifest" "smoke/AndroidManifest.xml"
                        "-o" "smoke/fixture.apk" "smoke/compiled.zip")
                (invoke "./aapt2" "dump" "resources" "smoke/fixture.apk")))))))
    (native-inputs
     (append (list (list "clang-toolchain" clang-toolchain-18)
                   (list "protobuf" protobuf)
                   (list "googletest" googletest))
             extra-sources))
    (inputs (list expat fmt-9 libpng protobuf zlib))
    (home-page "https://android.googlesource.com/platform/frameworks/base/")
    (synopsis "Android resource compiler built from pinned AOSP source")
    (description
     "AAPT2 compiles and links Android resources, including binary and protobuf
resource tables.  This package builds the Linux host tool and its Android utility
libraries from source with Clang, Protobuf, libpng, Expat, fmt and zlib.  It does
not invoke Soong or download Android SDK binaries.  Android framework resource
IDs and attribute formats are supplied separately by the source-built platform.")
    (license license:asl2.0)))
