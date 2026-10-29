// Copyright (c) 2026 The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#ifndef BITCOIN_QT_ANDROIDJIT_H
#define BITCOIN_QT_ANDROIDJIT_H

#include <QFile>

/** Read the effective process policy without attempting an executable allocation. */
inline bool AndroidExecmemBlocked()
{
    // GrapheneOS SELinuxFlags.isExecmemBlocked() reads this same hexadecimal
    // process attribute and tests DENY_EXECMEM (bit 0). Other restrictions,
    // including DCL from storage or WebView DCL, do not imply this restriction.
    // https://github.com/GrapheneOS/platform_frameworks_base/blob/17/core/java/com/android/internal/os/SELinuxFlags.java
    QFile policy{QStringLiteral("/proc/self/attr/grapheneos_flags")};
    if (!policy.open(QIODevice::ReadOnly)) return false;
    bool valid{false};
    const auto flags = policy.readAll().trimmed().toULongLong(&valid, 16);
    // Stock Android has no such attribute. Unknown policy leaves Qt's normal
    // JIT behavior in place; only an explicit kernel restriction disables it.
    return valid && (flags & 1) != 0;
}

#endif // BITCOIN_QT_ANDROIDJIT_H
