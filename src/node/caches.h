// Copyright (c) 2021 The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#ifndef BITCOIN_NODE_CACHES_H
#define BITCOIN_NODE_CACHES_H

#include <kernel/caches.h>
#include <util/byte_units.h>

#include <cstddef>
#include <limits>

class ArgsManager;

//! min. -dbcache (bytes)
static constexpr size_t MIN_DB_CACHE{4_MiB};
//! max. -dbcache (bytes)
static constexpr size_t MAX_DB_CACHE{sizeof(void*) > 4 ? 1048576_MiB : 3000_MiB};
//! -dbcache default (bytes)
static constexpr size_t DEFAULT_DB_CACHE{DEFAULT_KERNEL_CACHE};

namespace node {
struct IndexCacheSizes {
    size_t tx_index{0};
    size_t filter_index{0};
};
struct CacheSizes {
    IndexCacheSizes index;
    kernel::CacheSizes kernel;
};
CacheSizes CalculateCacheSizes(const ArgsManager& args, size_t n_indexes = 0);
} // namespace node

#endif // BITCOIN_NODE_CACHES_H
