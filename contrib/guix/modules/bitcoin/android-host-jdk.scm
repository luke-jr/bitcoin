;;; Source-built Android host Java tools.
;;; The path/currency and archive phases adapt (gnu packages java) from GNU Guix.
;;; Upstream source-file copyright notices are retained below.
;;; Copyright © 2015-2024 Ricardo Wurmus <rekado@elephly.net>
;;; Copyright © 2016 Leo Famulari <leo@famulari.name>
;;; Copyright © 2016, 2017 Roel Janssen <roel@gnu.org>
;;; Copyright © 2017, 2019, 2021 Carlo Zancanaro <carlo@zancanaro.id.au>
;;; Copyright © 2017-2022 Julien Lepiller <julien@lepiller.eu>
;;; Copyright © 2017 Thomas Danckaert <post@thomasdanckaert.be>
;;; Copyright © 2016, 2017, 2018 Alex Vong <alexvong1995@gmail.com>
;;; Copyright © 2017, 2019, 2021 Tobias Geerinckx-Rice <me@tobias.gr>
;;; Copyright © 2018, 2019 Gábor Boskovits <boskovits@gmail.com>
;;; Copyright © 2018 Chris Marusich <cmmarusich@gmail.com>
;;; Copyright © 2018-2024 Efraim Flashner <efraim@flashner.co.il>
;;; Copyright © 2019, 2020, 2021 Björn Höfling <bjoern.hoefling@bjoernhoefling.de>
;;; Copyright © 2020 Jan (janneke) Nieuwenhuizen <janneke@gnu.org>
;;; Copyright © 2020 Raghav Gururajan <raghavgururajan@disroot.org>
;;; Copyright © 2020, 2022 Maxim Cournoyer <maxim.cournoyer@gmail.com>
;;; Copyright © 2021 Vincent Legoll <vincent.legoll@gmail.com>
;;; Copyright © 2021 Mike Gerwitz <mtg@gnu.org>
;;; Copyright © 2021 Pierre Langlois <pierre.langlois@gmx.com>
;;; Copyright © 2021 Guillaume Le Vaillant <glv@posteo.net>
;;; Copyright © 2022 Artyom V. Poptsov <poptsov.artyom@gmail.com>
;;; Copyright © 2024 Paul A. Patience <paul@apatience.com>
;;; Copyright © 2024 Raven Hallsby <karl@hallsby.com>
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

(define-module (bitcoin android-host-jdk)
  #:use-module (guix packages)
  #:use-module (guix gexp)
  #:use-module (guix git-download)
  #:use-module (guix utils)
  #:use-module (gnu packages java)
  #:use-module (gnu packages autotools)
  #:use-module (ice-9 match)
  #:use-module (srfi srfi-1)
  #:export (android-icedtea7 android-icedtea8 android-openjdk17
            android-headless-package))

;; Source-built host compiler/signing tools do not need native desktop support.
;; Legacy Java support APIs remain real classes because logging and Ant use
;; java.beans, whose method signatures include AWT types.
(define %desktop-inputs
  '("alsa-lib" "cups" "fontconfig" "fontconfig-minimal" "freetype" "giflib"
    "gtk+" "lcms"
    "libjpeg" "libjpeg-turbo" "libpng" "libice" "libx11" "libxcomposite" "libxcursor"
    "libxext" "libxi" "libxinerama" "libxrandr" "libxrender" "libxt" "libxtst"))

(define %icedtea7-tools-patch
  (local-file "../../patches/icedtea7-build-tools-only.patch"))
(define %icedtea8-tools-patch
  (local-file "../../patches/icedtea8-build-tools-only.patch"))

(define (without-inputs inputs names)
  (filter (match-lambda
            ((name . _) (not (member name names))))
          inputs))

(define (replace-bootstrap inputs original replacement)
  (map (match-lambda
         ((name package outputs ...)
          (cons* name (if (eq? package original) replacement package) outputs)))
       inputs))

(define (tools-autoconf-inputs inputs)
  (append `(("autoconf" ,autoconf) ("automake" ,automake))
          (without-inputs inputs '("autoconf" "automake"))))

(define (legacy-tools-phases phases patch java8?)
  #~(modify-phases #$phases
      (add-after 'unpack 'select-build-tools
        (lambda _
          (invoke "patch" "--batch" "-p1" "--input" #$patch)))
      (add-before 'configure 'regenerate-tools-configure
        (lambda* (#:key inputs #:allow-other-keys)
          ;; The inherited IcedTea7 phase fixes an obsolete header name in the
          ;; generated configure. Preserve that fix when regenerating from m4.
          (substitute* "acinclude.m4"
            (("attr/xattr.h") "sys/xattr.h"))
          #$@(if java8?
                 '()
                 '((substitute* "Makefile.am"
                     (("\\$\\(SYSTEM_JDK_DIR\\)/jre/lib/rt.jar")
                      (search-input-file inputs "/lib/rt.jar")))))
          ;; Preserve the pinned recipe's distribution identity after Automake
          ;; regenerates Makefile.in from Makefile.am.
          (substitute* "Makefile.am"
            (("DISTRIBUTION_ID=\"\\$\\(DIST_ID\\)\"")
             "DISTRIBUTION_ID=\"\\\"guix\\\"\""))
          (invoke "autoreconf" "-fi")
          #$@(if java8?
                 '((with-directory-excursion "openjdk.src"
                     (invoke "bash" "common/autoconf/autogen.sh")))
                 '())
          (setenv "BUILD_HEADLESS_ONLY" "true")))
      (add-after 'install 'check-build-tools
        (lambda* (#:key outputs #:allow-other-keys)
          (let* ((jdk (assoc-ref outputs "jdk"))
                 (bin (string-append jdk "/bin/")))
            (for-each
             (lambda (file)
               (when (any (lambda (name) (string-contains file name))
                          '("libawt" "libfontmanager" "libjsound" "libjawt" "libsplashscreen" "libsaproc"))
                 (error "desktop native library in tools-only bootstrap" file)))
             (find-files jdk "\\.so$"))
            (for-each
             (lambda (name)
               (when (file-exists? (string-append jdk name))
                 (error "GUI/debugger tool in tools-only bootstrap" name)))
             '("/bin/jconsole" "/bin/policytool" "/bin/jsadebugd" "/lib/sa-jdi.jar"))
            (mkdir "tools-only-smoke")
            (with-directory-excursion "tools-only-smoke"
              (call-with-output-file "ToolsOnlySmoke.java"
                (lambda (port)
                  (display "import java.beans.Introspector;
import java.security.MessageDigest;
import java.security.Signature;
import java.util.logging.Logger;
public class ToolsOnlySmoke {
  public String getName() { return \"tools\"; }
  public static void main(String[] args) throws Exception {
    if (Introspector.getBeanInfo(ToolsOnlySmoke.class).getPropertyDescriptors().length == 0)
      throw new AssertionError(\"java.beans support is missing\");
    MessageDigest.getInstance(\"SHA-256\").digest(new byte[0]);
    Signature.getInstance(\"SHA256withRSA\");
    Logger.getLogger(\"tools-only\").info(\"bootstrap APIs available\");
  }
}
" port)))
              (invoke (string-append bin "javac") "ToolsOnlySmoke.java")
              (invoke (string-append bin "jar") "cf" "smoke.jar" "ToolsOnlySmoke.class")
              (invoke (string-append bin "java") "-Xmx128m" "-cp" "smoke.jar" "ToolsOnlySmoke")
              (invoke (string-append bin "keytool") "-help")
              (invoke (string-append bin "jarsigner") "-help")))))
      (replace 'install
        (lambda* (#:key outputs #:allow-other-keys)
          (let ((image-root #$(if java8? "openjdk.build/images/" "openjdk.build/")))
            (copy-recursively (string-append image-root "j2re-image")
                              (assoc-ref outputs "out"))
            (copy-recursively (string-append image-root "j2sdk-image")
                              (assoc-ref outputs "jdk"))
            (mkdir-p (string-append (assoc-ref outputs "doc") "/share/doc/icedtea"))
            #$@(if java8?
                   '((copy-file
                      (string-append (assoc-ref outputs "jdk") "/jre/lib/security/nss.cfg")
                      (string-append (assoc-ref outputs "out") "/lib/security/nss.cfg")))
                   '()))))))

(define android-icedtea7
  (package
    (inherit icedtea-7)
    (inputs (without-inputs (package-inputs icedtea-7) %desktop-inputs))
    (native-inputs (tools-autoconf-inputs (package-native-inputs icedtea-7)))
    (arguments
     (substitute-keyword-arguments (package-arguments icedtea-7)
       ((#:modules modules)
        (cons '(srfi srfi-1) modules))
       ((#:configure-flags flags)
        `(append (delete "--enable-system-lcms" ,flags)
                 '("--enable-build-tools-only" "--disable-docs" "--disable-native-debuginfo")))
       ((#:make-flags flags ''())
        `(append '("BUILD_HEADLESS_ONLY=true" "FULL_DEBUG_SYMBOLS=0") ,flags))
       ((#:phases phases)
        (legacy-tools-phases
         #~(modify-phases #$phases
             (delete 'fix-x11-extension-include-path)
             (replace 'set-additional-paths
               (lambda _
                 (setenv "CC" "gcc")
                 (setenv "ALT_OBJCOPY" (which "objcopy"))))
             (replace 'patch-paths
               (lambda* (#:key inputs #:allow-other-keys)
                 ;; Keep the pinned recipe's tool and currency fixes; its
                 ;; desktop-only ALSA header substitution is unnecessary.
                 (substitute* "openjdk.src/hotspot/make/linux/makefiles/buildtree.make"
                   (("/bin/sh") (which "bash")))
                 (let ((files '("openjdk.src/jdk/make/common/shared/Defs-linux.gmk"
                                "openjdk.src/corba/make/common/shared/Defs-linux.gmk"))
                       (corebin (string-append (assoc-ref inputs "coreutils") "/bin/")))
                   (substitute* files
                     (("UNIXCOMMAND_PATH  = /bin/") (string-append "UNIXCOMMAND_PATH = " corebin))
                     (("USRBIN_PATH  = /usr/bin/") (string-append "USRBIN_PATH = " corebin))
                     (("DEVTOOLS_PATH *= */usr/bin/") (string-append "DEVTOOLS_PATH = " corebin))
                     (("COMPILER_PATH *= */usr/bin/")
                      (string-append "COMPILER_PATH = " (assoc-ref inputs "gcc") "/bin/"))
                     (("DEF_OBJCOPY *=.*objcopy") (string-append "DEF_OBJCOPY = " (which "objcopy")))))
                 (for-each
                  (match-lambda
                    ((variable pattern executable)
                     (substitute* '("openjdk.src/jdk/make/common/shared/Defs-utils.gmk"
                                    "openjdk.src/corba/make/common/shared/Defs-utils.gmk")
                       ((pattern) (string-append variable " = " (which executable))))))
                  '(("ECHO" "ECHO *=.*echo" "echo") ("GREP" "^GREP *=.*grep" "grep")
                    ("EGREP" "EGREP *=.*egrep" "egrep") ("CPIO" "CPIO *=.*cpio" "cpio")
                    ("READELF" "READELF *=.*readelf" "readelf") ("AR" "^ *AR *=.*ar" "ar")
                    ("TAR" "^ *TAR *=.*tar" "tar") ("AS" "AS *=.*as" "as")
                    ("LD" "LD *=.*ld" "ld") ("STRIP" "STRIP *=.*strip" "strip")
                    ("NM" "NM *=.*nm" "nm") ("SH" "^SH *=.*sh" "bash")
                    ("FIND" "FIND *=.*find" "find") ("LDD" "LDD *=.*ldd" "ldd")
                    ("NAWK" "NAWK *=.*(n|g)awk" "gawk") ("XARGS" "XARGS *=.*xargs" "xargs")
                    ("UNZIP" "UNZIP *=.*unzip" "unzip") ("ZIPEXE" "ZIPEXE *=.*zip" "zip")
                    ("SED" "SED *=.*sed" "sed")))
                 (substitute* "openjdk.src/jdk/src/share/classes/java/util/CurrencyData.properties"
                   (("AZ=AZM;2005-12-31-20-00-00;AZN") "AZ=AZN")
                   (("MZ=MZM;2006-06-30-22-00-00;MZN") "MZ=MZN")
                   (("RO=ROL;2006-06-30-21-00-00;RON") "RO=RON")
                   (("TR=TRL;2004-12-31-22-00-00;TRY") "TR=TRY")))))
         %icedtea7-tools-patch #f))))))

(define android-icedtea8
  (package
    (inherit icedtea-8)
    (inputs (without-inputs (package-inputs icedtea-8) %desktop-inputs))
    (native-inputs
     (tools-autoconf-inputs
      (replace-bootstrap (package-native-inputs icedtea-8)
                         icedtea-7 android-icedtea7)))
    (arguments
     (substitute-keyword-arguments (package-arguments icedtea-8)
       ((#:modules modules)
        (cons '(srfi srfi-1) modules))
       ((#:configure-flags flags)
        `(append ,flags '("--enable-headless" "--enable-build-tools-only" "--disable-docs" "--disable-native-debuginfo")))
       ((#:phases phases)
        (legacy-tools-phases phases %icedtea8-tools-patch #t))
       ((#:disallowed-references _ '())
        (list (gexp-input android-icedtea7 "jdk")))))))

(define (openjdk-tools-patch version)
  (cond
   ((string-prefix? "9." version)
    (local-file "../../patches/openjdk9-build-tools-only.patch"))
   ((string-prefix? "10." version)
    (local-file "../../patches/openjdk10-build-tools-only.patch"))
   ((string-prefix? "11." version)
    (local-file "../../patches/openjdk11-build-tools-only.patch"))
   ((string-prefix? "13." version)
    (local-file "../../patches/openjdk13-build-tools-only.patch"))
   ((or (string-prefix? "12." version) (string-prefix? "14." version))
    (local-file "../../patches/openjdk14-build-tools-only.patch"))
   (else (local-file "../../patches/openjdk15-build-tools-only.patch"))))

(define (tools-openjdk base bootstrap-original bootstrap-tools)
  (let ((legacy? (member (package-version base) '("9.181" "10.46"))))
    (package
      (inherit base)
      (source (portable-bootstrap-source base))
      (inputs (without-inputs (package-inputs base) %desktop-inputs))
      (native-inputs
       (tools-autoconf-inputs
        (replace-bootstrap (package-native-inputs base)
                           bootstrap-original bootstrap-tools)))
      (arguments
       (substitute-keyword-arguments (package-arguments base)
         ((#:disallowed-references _ '())
          (list (gexp-input bootstrap-tools)
                (gexp-input bootstrap-tools "jdk")))
         ((#:modules modules)
          (cons '(srfi srfi-1) modules))
         ((#:make-flags flags #~'())
          ;; JDK9/10's recipe passes "all" as a make flag. Keep options and
          ;; assignments, but let our explicit image target bound compilation.
          #~(filter (lambda (flag)
                      (not (member flag '("all" "all-images" "images"
                                           "product-images" "jdk-image"
                                           "legacy-jre-image" "docs"
                                           "docs-image" "test-image"))))
                    #$flags))
         ((#:configure-flags _ #~'())
          ;; Reconstruct the pinned recipe's non-desktop options. Filtering its
          ;; original gexp at build time would retain hidden freetype inputs.
          #~'("--with-extra-cflags=-fcommon -fno-delete-null-pointer-checks -fno-lifetime-dse"
              "--disable-option-checking"
              "--disable-warnings-as-errors"
              #$@(cond
                  (legacy? '())
                  ((member (car (string-split (package-version base) #\.))
                           '("11" "12" "13" "14"))
                   '("--disable-hotspot-gtest"))
                  (else '("--without-gtest")))
              "--with-native-debug-symbols=none"
              "--with-version-pre="
              "--enable-headless-only"
              "--enable-build-tools-only"))
         ((#:phases phases)
          #~(modify-phases #$phases
              (add-after 'unpack 'select-build-tools
                (lambda _
                  (invoke "patch" "--batch" "-p1" "--input"
                          #$(openjdk-tools-patch (package-version base)))))
              (add-before 'configure 'regenerate-tools-configure
                (lambda _
                  (setenv "AUTOCONF" (which "autoconf"))
                  (let ((autogen (find (lambda (file) (file-exists? file))
                                       '("common/autoconf/autogen.sh"
                                         "make/autoconf/autogen.sh"))))
                    (when autogen
                      ;; Older generators record a wall-clock timestamp. Keep
                      ;; their generated configure metadata reproducible too.
                      (substitute* autogen
                        (("^if test \"x\\$CUSTOM_CONFIG_DIR\"" line)
                         (string-append "TIMESTAMP=${SOURCE_DATE_EPOCH:-0}\n" line)))
                      (invoke "bash" autogen)))
                  #$@(if (string=? (package-version base) "10.46")
                         '((substitute* "make/autoconf/generated-configure.sh"
                             (("-Werror") "")))
                         '())))
              #$@(if legacy?
                     #~((replace 'configure
                          (lambda* (#:key inputs outputs #:allow-other-keys)
                            (invoke "bash" "./configure"
                                    "--with-extra-cflags=-fcommon -fno-delete-null-pointer-checks -fno-lifetime-dse"
                                    "--disable-warnings-as-errors"
                                    "--disable-hotspot-gtest"
                                    "--with-native-debug-symbols=none"
                                    "--enable-headless-only"
                                    "--enable-build-tools-only"
                                    (string-append "--prefix=" (assoc-ref outputs "out"))))))
                     #~())
              (replace 'build
                (lambda* (#:key parallel-build? make-flags #:allow-other-keys)
                  ;; 'all' also builds documentation/test images; older
                  ;; product-images adds a second runtime. Build one tool image.
                  (apply invoke "make" "jdk-image"
                         (append
                          (if parallel-build?
                              (list (string-append "JOBS="
                                                   (number->string (parallel-job-count))))
                              '())
                          make-flags))))
              (delete 'build-jre)
              (replace 'install
                (lambda* (#:key outputs #:allow-other-keys)
                  (let ((images (car (find-files "build" ".*-server-release"
                                                 #:directories? #t))))
                    (copy-recursively (string-append images "/images/jdk")
                                      (assoc-ref outputs "jdk"))
                    ;; Both package outputs retain their existing tool paths
                    ;; without duplicating the compiled module/runtime image.
                    (symlink (assoc-ref outputs "jdk") (assoc-ref outputs "out"))
                    (mkdir-p (assoc-ref outputs "doc")))))
              (replace 'install-libjvm
                (lambda* (#:key outputs #:allow-other-keys)
                  (let ((lib (string-append (assoc-ref outputs "jdk") "/lib")))
                    ;; out and jdk now name the same image; create this alias once.
                    (symlink (string-append lib "/server/libjvm.so")
                             (string-append lib "/libjvm.so")))))
              #$@(if legacy?
                     #~()
                     #~((replace 'strip-archive-timestamps
                          (lambda* (#:key outputs #:allow-other-keys)
                            (use-modules (ice-9 binary-ports)
                                         (ice-9 rdelim)
                                         (rnrs bytevectors))
                            ;; ModuleHashes covers resource names as well as
                            ;; content. Enumerating extracted directories adds
                            ;; resources and invalidates java.base's hashes.
                            (define (archive-entries archive)
                              (let ((port (open-pipe* OPEN_READ "unzip" "-Z1" archive)))
                                (let loop ((entries '()))
                                  (let ((entry (read-line port)))
                                    (if (eof-object? entry)
                                        (begin
                                          (unless (zero? (close-pipe port))
                                            (error "cannot list Java archive entries" archive))
                                          (reverse entries))
                                        (loop (cons entry entries)))))))
                            (define (repack-archive archive)
                              (let ((entries (archive-entries archive))
                                    (dir (mkdtemp "zip-contents.XXXXXX")))
                                (with-directory-excursion dir
                                  (invoke "unzip" archive))
                                (delete-file archive)
                                (for-each (compose repack-archive canonicalize-path)
                                          (find-files dir "(ct\\.sym|\\.jar)$"))
                                (for-each
                                 (lambda (file)
                                   (unless (eq? (stat:type (lstat file)) 'symlink)
                                     (utime file 0 0 0 0)))
                                 (find-files dir #:directories? #t))
                                (with-directory-excursion dir
                                  (apply invoke "zip" "-0" "-X" "-y" archive entries))
                                (delete-file-recursively dir)))
                            (define (repack-jmod archive)
                              (let* ((header #vu8(#x4a #x4d #x01 #x00))
                                     (temp (mkstemp! (string-copy "jmod-contents.XXXXXX")))
                                     (temp-name (canonicalize-path (port-filename temp))))
                                (call-with-input-file archive
                                  (lambda (file)
                                    (unless (equal? (get-bytevector-n file (bytevector-length header)) header)
                                      (error "unexpected JMOD header" archive))
                                    (sendfile temp file
                                              (- (stat:size (stat file)) (bytevector-length header))
                                              (bytevector-length header))))
                                (close-port temp)
                                (repack-archive temp-name)
                                (delete-file archive)
                                (call-with-output-file archive
                                  (lambda (file)
                                    (put-bytevector file header)
                                    (call-with-input-file temp-name
                                      (lambda (contents)
                                        (sendfile file contents (stat:size (stat contents)) 0)))))
                                (delete-file temp-name)))
                            (let ((jdk (assoc-ref outputs "jdk"))
                                  (doc (assoc-ref outputs "doc")))
                              (for-each repack-archive (find-files doc "\\.zip$"))
                              (for-each repack-archive (find-files jdk "\\.(zip|jar)$"))
                              (repack-archive (string-append jdk "/lib/ct.sym"))
                              (for-each repack-jmod (find-files jdk "\\.jmod$")))))
                        (add-after 'strip-archive-timestamps 'check-linked-build-tools
                          (lambda* (#:key outputs #:allow-other-keys)
                            ;; Exercise recorded module hashes after normalization.
                            (let* ((jdk (assoc-ref outputs "jdk"))
                                   (linked "tools-only-linked-smoke"))
                              (invoke (string-append jdk "/bin/jlink")
                                      "--module-path" (string-append jdk "/jmods")
                                      "--add-modules" "ALL-MODULE-PATH"
                                      "--output" linked)
                              (invoke (string-append linked "/bin/java") "--list-modules")
                              (invoke (string-append linked "/bin/javac") "-version")
                              (delete-file-recursively linked))))
                        (replace 'remove-extraneous-files
                          (lambda* (#:key outputs #:allow-other-keys)
                            ;; The original phase loops over out and jdk. Their
                            ;; paths overlap now, so normalize the one image once.
                            (for-each delete-file
                                      (find-files (assoc-ref outputs "jdk")
                                                  "(^src\\.zip|\\.diz)$"))))))
              (add-after 'install 'check-build-tools
                (lambda* (#:key outputs #:allow-other-keys)
                  (use-modules (ice-9 textual-ports))
                  (let* ((bin (string-append (assoc-ref outputs "jdk") "/bin/"))
                         (pipe (open-pipe* OPEN_READ (string-append bin "java") "--list-modules"))
                         (modules (get-string-all pipe)))
                    (unless (zero? (close-pipe pipe))
                      (error "cannot list source-built Java tool modules"))
                    (when (string-contains modules "java.desktop")
                      (error "desktop module in tools-only bootstrap"))
                    (for-each
                     (lambda (module)
                       (unless (string-contains modules module)
                         (error "missing Java tool/bootstrap module" module)))
                     '("java.base" "java.compiler" "java.logging" "java.xml"
                       "jdk.compiler" "jdk.crypto.ec" "jdk.internal.opt"
                       "jdk.jartool" "jdk.javadoc" "jdk.jdeps" "jdk.jlink"
                       "jdk.unsupported" "jdk.zipfs"))
                    (invoke (string-append bin "javac") "-version")
                    (invoke (string-append bin "keytool") "-help")
                    (invoke (string-append bin "jarsigner") "-help"))))
              (delete 'remove-timestamp-from-api-summary))))))))

(define (portable-bootstrap-source base)
  (let ((source (package-source base)))
    (cond
     ((member (package-version base) '("9.181" "10.46"))
      ;; The official Git and retired Mercurial transports produce identical
      ;; recursive source hashes for these immutable upstream revisions.
      (origin
        (inherit source)
        (method git-fetch)
        (uri (git-reference
              (url "https://github.com/openjdk/jdk.git")
              (commit (if (string=? (package-version base) "9.181")
                          "801281100cbbec62d41c643ee4d79537a8e8992c"
                          "7a145c6805ba8c81680294e87e801bdef56c9954"))))))
     ((string=? (package-version base) "12.33")
      ;; These are source archives, verified against the original flat hash;
      ;; their content-addressed mirrors avoid the retired Mercurial server.
      (origin
        (inherit source)
        (uri (append
              (map (lambda (host)
                     (string-append "https://" host
                      "/file/openjdk-12.33.tar.bz2/sha256/"
                      "0pi2gwib3j2imi4l623iaywrmvfh9rqzh82lj2gxqbrmg55swvjf"))
                   '("ci.guix.gnu.org" "bordeaux.guix.gnu.org"))
              (list (origin-uri source))))))
     (else source))))

(define android-openjdk9
  (tools-openjdk openjdk9 icedtea-8 android-icedtea8))
(define android-openjdk10
  (tools-openjdk openjdk10 openjdk9 android-openjdk9))
(define android-openjdk11
  (tools-openjdk openjdk11 openjdk10 android-openjdk10))
(define android-openjdk12
  (tools-openjdk openjdk12 openjdk11 android-openjdk11))
(define android-openjdk13
  (tools-openjdk openjdk13 openjdk12 android-openjdk12))
(define android-openjdk14
  (tools-openjdk openjdk14 openjdk13 android-openjdk13))
(define android-openjdk15
  (tools-openjdk openjdk15 openjdk14 android-openjdk14))
(define android-openjdk16
  (tools-openjdk openjdk16 openjdk15 android-openjdk15))
(define android-openjdk17
  (tools-openjdk openjdk17 openjdk16 android-openjdk16))

;; Also rewrite implicit ant-build-system JDK inputs and explicit Java library
;; inputs. Each replacement already has its own bootstrap chain rewritten:
;; package-input-rewriting intentionally stops recursion at a replacement.
(define android-headless-package
  (package-input-rewriting
   (list (cons icedtea-7 android-icedtea7)
         (cons icedtea-8 android-icedtea8)
         (cons openjdk9 android-openjdk9)
         (cons openjdk10 android-openjdk10)
         (cons openjdk11 android-openjdk11)
         (cons openjdk12 android-openjdk12)
         (cons openjdk13 android-openjdk13)
         (cons openjdk14 android-openjdk14)
         (cons openjdk15 android-openjdk15)
         (cons openjdk16 android-openjdk16)
         (cons openjdk17 android-openjdk17))))
