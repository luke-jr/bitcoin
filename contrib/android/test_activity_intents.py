#!/usr/bin/env python3
# Copyright (c) 2026 The Bitcoin Knots developers
# Distributed under the MIT software license, see the accompanying file COPYING.

"""Exercise the real launcher class against host Java lifecycle fixtures."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
ACTIVITY = ROOT / 'src/qt/android/src/org/bitcoinknots/qt/KnotsActivity.java'

FIXTURES = {
    'android/content/pm/ApplicationInfo.java': '''
package android.content.pm;
public class ApplicationInfo {
    public static final int FLAG_DEBUGGABLE = 2;
    public int flags;
}
''',
    'android/os/Bundle.java': '''
package android.os;
public class Bundle {}
''',
    'android/content/Intent.java': '''
package android.content;
import java.util.HashMap;
import java.util.Map;
public class Intent {
    public final Map<String, Object> extras = new HashMap<>();
    public String action = "android.intent.action.VIEW";
    public String data = "bitcoin:example?amount=1";
    public final Object clipData = new Object();
    public int flags = 0x10000001;
    public void removeExtra(String name) { extras.remove(name); }
}
''',
    'org/qtproject/qt/android/bindings/QtActivity.java': '''
package org.qtproject.qt.android.bindings;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.os.Bundle;
public class QtActivity {
    public static final String[] CONFIG = {"applicationArguments", "extraappparams", "extraenvvars"};
    public final ApplicationInfo info = new ApplicationInfo();
    public Intent launchIntent;
    public Intent deliveredIntent;
    public Bundle deliveredState;
    public int createCalls;
    public int newIntentCalls;
    public ApplicationInfo getApplicationInfo() { return info; }
    public Intent getIntent() { return launchIntent; }
    private void checkBeforeQtLoads(Intent intent) {
        if (intent == null) return;
        boolean debug = (info.flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0;
        for (String key : CONFIG) {
            if (intent.extras.containsKey(key) != debug)
                throw new AssertionError("Qt received incorrect extra: " + key);
        }
    }
    public void onCreate(Bundle state) {
        checkBeforeQtLoads(getIntent());
        createCalls++;
        deliveredIntent = getIntent();
        deliveredState = state;
    }
    protected void onNewIntent(Intent intent) {
        checkBeforeQtLoads(intent);
        newIntentCalls++;
        deliveredIntent = intent;
    }
}
''',
    'org/bitcoinknots/qt/ActivityIntentProbe.java': '''
package org.bitcoinknots.qt;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.os.Bundle;
import java.util.HashMap;
import java.util.Map;
import org.qtproject.qt.android.bindings.QtActivity;
public class ActivityIntentProbe {
    private static void require(boolean value) { if (!value) throw new AssertionError(); }
    private static Intent intent() {
        Intent intent = new Intent();
        for (String key : QtActivity.CONFIG) intent.extras.put(key, new Object());
        intent.extras.put("ordinary", new Object());
        intent.extras.put("android.intent.extra.REFERRER", "android-app://org.example");
        return intent;
    }
    private static void checkPreserved(Intent intent, Map<String, Object> before,
                                       Object clipData, boolean debug) {
        Map<String, Object> expected = new HashMap<>(before);
        if (!debug) for (String key : QtActivity.CONFIG) expected.remove(key);
        require(intent.extras.equals(expected));
        require(intent.action.equals("android.intent.action.VIEW"));
        require(intent.data.equals("bitcoin:example?amount=1"));
        require(intent.flags == 0x10000001);
        require(intent.clipData == clipData);
    }
    private static void exercise(boolean debug) {
        KnotsActivity activity = new KnotsActivity();
        activity.info.flags = 0x4000 | (debug ? ApplicationInfo.FLAG_DEBUGGABLE : 0);
        Intent initial = intent();
        Map<String, Object> initialExtras = new HashMap<>(initial.extras);
        Object initialClip = initial.clipData;
        activity.launchIntent = initial;
        Bundle state = new Bundle();
        activity.onCreate(state);
        require(activity.createCalls == 1 && activity.deliveredState == state);
        require(activity.deliveredIntent == initial);
        checkPreserved(initial, initialExtras, initialClip, debug);
        Intent next = intent();
        Map<String, Object> nextExtras = new HashMap<>(next.extras);
        Object nextClip = next.clipData;
        activity.onNewIntent(next);
        require(activity.newIntentCalls == 1 && activity.deliveredIntent == next);
        require(activity.getIntent() == initial); // Preserve Qt's lifecycle semantics.
        checkPreserved(next, nextExtras, nextClip, debug);
        checkPreserved(initial, initialExtras, initialClip, debug);
        activity.launchIntent = null;
        activity.onCreate(null);
        activity.onNewIntent(null);
        require(activity.createCalls == 2 && activity.newIntentCalls == 2);
    }
    public static void main(String[] args) { exercise(false); exercise(true); }
}
''',
}


class ActivityIntentTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('javac') and shutil.which('java'), 'Java compiler/runtime required')
    def test_release_and_debug_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sources = [str(ACTIVITY)]
            for name, content in FIXTURES.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
                sources.append(str(path))
            classes = root / 'classes'
            subprocess.run(['javac', '--release', '8', '-d', str(classes), *sources], check=True)
            subprocess.run(['java', '-cp', str(classes), 'org.bitcoinknots.qt.ActivityIntentProbe'], check=True)


if __name__ == '__main__':
    unittest.main()
