// Copyright (c) 2026 The Bitcoin Knots developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

package org.bitcoinknots.qt;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.os.BatteryManager;

/** Device conditions observed by the Qt node's networking policy. */
public final class DeviceConditions {
    public static final int CELLULAR_METERED_OR_UNKNOWN = 1;
    public static final int ON_BATTERY_OR_UNKNOWN = 2;

    // Guarded by the class monitor, including native notification ordering.
    private static Context monitoringContext;
    private static ConnectivityManager connectivityManager;
    private static ConnectivityManager.NetworkCallback networkCallback;
    private static BroadcastReceiver batteryReceiver;
    private static int monitoringFailures;
    private static Network activeNetwork;
    private static int observedFlags = CELLULAR_METERED_OR_UNKNOWN | ON_BATTERY_OR_UNKNOWN;

    private DeviceConditions() {}

    /** Register this native method before calling start(). Runs on Android callback threads. */
    public static native void conditionsChanged(int flags);

    /** Starts once and immediately reports the current conditions. */
    public static synchronized void start(Context context) {
        if (monitoringContext != null) {
            reportConditions();
            return;
        }
        if (context == null) {
            conditionsChanged(CELLULAR_METERED_OR_UNKNOWN | ON_BATTERY_OR_UNKNOWN);
            return;
        }
        Context applicationContext;
        try {
            applicationContext = context.getApplicationContext();
        } catch (RuntimeException e) {
            conditionsChanged(CELLULAR_METERED_OR_UNKNOWN | ON_BATTERY_OR_UNKNOWN);
            return;
        }
        monitoringContext = applicationContext != null ? applicationContext : context;
        monitoringFailures = CELLULAR_METERED_OR_UNKNOWN | ON_BATTERY_OR_UNKNOWN;
        observedFlags = CELLULAR_METERED_OR_UNKNOWN | ON_BATTERY_OR_UNKNOWN;
        activeNetwork = null;
        try {
            connectivityManager = monitoringContext.getSystemService(ConnectivityManager.class);
            if (connectivityManager != null) {
                networkCallback = new ConnectivityManager.NetworkCallback() {
                    @Override
                    public void onAvailable(Network network) {
                        synchronized (DeviceConditions.class) {
                            if (networkCallback != this || monitoringContext == null) return;
                            activeNetwork = network;
                            observedFlags |= CELLULAR_METERED_OR_UNKNOWN;
                            reportConditions();
                        }
                    }

                    @Override
                    public void onLost(Network network) {
                        synchronized (DeviceConditions.class) {
                            if (networkCallback != this || !network.equals(activeNetwork)) return;
                            activeNetwork = null;
                            observedFlags |= CELLULAR_METERED_OR_UNKNOWN;
                            reportConditions();
                        }
                    }

                    @Override
                    public void onCapabilitiesChanged(Network network, NetworkCapabilities capabilities) {
                        synchronized (DeviceConditions.class) {
                            if (networkCallback != this || !network.equals(activeNetwork)) return;
                            observedFlags &= ~CELLULAR_METERED_OR_UNKNOWN;
                            if (isCellularMeteredOrUnknown(capabilities)) observedFlags |= CELLULAR_METERED_OR_UNKNOWN;
                            reportConditions();
                        }
                    }
                };
                connectivityManager.registerDefaultNetworkCallback(networkCallback);
                monitoringFailures &= ~CELLULAR_METERED_OR_UNKNOWN;
            }
        } catch (RuntimeException e) {
            // Without monitoring, a future cellular transition could be missed.
        }
        try {
            batteryReceiver = new BroadcastReceiver() {
                @Override
                public void onReceive(Context receiverContext, Intent intent) {
                    synchronized (DeviceConditions.class) {
                        if (batteryReceiver != this || monitoringContext == null) return;
                        updateBattery(intent);
                        reportConditions();
                    }
                }
            };
            // This is a system-only broadcast, so no receiver export flag is needed.
            Intent battery = monitoringContext.registerReceiver(batteryReceiver, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
            updateBattery(battery);
            monitoringFailures &= ~ON_BATTERY_OR_UNKNOWN;
        } catch (RuntimeException e) {
            // Keep the battery condition unknown if ongoing monitoring failed.
        }
        reportConditions();
    }

    /** Idempotently releases callbacks; already queued callbacks become no-ops. */
    public static synchronized void stop(Context context) {
        Context previousContext = monitoringContext;
        monitoringContext = null;
        if (connectivityManager != null && networkCallback != null) {
            try {
                connectivityManager.unregisterNetworkCallback(networkCallback);
            } catch (RuntimeException e) {
                // A registration failure or platform teardown may already remove it.
            }
        }
        if (previousContext != null && batteryReceiver != null) {
            try {
                previousContext.unregisterReceiver(batteryReceiver);
            } catch (RuntimeException e) {
                // Includes an unsuccessful registration or an already removed receiver.
            }
        }
        connectivityManager = null;
        networkCallback = null;
        batteryReceiver = null;
        monitoringFailures = 0;
        activeNetwork = null;
        observedFlags = CELLULAR_METERED_OR_UNKNOWN | ON_BATTERY_OR_UNKNOWN;
    }

    private static synchronized void reportConditions() {
        if (monitoringContext == null) return;
        // Callback arguments are ordered by Android; synchronous connectivity
        // queries inside callbacks can return stale state and must not replace them.
        conditionsChanged(observedFlags | monitoringFailures);
    }

    private static void updateBattery(Intent battery) {
        observedFlags &= ~ON_BATTERY_OR_UNKNOWN;
        if (isOnBatteryOrUnknown(battery)) observedFlags |= ON_BATTERY_OR_UNKNOWN;
    }

    private static boolean isCellularMeteredOrUnknown(NetworkCapabilities capabilities) {
        try {
            if (capabilities == null) return true;
            // Require an explicitly unmetered connection, including through VPNs.
            // Cellular remains restricted even if its plan is marked unmetered.
            if (!capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_METERED)) return true;
            if (capabilities.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)) return true;
            return !capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)
                    && !capabilities.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET);
        } catch (RuntimeException e) {
            return true;
        }
    }

    private static boolean isOnBatteryOrUnknown(Intent battery) {
        try {
            // External power is what matters, including a full battery or paused
            // charging. A missing sticky intent/extra must not permit networking.
            return battery == null || battery.getIntExtra(BatteryManager.EXTRA_PLUGGED, -1) <= 0;
        } catch (RuntimeException e) {
            return true;
        }
    }
}
