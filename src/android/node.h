// Copyright (c) 2026 The Bitcoin Knots developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or https://opensource.org/license/mit/.

#ifndef BITCOIN_ANDROID_NODE_H
#define BITCOIN_ANDROID_NODE_H

namespace node { struct NodeContext; }

namespace android {
/** Publish the daemon's shutdown signal while its context is alive. */
class NodeContextScope
{
public:
    explicit NodeContextScope(node::NodeContext& node);
    ~NodeContextScope();
    NodeContextScope(const NodeContextScope&) = delete;
    NodeContextScope& operator=(const NodeContextScope&) = delete;
};
} // namespace android

#endif // BITCOIN_ANDROID_NODE_H
