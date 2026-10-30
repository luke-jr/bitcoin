;;; Source-built CMake for the Android Qt host tools.
;;; Copyright (c) 2026 The Bitcoin Knots developers
;;;
;;; This file is free software; you can redistribute it and/or modify it
;;; under the terms of the GNU General Public License as published by
;;; the Free Software Foundation; either version 3 of the License, or (at
;;; your option) any later version.
;;;
;;; This file is distributed in the hope that it will be useful, but
;;; WITHOUT ANY WARRANTY; without even the implied warranty of
;;; MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
;;; GNU General Public License for more details.
;;;
;;; See LICENSE.GPL-3.0-or-later in this directory for the license text.

(define-module (bitcoin android-host-cmake)
  #:use-module ((guix licenses) #:prefix license:)
  #:use-module (guix packages)
  #:use-module (guix download)
  #:use-module (guix gexp)
  #:use-module (guix utils)
  #:use-module (gnu packages cmake)
  #:use-module (ice-9 match)
  #:export (android-host-cmake))

(define android-cmake-version "3.31.12")

(define-public android-host-cmake
  (package
    (inherit cmake-minimal)
    (name "android-host-cmake")
    (version android-cmake-version)
    (source
     (origin
       (inherit (package-source cmake-minimal))
       (uri (string-append "https://cmake.org/files/v3.31/cmake-"
                           version ".tar.gz"))
       (sha256
        (base32 "0wl2zl6gl3fgallwq16ky8cwqwr6ly0zjr7dvcmn0rgs9njxagsz"))
       ;; CMake 3.31 already honors SSL_CERT_FILE and SSL_CERT_DIR upstream.
       (patches '())
       ;; Keep Guix's dependency purge, with the two new source libraries
       ;; required by CMake 3.31.  The pinned Guix has no cppdap package, and
       ;; llpkgc has no system-library option.  All other libraries retain
       ;; the inherited system-library selection and cached source builds.
       (snippet
        (match (origin-snippet (package-source cmake-minimal))
          (('begin ('define 'preserved-files ('quote preserved)) body ...)
           `(begin
              (define preserved-files
                ',(append '("Utilities/cmcppdap" "Utilities/cmllpkgc")
                          preserved))
              ,@body))))))
    (arguments
     (substitute-keyword-arguments (package-arguments cmake-minimal)
       ((#:configure-flags flags)
        #~(append
           (list "-DCMAKE_USE_SYSTEM_LIBRARIES=ON"
                 "-DCMAKE_USE_SYSTEM_LIBRARY_CPPDAP=OFF"
                 (string-append "-DCMAKE_DOC_DIR=share/doc/cmake-"
                                #$(version-major+minor android-cmake-version)))
           ;; The inherited flags contain a hardcoded 3.24 documentation path.
           (filter (lambda (flag)
                     (and (not (string-prefix? "-DCMAKE_DOC_DIR=" flag))
                          (not (string=? "-DCMAKE_USE_SYSTEM_LIBRARIES=ON" flag))))
                   #$flags)))
       ((#:phases phases)
        #~(modify-phases #$phases
            ;; Keep the inherited shell paths and test suite, but update
            ;; the version-specific documentation removal and retain the
            ;; license of the newly bundled Apache-2.0 library.
            (replace 'delete-help-documentation
              (lambda _
                (delete-file-recursively
                 (string-append #$output "/share/cmake-"
                                #$(version-major+minor android-cmake-version)
                                "/Help"))))
            (add-after 'install 'install-cppdap-license
              (lambda _
                (install-file
                 (string-append "../cmake-" #$android-cmake-version
                                "/Utilities/cmcppdap/LICENSE")
                 (string-append #$output "/share/doc/cmake-"
                                #$(version-major+minor android-cmake-version)
                                "/cmcppdap"))))))))
    (license (append (package-license cmake-minimal)
                     (list license:asl2.0)))))
