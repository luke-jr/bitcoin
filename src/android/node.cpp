// Copyright (c) 2026 The Bitcoin Knots developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or https://opensource.org/license/mit/.

#include <android/node.h>
#include <android/bitcoin_knots_node.h>
#include <node/context.h>
#include <util/signalinterrupt.h>

#include <jni.h>

#include <atomic>
#include <limits>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

int AndroidNodeMain(int argc, char* argv[]);

namespace {
std::mutex g_mutex;
util::SignalInterrupt* g_interrupt{nullptr};
bool g_stop_requested{false};
std::atomic<bool> g_started{false};

class LocalString
{
    JNIEnv* const m_env;
    const jstring m_string;

public:
    LocalString(JNIEnv* env, jstring string) : m_env(env), m_string(string) {}
    ~LocalString() { if (m_string) m_env->DeleteLocalRef(m_string); }
    LocalString(const LocalString&) = delete;
    LocalString& operator=(const LocalString&) = delete;
};

/** JNI's modified UTF-8 is not suitable for filesystem paths; convert UTF-16. */
bool CopyArgument(JNIEnv* env, jstring value, std::string& argument)
{
    const jsize length = env->GetStringLength(value);
    if (env->ExceptionCheck()) return false;
    auto release = [env, value](const jchar* chars) { env->ReleaseStringChars(value, chars); };
    std::unique_ptr<const jchar, decltype(release)> chars{env->GetStringChars(value, nullptr), release};
    if (!chars) return false;
    argument.reserve(length);
    for (jsize i = 0; i < length; ++i) {
        unsigned int codepoint = chars.get()[i];
        if (codepoint == 0) return false;
        if (codepoint >= 0xd800 && codepoint <= 0xdbff) {
            if (++i == length) return false;
            const unsigned int low = chars.get()[i];
            if (low < 0xdc00 || low > 0xdfff) return false;
            codepoint = 0x10000 + ((codepoint - 0xd800) << 10) + (low - 0xdc00);
        } else if (codepoint >= 0xdc00 && codepoint <= 0xdfff) {
            return false;
        }
        if (codepoint <= 0x7f) {
            argument.push_back(codepoint);
        } else if (codepoint <= 0x7ff) {
            argument.push_back(0xc0 | (codepoint >> 6));
            argument.push_back(0x80 | (codepoint & 0x3f));
        } else if (codepoint <= 0xffff) {
            argument.push_back(0xe0 | (codepoint >> 12));
            argument.push_back(0x80 | ((codepoint >> 6) & 0x3f));
            argument.push_back(0x80 | (codepoint & 0x3f));
        } else {
            argument.push_back(0xf0 | (codepoint >> 18));
            argument.push_back(0x80 | ((codepoint >> 12) & 0x3f));
            argument.push_back(0x80 | ((codepoint >> 6) & 0x3f));
            argument.push_back(0x80 | (codepoint & 0x3f));
        }
    }
    return true;
}
} // namespace

android::NodeContextScope::NodeContextScope(node::NodeContext& node)
{
    std::lock_guard lock{g_mutex};
    g_interrupt = node.shutdown_signal;
    if (g_stop_requested && g_interrupt) (void)(*g_interrupt)();
}

android::NodeContextScope::~NodeContextScope()
{
    std::lock_guard lock{g_mutex};
    g_interrupt = nullptr;
}

extern "C" BITCOIN_KNOTS_NODE_API int bitcoin_knots_node_main(int argc, const char* const argv[])
{
    try {
        if (argc < 1 || !argv || !argv[0] || !argv[0][0]) return BITCOIN_KNOTS_NODE_INVALID_ARGUMENT;
        for (int i = 1; i < argc; ++i) {
            if (!argv[i]) return BITCOIN_KNOTS_NODE_INVALID_ARGUMENT;
        }
        if (g_started) return BITCOIN_KNOTS_NODE_ALREADY_STARTED;
        std::vector<std::string> arguments;
        arguments.reserve(argc);
        for (int i = 0; i < argc; ++i) arguments.emplace_back(argv[i]);
        std::vector<char*> mutable_argv;
        mutable_argv.reserve(arguments.size() + 1);
        for (auto& argument : arguments) mutable_argv.push_back(argument.data());
        mutable_argv.push_back(nullptr);
        if (g_started.exchange(true)) return BITCOIN_KNOTS_NODE_ALREADY_STARTED;
        return AndroidNodeMain(argc, mutable_argv.data());
    } catch (...) {
        return BITCOIN_KNOTS_NODE_INTERNAL_ERROR;
    }
}

extern "C" BITCOIN_KNOTS_NODE_API void bitcoin_knots_node_interrupt(void)
{
    try {
        std::lock_guard lock{g_mutex};
        g_stop_requested = true;
        if (g_interrupt) (void)(*g_interrupt)();
    } catch (...) {
        // Never unwind a C++ exception through a host's C or JNI boundary.
    }
}

extern "C" JNIEXPORT jint JNICALL
Java_org_bitcoinknots_android_Node_run(JNIEnv* env, jclass, jobjectArray args)
{
    if (!args) return BITCOIN_KNOTS_NODE_INVALID_ARGUMENT;
    try {
        const jsize count = env->GetArrayLength(args);
        if (env->ExceptionCheck()) return BITCOIN_KNOTS_NODE_INTERNAL_ERROR;
        if (count == std::numeric_limits<int>::max()) return BITCOIN_KNOTS_NODE_INVALID_ARGUMENT;
        std::vector<std::string> arguments;
        arguments.reserve(static_cast<size_t>(count) + 1);
        arguments.emplace_back("bitcoin-knots");
        for (jsize i = 0; i < count; ++i) {
            const auto value = static_cast<jstring>(env->GetObjectArrayElement(args, i));
            LocalString reference{env, value};
            if (env->ExceptionCheck()) return BITCOIN_KNOTS_NODE_INTERNAL_ERROR;
            if (!value) return BITCOIN_KNOTS_NODE_INVALID_ARGUMENT;
            arguments.emplace_back();
            if (!CopyArgument(env, value, arguments.back())) {
                return env->ExceptionCheck() ? BITCOIN_KNOTS_NODE_INTERNAL_ERROR : BITCOIN_KNOTS_NODE_INVALID_ARGUMENT;
            }
        }
        std::vector<const char*> argv;
        argv.reserve(arguments.size());
        for (const auto& argument : arguments) argv.push_back(argument.c_str());
        return bitcoin_knots_node_main(static_cast<int>(arguments.size()), argv.data());
    } catch (...) {
        return BITCOIN_KNOTS_NODE_INTERNAL_ERROR;
    }
}

extern "C" JNIEXPORT void JNICALL
Java_org_bitcoinknots_android_Node_stop(JNIEnv*, jclass)
{
    bitcoin_knots_node_interrupt();
}
