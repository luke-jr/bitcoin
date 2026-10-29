// Copyright (c) 2026 The Bitcoin Knots developers
// Distributed under the MIT software license, see the accompanying file COPYING.

#ifndef BITCOIN_QT_ANDROIDNETWORKPOLICY_H
#define BITCOIN_QT_ANDROIDNETWORKPOLICY_H

#include <QObject>
#include <QMutex>
#include <QString>

#include <atomic>
#include <memory>

class OptionsModel;
namespace interfaces { class Handler; class Node; }

/** Automatically operate the existing network toggle when device conditions change. */
class AndroidNetworkPolicy : public QObject
{
    Q_OBJECT
public:
    AndroidNetworkPolicy(interfaces::Node& node, OptionsModel& options);
    ~AndroidNetworkPolicy();
    /** Hand off a startup-disabled connection manager, preserving -networkactive=0. */
    void start(bool initially_active = true);
    void stop();
    QString pauseReason() const;
    // Called with the bridge lifetime mutex held, including from Java threads.
    void updateConditions(int flags);
    void updateNetworkActive(bool active);

Q_SIGNALS:
    void pauseReasonChanged(const QString& reason);

private:
    void updateOptions();
    void apply();
    void setPauseReason(const QString& reason);
    interfaces::Node& m_node;
    OptionsModel& m_options;
    std::atomic<bool> m_ready{false};
    bool m_registered{false};
    bool m_policy_paused{false};
    bool m_setting_network{false};
    bool m_cellular{true};
    bool m_battery{true};
    int m_flags{3};
    mutable QMutex m_reason_mutex;
    QString m_reason;
    std::unique_ptr<interfaces::Handler> m_network_handler;
};

#endif // BITCOIN_QT_ANDROIDNETWORKPOLICY_H
