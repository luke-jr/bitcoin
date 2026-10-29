// Copyright (c) 2018-2022 The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <qt/bitcoin.h>

#include <compat/compat.h>
#include <util/translation.h>

#include <QCoreApplication>

#ifdef Q_OS_ANDROID
#include <qt/androidjit.h>
#endif

#include <functional>
#include <string>

/** Translate string to current locale using Qt. */
extern const TranslateFn G_TRANSLATION_FUN = [](const char* psz) {
    return QCoreApplication::translate("bitcoin-core", psz).toStdString();
};

const std::function<std::string()> G_TEST_GET_FULL_NAME{};

MAIN_FUNCTION
{
#ifdef Q_OS_ANDROID
    // Honor an effective OS execmem restriction without triggering a denied
    // allocation. Otherwise preserve Qt's normal JIT behavior and overrides.
    if (AndroidExecmemBlocked()) qputenv("QT_ENABLE_REGEXP_JIT", "0");
#endif
    return GuiMain(argc, argv);
}
