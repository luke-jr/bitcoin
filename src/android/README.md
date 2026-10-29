# Embedding the Android node module

The Android node module runs Bitcoin Knots inside an embedding application's
process. It provides a C ABI and a Java JNI class; it does not provide an Android
application, Activity, Service, notification, or permission declarations. The host
owns its UI, threading, lifecycle, manifest, and any background execution support.
It also retains its signal handlers, allocation-failure handler, locale, and
file-creation mask. The module does not install daemon process policies; the host
must keep node files private and call the interrupt API for orderly shutdown.
The separate Qt GUI target is a complete application.

Build the module using the Android toolchain and `BUILD_ANDROID_MODULE=ON`.
Package `libknots.so` and its required shared libraries for the selected ABI in
the host application. The Java class is
`org.bitcoinknots.android.Node`; it loads `knots`. It uses only Java 8 APIs and can
be compiled into `classes.jar` without Android framework classes. Native hosts
can include the standalone C header `bitcoin_knots_node.h`.

Core has process-wide state, so **one invocation is supported per process**.
This includes an invocation that returns an initialization error or only prints
help. A new process is required for another invocation; do not attempt a restart
by unloading and reloading the library. Argument validation failures before the
daemon is entered do not consume the invocation.

Run the blocking API on a host-owned worker thread. Supply `-datadir=` with an
existing private directory owned by the host application. Arguments otherwise
have ordinary `bitcoind` semantics, including configuration-file processing. The
module does not add RPC settings, networking restrictions, data-directory choices,
or other command-line overrides. Daemonization is unsupported: the module rejects
enabled `-daemon` and `-daemonwait`, including settings loaded from configuration.

```java
// privateDataDirectory must already exist and belong to this application.
Thread worker = new Thread(() -> {
    int status = org.bitcoinknots.android.Node.run(new String[] {
        "-datadir=" + privateDataDirectory,
        "-networkactive=0"
    });
    // Deliver status to the host's lifecycle/UI coordinator.
}, "bitcoin-knots");
worker.start();

// Later, request shutdown from a host thread:
org.bitcoinknots.android.Node.stop();
// Wait on a suitable worker/lifecycle thread, never the Android UI thread:
worker.join();
```

`Node.run(String[])` excludes `argv[0]`; the JNI adapter supplies only that program
name. The array and its entries must be nonnull, valid Unicode strings without
embedded NUL characters. JNI converts UTF-16 to standard UTF-8, including
supplementary characters in directory paths. Pending JVM exceptions, such as
allocation failures, propagate normally; C++ exceptions do not cross JNI.

`bitcoin_knots_node_main(int argc, const char* const argv[])` includes `argv[0]`,
which must be nonempty. Every argument pointer must be nonnull. A final null
pointer after the `argc` entries is optional. The module copies the arguments;
their values are passed through unchanged.

Both entry points return the daemon's nonnegative exit status (`0` for success).
Negative module errors are stable:

| C constant | Java constant | Value | Meaning |
| --- | --- | ---: | --- |
| `BITCOIN_KNOTS_NODE_INVALID_ARGUMENT` | `Node.INVALID_ARGUMENT` | -1 | Invalid argument array or string. |
| `BITCOIN_KNOTS_NODE_ALREADY_STARTED` | `Node.ALREADY_STARTED` | -2 | A daemon invocation was already accepted in this process. |
| `BITCOIN_KNOTS_NODE_INTERNAL_ERROR` | `Node.INTERNAL_ERROR` | -3 | Native allocation failure or caught C++ exception. |

`bitcoin_knots_node_interrupt()` and `Node.stop()` are thread-safe shutdown
requests. A request before initialization finishes, or even before `run`, is
latched and delivered when the shutdown signal exists. Repeated requests are
safe. These functions do not wait, terminate the host, or kill its process. The
host must wait for the blocking run call to return before leaving the process or
unloading native code. The interrupt API is intended for ordinary threads, not
POSIX signal handlers.
