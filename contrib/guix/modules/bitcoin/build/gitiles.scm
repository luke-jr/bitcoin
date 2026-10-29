;;; Copyright (c) 2026 The Bitcoin Knots developers
;;; Distributed under the MIT software license, see the accompanying
;;; file COPYING or https://opensource.org/license/mit-license.php.

(define-module (bitcoin build gitiles)
  #:use-module (guix build utils)
  #:export (unpack-gitiles-archive))

(define (unpack-gitiles-archive archive output tar)
  "Unpack a Gitiles ARCHIVE into OUTPUT, retaining source modes and symlinks.
The fixed-output derivation authenticates the resulting directory recursively;
ownership and timestamps are deliberately absent from that hash."
  (mkdir output)
  (invoke tar "--extract" "--gzip" "--file" archive
          "--directory" output "--same-permissions" "--no-same-owner"))
