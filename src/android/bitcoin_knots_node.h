// Copyright (c) 2026 The Bitcoin Knots developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or https://opensource.org/license/mit/.

#ifndef BITCOIN_ANDROID_BITCOIN_KNOTS_NODE_H
#define BITCOIN_ANDROID_BITCOIN_KNOTS_NODE_H

#if defined(__GNUC__)
#define BITCOIN_KNOTS_NODE_API __attribute__((visibility("default")))
#else
#define BITCOIN_KNOTS_NODE_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

enum bitcoin_knots_node_error {
    BITCOIN_KNOTS_NODE_INVALID_ARGUMENT = -1,
    BITCOIN_KNOTS_NODE_ALREADY_STARTED = -2,
    BITCOIN_KNOTS_NODE_INTERNAL_ERROR = -3,
};

/**
 * Run the node synchronously, at most once per process, on a host worker thread.
 * argc includes argv[0], which must be nonempty. Every argument must be nonnull;
 * a terminating null argv entry is optional. Arguments are copied and passed
 * through unchanged. The host must supply its private data directory.
 * Returns the daemon's nonnegative exit status, or bitcoin_knots_node_error.
 * Invalid arguments and failures before entering the daemon do not consume the
 * one invocation. An invocation that reaches the daemon cannot be restarted.
 */
BITCOIN_KNOTS_NODE_API int bitcoin_knots_node_main(int argc, const char* const argv[]);

/**
 * Request shutdown from any host thread; this also latches before main starts.
 * The host must still wait for bitcoin_knots_node_main to return before leaving
 * the process or unloading the library. This is not a signal-handler API.
 */
BITCOIN_KNOTS_NODE_API void bitcoin_knots_node_interrupt(void);

#ifdef __cplusplus
} // extern "C"
#endif

#endif // BITCOIN_ANDROID_BITCOIN_KNOTS_NODE_H
