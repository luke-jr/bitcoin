;;; Copyright (c) 2026 The Bitcoin Knots developers
;;; Distributed under the MIT software license, see the accompanying
;;; file COPYING or https://opensource.org/license/mit-license.php.

;; Run with a UTF-8 locale and GNU tar/gzip available:
;; guix repl -L contrib/guix/modules -- contrib/guix/tests/gitiles.scm
(use-modules (bitcoin build gitiles)
             (guix build utils)
             (guix hash)
             ((guix utils) #:select (call-with-temporary-directory))
             (ice-9 ftw)
             (srfi srfi-64))

(define (tree-hash path)
  (file-hash* path #:recursive? #t #:select? (const #t)))

(setlocale LC_ALL "")
(test-begin "gitiles")
(define runner (test-runner-current))
(call-with-temporary-directory
 (lambda (directory)
   (with-directory-excursion directory
     (mkdir "fixture")
     (call-with-output-file "fixture/source-µ.txt"
       (lambda (port) (display "Pinned source contents\n" port)))
     (call-with-output-file "fixture/run.sh"
       (lambda (port) (display "#!/bin/sh\nexit 0\n" port)))
     (chmod "fixture/run.sh" #o755)
     (symlink "source-µ.txt" "fixture/link")
     (symlink "missing-source.txt" "fixture/dangling")
     (for-each
      (lambda (archive timestamp)
        (invoke "tar" "--create" "--gzip" "--format=pax"
                "--owner=0" "--group=0" "--numeric-owner"
                (string-append "--mtime=@" timestamp)
                "--file" archive "--directory" "fixture" "."))
      '("first.tar.gz" "second.tar.gz") '("100" "200"))
     (test-assert "archive timestamps change the raw download hash"
       (not (equal? (file-hash* "first.tar.gz" #:recursive? #f)
                    (file-hash* "second.tar.gz" #:recursive? #f))))
     (unpack-gitiles-archive "first.tar.gz" "first" (which "tar"))
     (unpack-gitiles-archive "second.tar.gz" "second" (which "tar"))
     (let ((expected (tree-hash "first")))
       (test-equal "request timestamps do not affect the recursive source hash"
         expected (tree-hash "second"))
       (test-equal "source symlinks are preserved"
         "source-µ.txt" (readlink "second/link"))
       (test-equal "dangling source symlinks are preserved"
         "missing-source.txt" (readlink "second/dangling"))
       (call-with-output-file "second/source-µ.txt"
         (lambda (port) (display "Changed source contents\n" port)))
       (test-assert "changed source contents do not match the expected hash"
         (not (equal? expected (tree-hash "second"))))
       (call-with-output-file "second/source-µ.txt"
         (lambda (port) (display "Pinned source contents\n" port)))
       (chmod "second/run.sh" #o644)
       (test-assert "changed executable bits do not match the expected hash"
         (not (equal? expected (tree-hash "second"))))
       (chmod "second/run.sh" #o755)
       (delete-file "second/link")
       (symlink "run.sh" "second/link")
       (test-assert "changed symlink targets do not match the expected hash"
         (not (equal? expected (tree-hash "second"))))))))
(test-end "gitiles")
(exit (zero? (test-runner-fail-count runner)))
