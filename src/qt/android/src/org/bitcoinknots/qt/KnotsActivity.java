// Copyright (c) 2026 The Bitcoin Knots developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

package org.bitcoinknots.qt;

import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.os.Bundle;
import org.qtproject.qt.android.bindings.QtActivity;

/** The exported launcher must not accept node configuration from other apps. */
public final class KnotsActivity extends QtActivity {
    private void sanitizeConfigurationExtras(Intent intent) {
        if (intent == null || (getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
            return;
        }
        // Keep release startup configuration under this application's control,
        // independently of QtLoader's handling of configuration extras.
        intent.removeExtra("applicationArguments");
        intent.removeExtra("extraappparams");
        intent.removeExtra("extraenvvars");
    }

    @Override
    public void onCreate(Bundle savedInstanceState) {
        sanitizeConfigurationExtras(getIntent());
        super.onCreate(savedInstanceState);
    }

    @Override
    protected void onNewIntent(Intent intent) {
        sanitizeConfigurationExtras(intent);
        super.onNewIntent(intent);
    }
}
