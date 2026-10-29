// Copyright (c) 2026 The Bitcoin Knots developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or https://opensource.org/license/mit/.

package org.bitcoinknots.android;

/** In-process node module. The embedding application owns threading and lifecycle. */
public final class Node {
    public static final int INVALID_ARGUMENT = -1;
    public static final int ALREADY_STARTED = -2;
    public static final int INTERNAL_ERROR = -3;

    static { System.loadLibrary("knots"); }

    private Node() {}

    /**
     * Run synchronously on a host worker thread, once per process. Arguments are
     * ordinary bitcoind arguments, excluding argv[0]. Supply -datadir pointing to
     * an existing private directory owned by the host application. Arguments and
     * array entries must be nonnull and contain valid Unicode without NUL.
     * Returns the daemon's nonnegative exit status or one of the error constants.
     */
    public static native int run(String[] args);

    /** Request shutdown, including before run starts. Wait for run to return. */
    public static native void stop();
}
