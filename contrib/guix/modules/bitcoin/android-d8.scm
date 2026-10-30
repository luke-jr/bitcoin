;; Copyright (c) 2026 The Bitcoin Knots developers
;; Distributed under the MIT software license, see the accompanying file COPYING.

(define-module (bitcoin android-d8)
  #:use-module (gnu packages bash)
  #:use-module (gnu packages java)
  #:use-module (bitcoin android-host-jdk)
  #:use-module (guix build-system gnu)
  #:use-module (guix download)
  #:use-module (guix gexp)
  #:use-module (guix git-download)
  #:use-module ((guix licenses) #:prefix license:)
  #:use-module (guix packages))

;; Keep the Java libraries' implicit Ant/bootstrap JDKs headless too.  Use the
;; same packages in the generated launcher, whose classpath is a direct gexp.
(define java-asm-for-d8 (android-headless-package java-asm))
(define java-guava-for-d8 (android-headless-package java-guava))
(define java-failureaccess-for-d8
  (android-headless-package java-guava-futures-failureaccess))
(define java-jopt-simple-for-d8 (android-headless-package java-jopt-simple-4))

;; These are archives of Java SOURCE, not binary Maven libraries. Compiling the
;; published source directly avoids Ivy/Maven downloads and generator toolchains.
(define (source-java-library name version uri hash jar-name smoke-source)
  (package
    (name name)
    (version version)
    (source (origin
              (method url-fetch)
              (uri uri)
              (file-name (string-append name "-" version "-sources.jar"))
              (sha256 (base32 hash))))
    (build-system gnu-build-system)
    (arguments
     (list
      #:modules '((guix build gnu-build-system)
                  (guix build utils)
                  (srfi srfi-1)
                  (srfi srfi-13))
      #:phases
      #~(modify-phases %standard-phases
          (replace 'unpack
            (lambda* (#:key source #:allow-other-keys)
              (mkdir "source")
              (chdir "source")
              (invoke "jar" "--extract" "--file" source)))
          (delete 'configure)
          (replace 'build
            (lambda _
              (unless (null? (find-files "." "\\.class$"))
                (error "Unexpected binary classes in Java source archive"))
              (mkdir "classes")
              (apply invoke "javac" "-J-Xmx2G" "--release" "8"
                     "-encoding" "UTF-8" "-d" "classes"
                     (sort (filter (lambda (file)
                                     (not (string-suffix? "Test.java" file)))
                                   (find-files "." "\\.java$"))
                           string<?))
              (with-directory-excursion "classes"
                (apply invoke "jar" "--create" "--file" "../library.jar"
                       "--no-compress" "--date=1980-01-01T00:00:02Z"
                       (sort (find-files "." "\\.class$") string<?)))))
          (replace 'check
            (lambda* (#:key tests? #:allow-other-keys)
              (when tests?
                (call-with-output-file "Smoke.java"
                  (lambda (port) (display #$smoke-source port)))
                (mkdir "smoke")
                (invoke "javac" "--release" "8" "-classpath" "library.jar"
                        "-d" "smoke" "Smoke.java")
                (invoke "java" "-classpath" "smoke:library.jar" "Smoke"))))
          (replace 'install
            (lambda* (#:key outputs #:allow-other-keys)
              (let ((directory (string-append (assoc-ref outputs "out")
                                              "/share/java")))
                (mkdir-p directory)
                (copy-file "library.jar" (string-append directory "/" #$jar-name))))))))
    (native-inputs (list (list android-openjdk17 "jdk")))
    (home-page uri)
    (synopsis "Java library compiled from its published source archive")
    (description
     "This library is compiled directly from its published Java source.  It is
used by the Android D8 source build without precompiled Maven artifacts.")
    (license license:asl2.0)))

(define java-fastutil-for-d8
  (source-java-library
   "java-fastutil" "7.2.0"
   "https://repo.maven.apache.org/maven2/it/unimi/dsi/fastutil/7.2.0/fastutil-7.2.0-sources.jar"
   "17j709v28p7hiv49054mm1cacv8lxsx7djnwv5n0rad8b31p377p"
   "fastutil.jar"
   "import it.unimi.dsi.fastutil.ints.Int2IntOpenHashMap;
class Smoke { public static void main(String[] args) {
  Int2IntOpenHashMap map = new Int2IntOpenHashMap();
  map.put(7, 11); if (map.get(7) != 11) throw new AssertionError();
} }"))

(define java-json-simple-for-d8
  (source-java-library
   "java-json-simple" "1.1.1"
   "https://repo.maven.apache.org/maven2/com/googlecode/json-simple/json-simple/1.1.1/json-simple-1.1.1-sources.jar"
   "1mi4rrb4m5zmqf26mbwsxlyxagam5anrb515v9mc0kdnmq10x5i6"
   "json-simple.jar"
   "import org.json.simple.parser.JSONParser;
class Smoke { public static void main(String[] args) throws Exception {
  Object value = new JSONParser().parse(\"[1,2]\");
  if (((java.util.List) value).size() != 2) throw new AssertionError();
} }"))

(define %d8-libraries
  (list java-asm-for-d8 java-guava-for-d8 java-failureaccess-for-d8
        java-jopt-simple-for-d8 java-fastutil-for-d8 java-json-simple-for-d8))

(define %d8-library-jars
  #~(append-map
     (lambda (library)
       ;; Guix Java packages can use either share/java or lib/m2.
       (let ((jars (sort (find-files library "\\.jar$") string<?)))
         (when (null? jars)
           (error "D8 library has no installed JAR" library))
         jars))
     (list #$@%d8-libraries)))

(define-public android-d8
  (let ((commit "1a02d973acbb3efb83477a3d0c7e784b6946e648"))
    (package
      (name "android-d8")
      (version "1.0.25")
      (source
       (origin
         (method git-fetch)
         (uri (git-reference
               (url "https://r8.googlesource.com/r8")
               (commit commit)))
         (file-name (git-file-name name version))
         (patches (list (local-file "../../patches/d8-fix-dex-signature.patch")))
         (sha256
          (base32 "0jswx9fhnacihbpbkh7385fd6qf761psql8kf96wyqbzca4q7p2h"))))
      (build-system gnu-build-system)
      (arguments
       (list
        #:modules '((guix build gnu-build-system)
                    (guix build utils)
                    (srfi srfi-1)
                    (srfi srfi-13))
        #:phases
        #~(modify-phases %standard-phases
            (delete 'configure)
            (replace 'build
              (lambda _
                ;; Do not invoke Gradle/depot_tools or use third_party binary
                ;; archives. D8's Java 8 compiler predates the Kotlin dependency.
                (setenv "CLASSPATH"
                        (string-append
                         (getcwd) "/classes:"
                         (string-join #$%d8-library-jars ":")))
                (mkdir "classes")
                (apply invoke "javac" "-J-Xmx2G" "--release" "8"
                       "-encoding" "UTF-8" "-d" "classes"
                       (sort (find-files "src/main/java" "\\.java$") string<?))
                (call-with-output-file "classes/r8-version.properties"
                  (lambda (port)
                    (format port "version-file.version.code=1~%version.sha=~a~%releaser=Bitcoin Knots Guix~%"
                            #$commit)))
                (with-directory-excursion "classes"
                  (apply invoke "jar" "--create" "--file" "../d8.jar"
                         "--no-compress" "--date=1980-01-01T00:00:02Z"
                         (sort (find-files "." "\\.(class|properties)$") string<?)))))
            (replace 'check
              (lambda* (#:key tests? #:allow-other-keys)
                (when tests?
                  (invoke "java" "com.android.tools.r8.D8" "--version")
                  (call-with-output-file "Smoke.java"
                    (lambda (port)
                      (display "class Smoke {
  interface Callback { int apply(int value); }
  static int twice(int value) {
    Callback callback = x -> x * 2; return callback.apply(value);
  }
}" port)))
                  (mkdir "smoke")
                  (invoke "javac" "--release" "8" "-d" "smoke" "Smoke.java")
                  (for-each
                   (lambda (output)
                     (mkdir output)
                     (apply invoke "java" "com.android.tools.r8.D8"
                            "--release" "--min-api" "28" "--output" output
                            (sort (find-files "smoke" "\\.class$") string<?)))
                   '("dex-one" "dex-two"))
                  (invoke "cmp" "dex-one/classes.dex" "dex-two/classes.dex")
                  (call-with-output-file "CheckDex.java"
                    (lambda (port)
                      (display "import java.nio.*;
import java.nio.file.*;
import java.security.*;
import java.util.*;
import java.util.zip.*;
class CheckDex {
  public static void main(String[] args) throws Exception {
    byte[] data = Files.readAllBytes(Paths.get(args[0]));
    ByteBuffer header = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN);
    if (data.length < 112 || header.getInt(32) != data.length)
      throw new AssertionError(\"Invalid DEX file size\");
    byte[] signature = MessageDigest.getInstance(\"SHA-1\")
        .digest(Arrays.copyOfRange(data, 32, data.length));
    if (!Arrays.equals(signature, Arrays.copyOfRange(data, 12, 32)))
      throw new AssertionError(\"Invalid DEX SHA-1 signature\");
    Adler32 checksum = new Adler32();
    checksum.update(data, 12, data.length - 12);
    if ((int) checksum.getValue() != header.getInt(8))
      throw new AssertionError(\"Invalid DEX Adler-32 checksum\");
  }
}" port)))
                  (invoke "javac" "--release" "8" "CheckDex.java")
                  (invoke "java" "-cp" "." "CheckDex" "dex-one/classes.dex"))))
            (replace 'install
              (lambda* (#:key outputs #:allow-other-keys)
                (let* ((out (assoc-ref outputs "out"))
                       (bin (string-append out "/bin"))
                       (classpath
                        (string-join
                         (cons (string-append out "/share/java/d8.jar")
                               #$%d8-library-jars)
                         ":")))
                  (install-file "d8.jar" (string-append out "/share/java"))
                  (mkdir-p bin)
                  (call-with-output-file (string-append bin "/d8")
                    (lambda (port)
                      (format port "#!~a~%exec ~a -cp \"~a\" com.android.tools.r8.D8 \"$@\"~%"
                              #$(file-append bash-minimal "/bin/bash")
                              #$(file-append android-openjdk17 "/bin/java") classpath)))
                  (chmod (string-append bin "/d8") #o755)))))))
      (native-inputs (list (list android-openjdk17 "jdk")))
      (inputs
       (cons* bash-minimal android-openjdk17 %d8-libraries))
      (home-page "https://r8.googlesource.com/r8/")
      (synopsis "Source-built Java 8 to Android DEX compiler")
      (description
       "D8 converts Java 8 class files to Android DEX, including lambda and
default-interface desugaring.  This version supports API 28 and builds directly
with OpenJDK and source-built Java libraries, without Gradle, Kotlin, downloaded
SDKs or binary Maven dependencies.  Compile application Java with --release 8;
this package is not a compiler for newer Java class-file formats.")
      (license license:bsd-3))))
