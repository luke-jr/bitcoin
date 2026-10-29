// Copyright (c) 2026 The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#ifndef BITCOIN_QT_ANDROIDWINDOWCHROME_H
#define BITCOIN_QT_ANDROIDWINDOWCHROME_H

class QApplication;

/** Add Android dialog close controls and keep input placeholders readable across themes. */
void InstallAndroidWindowChrome(QApplication& application);

#endif // BITCOIN_QT_ANDROIDWINDOWCHROME_H
