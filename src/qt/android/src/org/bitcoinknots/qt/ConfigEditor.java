// Copyright (c) 2026 The Bitcoin Knots developers
// Distributed under the MIT software license, see the accompanying file COPYING.

package org.bitcoinknots.qt;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;

import androidx.core.content.FileProvider;

import java.io.File;

/** Opens only the configuration file with the user's preferred editor. */
public final class ConfigEditor {
    public static final int OPENED = 0;
    public static final int NO_EDITOR = 1;
    public static final int ERROR = 2;

    private ConfigEditor() {}

    /** Called on the Android main thread. The provider remains non-exported. */
    public static int open(Context context, String path) {
        try {
            Uri uri = FileProvider.getUriForFile(context,
                    context.getPackageName() + ".qtprovider", new File(path));
            Intent intent = new Intent(Intent.ACTION_EDIT);
            intent.setDataAndType(uri, "text/plain");
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                    | Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
            intent.setClipData(ClipData.newRawUri("Bitcoin configuration", uri));
            if (!(context instanceof Activity)) {
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            }
            // Do not wrap in a chooser: Android should honor the preferred editor.
            context.startActivity(intent);
            return OPENED;
        } catch (ActivityNotFoundException e) {
            return NO_EDITOR;
        } catch (IllegalArgumentException | SecurityException e) {
            return ERROR;
        }
    }
}
