// Copyright (c) 2026 The Bitcoin Knots developers
// Distributed under the MIT software license, see the accompanying file COPYING.

#include <qt/androidnetworkpolicy.h>
#include <qt/optionsmodel.h>
#include <interfaces/handler.h>
#include <interfaces/node.h>

#include <QCoreApplication>
#include <QJniEnvironment>
#include <QJniObject>
#include <QMutexLocker>
#include <QScopedValueRollback>
#include <QStringList>
#include <QThread>
#include <QtCore/qcoreapplication_platform.h>

#include <mutex>

namespace {
constexpr auto CONDITIONS_CLASS = "org/bitcoinknots/qt/DeviceConditions";
constexpr int CELLULAR_METERED_OR_UNKNOWN = 1;
constexpr int ON_BATTERY_OR_UNKNOWN = 2;
std::mutex g_bridge_mutex;
AndroidNetworkPolicy* g_policy{nullptr};

void ConditionsChanged(JNIEnv*, jclass, jint flags)
{
    std::lock_guard lock{g_bridge_mutex};
    if (g_policy) g_policy->updateConditions(flags);
}
} // namespace

AndroidNetworkPolicy::AndroidNetworkPolicy(interfaces::Node& node, OptionsModel& options)
    : m_node(node), m_options(options)
{
    m_cellular = options.getPauseOnCellular();
    m_battery = options.getPauseOnBattery();
    QJniEnvironment env;
    const JNINativeMethod methods[] = {{const_cast<char*>("conditionsChanged"), const_cast<char*>("(I)V"), reinterpret_cast<void*>(ConditionsChanged)}};
    m_registered = env.registerNativeMethods(CONDITIONS_CLASS, methods, 1);
    if (env->ExceptionCheck()) env->ExceptionClear();
    {
        std::lock_guard lock{g_bridge_mutex};
        g_policy = this;
    }
    m_network_handler = node.handleNotifyNetworkActiveChanged([](bool active) {
        std::lock_guard lock{g_bridge_mutex};
        if (g_policy) g_policy->updateNetworkActive(active);
    });
    // The dialog submits both fields in one mapper operation. Read their final
    // values together rather than briefly applying an intermediate combination.
    connect(&options, &OptionsModel::networkPolicyChanged, this, &AndroidNetworkPolicy::updateOptions, Qt::QueuedConnection);
}

AndroidNetworkPolicy::~AndroidNetworkPolicy()
{
    stop();
}

void AndroidNetworkPolicy::start(bool initially_active)
{
    if (m_ready) return;
    m_ready = true;
    // The frontend temporarily initializes with -networkactive=0. Only claim
    // that pause when the user's original setting requested active networking.
    m_policy_paused = initially_active && !m_node.getNetworkActive();
    apply();
    // Java sends its initial native callback synchronously. Never hold the
    // bridge mutex here (or across stop's unregister calls).
    if (m_registered) {
        const auto context = QNativeInterface::QAndroidApplication::context();
        QJniObject::callStaticMethod<void>(CONDITIONS_CLASS, "start", "(Landroid/content/Context;)V", context.object());
    }
}

void AndroidNetworkPolicy::stop()
{
    {
        std::lock_guard lock{g_bridge_mutex};
        if (g_policy != this) return;
        g_policy = nullptr;
    }
    m_ready = false;
    m_network_handler.reset();
    if (m_registered) {
        const auto context = QNativeInterface::QAndroidApplication::context();
        QJniObject::callStaticMethod<void>(CONDITIONS_CLASS, "stop", "(Landroid/content/Context;)V", context.object());
    }
}

void AndroidNetworkPolicy::updateConditions(int flags)
{
    // Android callbacks run on Java threads. Serialize decisions with GUI
    // actions, and let QObject discard queued calls when this policy is deleted.
    QMetaObject::invokeMethod(this, [this, flags] {
        const int enabled = (m_cellular ? CELLULAR_METERED_OR_UNKNOWN : 0) |
                            (m_battery ? ON_BATTERY_OR_UNKNOWN : 0);
        const bool changed = (m_flags ^ flags) & enabled;
        m_flags = flags;
        if (m_ready && changed) apply();
    }, Qt::QueuedConnection);
}

void AndroidNetworkPolicy::updateNetworkActive(bool active)
{
    if (!m_ready) return;
    // Our setter emits the baseline notification synchronously on this thread.
    // Every other notification represents an external action, including RPC.
    if (QThread::currentThread() == thread() && m_setting_network) return;
    QMetaObject::invokeMethod(this, [this, active] {
        if (!m_ready || m_node.getNetworkActive() != active) return;
        m_policy_paused = false;
        setPauseReason(QString());
    }, Qt::QueuedConnection);
}

void AndroidNetworkPolicy::updateOptions()
{
    const bool cellular = m_options.getPauseOnCellular();
    const bool battery = m_options.getPauseOnBattery();
    if (m_cellular == cellular && m_battery == battery) return;
    m_cellular = cellular;
    m_battery = battery;
    if (m_ready) apply();
}

QString AndroidNetworkPolicy::pauseReason() const
{
    QMutexLocker lock{&m_reason_mutex};
    return m_reason;
}

void AndroidNetworkPolicy::setPauseReason(const QString& reason)
{
    bool changed;
    {
        QMutexLocker lock{&m_reason_mutex};
        changed = m_reason != reason;
        m_reason = reason;
    }
    if (changed) Q_EMIT pauseReasonChanged(reason);
}

void AndroidNetworkPolicy::apply()
{
    QStringList reasons;
    if (m_cellular && (m_flags & CELLULAR_METERED_OR_UNKNOWN)) reasons << tr("cellular, metered, or unknown connection");
    if (m_battery && (m_flags & ON_BATTERY_OR_UNKNOWN)) reasons << tr("battery power or unknown power source");
    const bool active = m_node.getNetworkActive();
    if (!reasons.isEmpty() && active) {
        m_policy_paused = true;
        QScopedValueRollback<bool> guard(m_setting_network, true);
        m_node.setNetworkActive(false);
    } else if (reasons.isEmpty() && m_policy_paused) {
        m_policy_paused = false;
        QScopedValueRollback<bool> guard(m_setting_network, true);
        m_node.setNetworkActive(true);
    }
    setPauseReason(m_policy_paused && !reasons.isEmpty()
        ? tr("Networking paused: %1.").arg(reasons.join(tr("; ")))
        : QString());
}
