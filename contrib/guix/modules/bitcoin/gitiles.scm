;;; Copyright (c) 2026 The Bitcoin Knots developers
;;; Distributed under the MIT software license, see the accompanying
;;; file COPYING or https://opensource.org/license/mit-license.php.

(define-module (bitcoin gitiles)
  #:use-module (guix gexp)
  #:use-module (guix modules)
  #:use-module (guix monads)
  #:use-module (guix packages)
  #:use-module (guix store)
  #:use-module (guix utils)
  #:use-module (srfi srfi-1)
  #:export (gitiles-fetch))

(define* (gitiles-fetch url hash-algo hash
                        #:optional name
                        #:key (system (%current-system))
                        (guile (default-guile)))
  "Fetch the pinned Gitiles archive at URL and hash its extracted source tree.
Gitiles puts the request time in tar PAX headers, even for an immutable commit.
The recursive fixed-output hash authenticates file contents, executable bits and
symlink targets, independently of archive timestamps and compression."
  (define tar
    (module-ref (resolve-interface '(gnu packages base)) 'tar))
  (define gzip
    (module-ref (resolve-interface '(gnu packages compression)) 'gzip))
  (define certificates
    (module-ref (resolve-interface '(gnu packages certs)) 'nss-certs))
  (define extensions
    (list (module-ref (resolve-interface '(gnu packages tls)) 'guile-gnutls)
          (module-ref (resolve-interface '(gnu packages guile)) 'guile-json-4)
          (module-ref (resolve-interface '(gnu packages guile)) 'guile-lzlib)))
  (define modules
    (delete '(guix config)
            (source-module-closure '((guix build download)
                                     (bitcoin build gitiles))
                                   #:select?
                                   (lambda (module)
                                     (or (guix-module-name? module)
                                         (equal? module '(bitcoin build gitiles)))))))
  (mlet %store-monad ((guile (package->derivation (or guile (default-guile))
                                                  system)))
    (gexp->derivation (or name "gitiles-source")
      (with-imported-modules modules
        (with-extensions extensions
          #~(begin
              (use-modules (guix build download)
                           (bitcoin build gitiles))
              (%x509-certificate-directory
               #+(file-append certificates "/etc/ssl/certs"))
              (setenv "PATH" #+(file-append gzip "/bin"))
              (unless (url-fetch (getenv "gitiles url") "source.tar.gz")
                (error "Could not fetch Gitiles source archive"))
              (unpack-gitiles-archive "source.tar.gz" #$output
                                      #+(file-append tar "/bin/tar")))))
      #:system system
      #:guile-for-build guile
      #:env-vars `(("gitiles url" . ,url))
      #:leaked-env-vars '("http_proxy" "https_proxy")
      #:hash-algo hash-algo
      #:hash hash
      #:recursive? #t
      #:local-build? #t
      #:graft? #f)))
