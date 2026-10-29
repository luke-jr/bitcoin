// Copyright (c) 2009-2010 Satoshi Nakamoto
// Copyright (c) 2009-present The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <bitcoin-build-config.h> // IWYU pragma: keep

#include <common/system.h>

#include <logging.h>
#include <util/string.h>
#include <util/time.h>

#ifdef __ANDROID__
#include <android/log.h>
#include <mutex>
#endif

#ifndef WIN32
#include <sys/stat.h>
#include <unistd.h>
#else
#include <compat/compat.h>
#include <codecvt>
#include <windows.h>
#endif

#ifdef HAVE_MALLOPT_ARENA_MAX
#include <malloc.h>
#endif

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <locale>
#include <optional>
#include <stdexcept>
#include <string>
#include <thread>

using util::ReplaceAll;

#ifdef __ANDROID__
namespace {
void LogToAndroid(const std::string& message)
{
    // Leave room for logcat's metadata and keep UTF-8 code points intact.
    constexpr size_t MAX_CHUNK_SIZE{3800};
    for (size_t offset{0}; offset < message.size();) {
        size_t end = std::min(offset + MAX_CHUNK_SIZE, message.size());
        const auto newline = std::find(message.begin() + offset, message.begin() + end, '\n');
        if (newline != message.begin() + end) end = newline - message.begin() + 1;
        const size_t chunk_end = end;
        while (end < message.size() && end > offset &&
               (static_cast<unsigned char>(message[end]) & 0xc0) == 0x80) {
            --end;
        }
        // Still make progress if a malformed message contains only continuation bytes.
        if (end == offset) end = chunk_end;
        __android_log_write(ANDROID_LOG_INFO, "BitcoinKnots", message.substr(offset, end - offset).c_str());
        offset = end;
    }
}

void SetupAndroidLogging()
{
    static std::once_flag once;
    std::call_once(once, [] { LogInstance().PushBackCallback(LogToAndroid); });
}
} // namespace
#endif

#ifndef WIN32
std::string ShellEscape(const std::string& arg)
{
    std::string escaped = arg;
    ReplaceAll(escaped, "'", "'\"'\"'");
    return "'" + escaped + "'";
}
#endif

#if HAVE_SYSTEM
void runCommand(const std::string& strCommand)
{
    if (strCommand.empty()) return;
#ifndef WIN32
    int nErr = ::system(strCommand.c_str());
#else
    int nErr = ::_wsystem(std::wstring_convert<std::codecvt_utf8_utf16<wchar_t>,wchar_t>().from_bytes(strCommand).c_str());
#endif
    if (nErr) {
        LogWarning("runCommand error: system(%s) returned %d", strCommand, nErr);
    }
}
#endif

void SetupEnvironment(bool setup_process)
{
#ifdef __ANDROID__
    // Register before logging starts so buffered startup messages are mirrored too.
    SetupAndroidLogging();
#endif
    if (!setup_process) return;
#ifdef HAVE_MALLOPT_ARENA_MAX
    // glibc-specific: On 32-bit systems set the number of arenas to 1.
    // By default, since glibc 2.10, the C library will create up to two heap
    // arenas per core. This is known to cause excessive virtual address space
    // usage in our usage. Work around it by setting the maximum number of
    // arenas to 1.
    if (sizeof(void*) == 4) {
        mallopt(M_ARENA_MAX, 1);
    }
#endif
    // On most POSIX systems (e.g. Linux, but not BSD) the environment's locale
    // may be invalid, in which case the "C.UTF-8" locale is used as fallback.
#if !defined(WIN32) && !defined(__APPLE__) && !defined(__FreeBSD__) && !defined(__OpenBSD__) && !defined(__NetBSD__)
    try {
        std::locale(""); // Raises a runtime error if current locale is invalid
    } catch (const std::runtime_error&) {
        setenv("LC_ALL", "C.UTF-8", 1);
    }
#elif defined(WIN32)
    // Set the default input/output charset is utf-8
    SetConsoleCP(CP_UTF8);
    SetConsoleOutputCP(CP_UTF8);
#endif

#ifndef WIN32
    constexpr mode_t private_umask = 0077;
    umask(private_umask);
#endif
}

bool SetupNetworking()
{
#ifdef WIN32
    // Initialize Windows Sockets
    WSADATA wsadata;
    int ret = WSAStartup(MAKEWORD(2,2), &wsadata);
    if (ret != NO_ERROR || LOBYTE(wsadata.wVersion ) != 2 || HIBYTE(wsadata.wVersion) != 2)
        return false;
#endif
    return true;
}

int GetNumCores()
{
    return std::thread::hardware_concurrency();
}

namespace {
    const auto g_startup_time{SteadyClock::now()};
} // namespace

SteadyClock::duration GetUptime() { return SteadyClock::now() - g_startup_time; }
