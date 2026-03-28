// Copyright (c) 2011-2022 The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <interfaces/node.h>
#include <qt/trafficgraphwidget.h>
#include <logging.h>
#include <qt/clientmodel.h>
#include <qt/guiutil.h>
#include <streams.h>
#include <util/fs.h>
#include <util/fs_helpers.h>

#include <QMouseEvent>
#if (QT_VERSION >= QT_VERSION_CHECK(6, 0, 0))
#include <QtNumeric>
#endif
#include <QPainter>
#include <QPainterPath>
#include <QColor>
#include <QTimer>
#include <QToolTip>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>

#define DESIRED_SAMPLES         800

#define XMARGIN                 10
#define YMARGIN                 10

TrafficGraphWidget::TrafficGraphWidget(QWidget* parent)
    : QWidget(parent)
{
    m_timer = new QTimer(this);
    connect(m_timer, &QTimer::timeout, this, &TrafficGraphWidget::updateStuff);
    m_timer->setInterval(75);
    m_timer->start();
    setMouseTracking(true);
}

void TrafficGraphWidget::setClientModel(ClientModel *model)
{
    clientModel = model;
    if(model) {
        m_data_dir = model->dataDir().toStdString();
        m_node = &model->node();

        if (m_samples_in[0].empty() && m_samples_out[0].empty()) {
            loadData();
        }

        const quint64 bytes_in = model->node().getTotalBytesRecv();
        const quint64 bytes_out = model->node().getTotalBytesSent();
        const int64_t now = GetTime<std::chrono::milliseconds>().count();
        for (int i = 0; i < VALUES_SIZE; ++i) {
            m_last_bytes_in[i] = bytes_in;
            m_last_bytes_out[i] = bytes_out;
            m_last_time[i] = now - m_timer->interval();
        }
        m_last_save_ms = now;
    } else {
        saveData();
        m_node = nullptr;
    }
}

int TrafficGraphWidget::y_value(float value)
{
    if (fMax == 0) return 0;
    int h = height() - YMARGIN * 2;
    return YMARGIN + h - (h * 1.0 * (fToggle ? (std::pow(value, 0.30102) / std::pow(fMax, 0.30102)) : (value / fMax)));
}

void TrafficGraphWidget::paintPath(QPainterPath &path, QQueue<float> &samples)
{
    int sampleCount = samples.size();
    if(sampleCount > 0) {
        int h = height() - YMARGIN * 2, w = width() - XMARGIN * 2;
        int x = XMARGIN + w;
        path.moveTo(x, YMARGIN + h);
        for(int i = 0; i < sampleCount; ++i) {
            double ratio = static_cast<double>(i) * m_values[m_value] / m_range / DESIRED_SAMPLES;
            x = XMARGIN + w - static_cast<int>(w * ratio);
            int y = y_value(samples.at(i));
            path.lineTo(x, y);
        }
        path.lineTo(x, YMARGIN + h);
    }
}

void TrafficGraphWidget::mousePressEvent(QMouseEvent *event)
{
    QWidget::mousePressEvent(event);
    fToggle = !fToggle;
    update();
}

void TrafficGraphWidget::mouseMoveEvent(QMouseEvent *event)
{
    QWidget::mouseMoveEvent(event);
    static int last_x = -1;
    static int last_y = -1;
#if (QT_VERSION >= QT_VERSION_CHECK(6, 0, 0))
    const QPointF event_local_pos = event->position();
    const QPointF event_global_pos = event->globalPosition();
#else
    const QPointF event_local_pos = event->localPos();
    const QPointF event_global_pos = event->screenPos();
#endif
    int x = qRound(event_local_pos.x());
    int y = qRound(event_local_pos.y());
    x_offset = qRound(event_global_pos.x()) - x;
    y_offset = qRound(event_global_pos.y()) - y;
    if (last_x == x && last_y == y) return; // Do nothing if mouse hasn't moved
    int h = height() - YMARGIN * 2, w = width() - XMARGIN * 2;
    int i = (w + XMARGIN - x) * DESIRED_SAMPLES / w;
    unsigned int smallest_distance = 50; int closest_i = -1;
    auto vTimeStamp = m_time_stamp[m_value];
    auto& vSamplesIn = m_samples_in[m_value];
    auto& vSamplesOut = m_samples_out[m_value];
    int sampleSize = vTimeStamp.size();
    if (sampleSize && i >= -10 && i < sampleSize + 2 && y <= h + YMARGIN + 3) {
        for (int test_i = std::max(i - 2, 0); test_i < std::min(i + 10, sampleSize); test_i++) {
            float val = std::max(vSamplesIn.at(test_i), vSamplesOut.at(test_i));
            int y_data = y_value(val);
            unsigned int distance = abs(y - y_data);
            if (distance < smallest_distance) {
                smallest_distance = distance;
                closest_i = test_i;
            }
        }
    }
    if (ttpoint != closest_i) {
        ttpoint = closest_i;
        update(); // Calls paintEvent() to draw or delete the highlighted point
    }
    last_x = x; last_y = y;
}

void TrafficGraphWidget::paintEvent(QPaintEvent *)
{
    QPainter painter(this);
    painter.fillRect(rect(), Qt::black);

    if(fMax <= 0.0f) return;

    QColor axisCol(Qt::gray);
    int h = height() - YMARGIN * 2;
    painter.setPen(axisCol);
    painter.drawLine(XMARGIN, YMARGIN + h, width() - XMARGIN, YMARGIN + h);

    // decide what order of magnitude we are
    int base = std::floor(std::log10(fMax));
    float val = std::pow(10.0f, base);

    const QString units = tr("kB/s");
    const float yMarginText = 2.0;

    // if we drew 10 or 3 fewer lines, break them up at the next lower order of magnitude
    if(fMax / val <= (fToggle ? 10.0f : 3.0f)) {
        float oldval = val;
        val = std::pow(10.0f, base - 1);
        painter.setPen(axisCol.darker());
        painter.drawText(XMARGIN, y_value(val)-yMarginText, QString("%1 %2").arg(val).arg(units));
        if (fToggle) {
            int yy = y_value(val*0.1);
            painter.drawText(XMARGIN, yy-yMarginText, QString("%1 %2").arg(val*0.1).arg(units));
            painter.drawLine(XMARGIN, yy, width() - XMARGIN, yy);
        }
        int count = 1;
        for(float y = val; y < (!fToggle || fMax / val < 20 ? fMax : oldval); y += val, count++) {
            if(count % 10 == 0)
                continue;
            int yy = y_value(y);
            painter.drawLine(XMARGIN, yy, width() - XMARGIN, yy);
        }
        val = oldval;
    }
    // draw lines
    painter.setPen(axisCol);
    for(float y = val; y < fMax; y += val) {
        int yy = y_value(y);
        painter.drawLine(XMARGIN, yy, width() - XMARGIN, yy);
    }
    painter.drawText(XMARGIN, y_value(val)-yMarginText, QString("%1 %2").arg(val).arg(units));

    auto vTimeStamp = m_time_stamp[m_value];
    auto& vSamplesIn = m_samples_in[m_value];
    auto& vSamplesOut = m_samples_out[m_value];
    painter.setRenderHint(QPainter::Antialiasing);
    if(!vSamplesIn.empty()) {
        QPainterPath p;
        paintPath(p, vSamplesIn);
        painter.fillPath(p, QColor(0, 255, 0, 128));
        painter.setPen(Qt::green);
        painter.drawPath(p);
    }
    if(!vSamplesOut.empty()) {
        QPainterPath p;
        paintPath(p, vSamplesOut);
        painter.fillPath(p, QColor(255, 0, 0, 128));
        painter.setPen(Qt::red);
        painter.drawPath(p);
    }
    int sampleCount = vTimeStamp.size();
    if (ttpoint >= 0 && ttpoint < sampleCount) {
        painter.setPen(Qt::yellow);
        int w = width() - XMARGIN * 2;
        double ratio = static_cast<double>(ttpoint) * m_values[m_value] / m_range / DESIRED_SAMPLES;
        int x = XMARGIN + w - static_cast<int>(w * ratio);
        int y = y_value(std::max(vSamplesIn.at(ttpoint), vSamplesOut.at(ttpoint)));
        painter.drawEllipse(QPointF(x, y), 3, 3);
        QString strTime;
        int64_t sampleTime = vTimeStamp.at(ttpoint);
        int age = GetTime() - sampleTime/1000;
        if (age < 60*60*23)
            strTime = QString::fromStdString(FormatISO8601Time(sampleTime/1000));
        else
            strTime = QString::fromStdString(FormatISO8601DateTime(sampleTime/1000));
        int milliseconds_between_samples = 1000;
        if (ttpoint > 0)
            milliseconds_between_samples = std::min(milliseconds_between_samples, int(vTimeStamp.at(ttpoint-1) - sampleTime));
        if (ttpoint + 1 < sampleCount)
            milliseconds_between_samples = std::min(milliseconds_between_samples, int(sampleTime - vTimeStamp.at(ttpoint+1)));
        if (milliseconds_between_samples < 1000)
            strTime += QString::fromStdString(strprintf(".%03d", (sampleTime%1000)));
        QString strData = tr("In") + " " + GUIUtil::formatBytesps(vSamplesIn.at(ttpoint)*1000) + "\n" + tr("Out") + " " + GUIUtil::formatBytesps(vSamplesOut.at(ttpoint)*1000);
        // Line below allows ToolTip to move faster than once every 10 seconds.
        QToolTip::showText(QPoint(x + x_offset, y + y_offset), strTime + "\n. " + strData);
        QToolTip::showText(QPoint(x + x_offset, y + y_offset), strTime + "\n  " + strData);
        tt_time = GetTime();
    } else
        QToolTip::hideText();
}

void TrafficGraphWidget::updateFmax()
{
    float tmax = 0.0f;
    for (const float f : m_samples_in[m_value]) {
        if (f > tmax) tmax = f;
    }
    for (const float f : m_samples_out[m_value]) {
        if (f > tmax) tmax = f;
    }
    fMax = tmax;
}

void TrafficGraphWidget::updateStuff()
{
    if(!clientModel) return;

    int64_t expected_gap = m_timer->interval();
    int64_t now = GetTime<std::chrono::milliseconds>().count();
    static int64_t last_jump_time = 0;
    int64_t time_offset = 0;

    if (!m_time_stamp[0].empty()) {
        int64_t last_time = m_time_stamp[0].front();
        int64_t actual_gap = now - last_time;
        if (actual_gap >= 1000 + expected_gap && last_time != last_jump_time) {
            time_offset = actual_gap - expected_gap;
            last_jump_time = last_time;
        }
    }

    bool update_needed = false;

    for (int i = 0; i < VALUES_SIZE; i++) {
        int64_t msecs_per_sample = static_cast<int64_t>(m_values[i]) * 60000 / DESIRED_SAMPLES;
        if (time_offset) {
            m_offset[i] += time_offset;
            if (m_offset[i] > now - m_last_time[i]) m_offset[i] = now - m_last_time[i];
        }
        if (now > (m_last_time[i] + msecs_per_sample + m_offset[i] - expected_gap / 2)) {
            m_offset[i] = 0;
            updateRates(i);
            if (i == m_value) {
                if (ttpoint >=0 && ttpoint < DESIRED_SAMPLES) {
                    ttpoint++;
                    if (ttpoint >= DESIRED_SAMPLES) ttpoint = -1;
                }
                update_needed = true;
            }
        }
    }

    if (!QToolTip::isVisible() || !isVisible() || window()->isMinimized()) {
        if (ttpoint >= 0) {
            ttpoint = -1;
            update_needed = true;
        }
    } else if (ttpoint >= 0 && GetTime() >= tt_time + 9) {
        update_needed = true;
    }

    if (update_needed) {
        updateFmax();
        update();
    }

    if (!m_data_dir.empty() && now - m_last_save_ms >= 60000) {
        saveData();
        m_last_save_ms = now;
    }
}

void TrafficGraphWidget::updateRates(int i)
{
    int64_t now = GetTime<std::chrono::milliseconds>().count();
    quint64 bytesIn = clientModel->node().getTotalBytesRecv();
    quint64 bytesOut = clientModel->node().getTotalBytesSent();

    // Counters should be monotonic. If they reset (restart/load edge), rebase to avoid spike artifacts.
    if (m_last_time[i] <= 0 || bytesIn < m_last_bytes_in[i] || bytesOut < m_last_bytes_out[i]) {
        m_last_bytes_in[i] = bytesIn;
        m_last_bytes_out[i] = bytesOut;
        m_last_time[i] = now;
        return;
    }

    int64_t actual_gap = now - m_last_time[i];
    if (actual_gap <= 0) return;
    float in_rate_kilobytes_per_msec = static_cast<float>(bytesIn - m_last_bytes_in[i]) / actual_gap;
    float out_rate_kilobytes_per_msec = static_cast<float>(bytesOut - m_last_bytes_out[i]) / actual_gap;
    m_samples_in[i].push_front(in_rate_kilobytes_per_msec);
    m_samples_out[i].push_front(out_rate_kilobytes_per_msec);
    m_time_stamp[i].push_front(now);
    m_last_time[i] = now;
    m_last_bytes_in[i] = bytesIn;
    m_last_bytes_out[i] = bytesOut;

    static int8_t fFull[VALUES_SIZE] = {};
    if (fFull[i] == 0 && m_time_stamp[i].size() <= DESIRED_SAMPLES) {
        fFull[i] = -1;
    }
    while (m_time_stamp[i].size() > DESIRED_SAMPLES) {
        if (ttpoint < 0 && m_value == i && i < VALUES_SIZE - 1 && fFull[i] < 0) {
            m_bump_value = true;
        }
        fFull[i] = 1;
        m_samples_in[i].pop_back();
        m_samples_out[i].pop_back();
        m_time_stamp[i].pop_back();
    }
}

int TrafficGraphWidget::setGraphRange(int value)
{
    if (!value) {
        m_bump_value = false;
        value = m_value + 2;
    }

    value--;
    m_value = std::min(value, VALUES_SIZE - 1);
    m_range = m_values[m_value];
    ttpoint = -1;
    updateFmax();
    update();

    return m_values[m_value];
}

void TrafficGraphWidget::saveData()
{
    if (m_data_dir.empty()) return;

    try {
        const fs::path path_traffic_graph{fs::PathFromString(m_data_dir) / "trafficgraph.dat"};
        FILE* file = fsbridge::fopen(path_traffic_graph, "wb");
        if (!file) {
            const std::string file_path{fs::PathToString(path_traffic_graph)};
            LogPrintf("TrafficGraphWidget: failed to open file for writing: %s\n", file_path.c_str());
            return;
        }
        AutoFile file_out{file};
        if (file_out.IsNull()) return;

        file_out << static_cast<uint32_t>(1); // version

        // Always persist effective totals so autosave is crash-safe.
        quint64 total_bytes_recv = m_baseline_bytes_recv;
        quint64 total_bytes_sent = m_baseline_bytes_sent;
        if (m_node) {
            total_bytes_recv += m_node->getTotalBytesRecv();
            total_bytes_sent += m_node->getTotalBytesSent();
        }
        file_out << VARINT(total_bytes_recv) << VARINT(total_bytes_sent);

        for (int i = 0; i < VALUES_SIZE; ++i) {
            file_out << VARINT(static_cast<uint32_t>(m_time_stamp[i].size()));

            for (int j = 0; j < m_samples_in[i].size(); ++j) {
                const float value = m_samples_in[i].at(j);
                uint32_t uint_value;
                std::memcpy(&uint_value, &value, sizeof(value));
                file_out << uint_value;
            }

            for (int j = 0; j < m_samples_out[i].size(); ++j) {
                const float value = m_samples_out[i].at(j);
                uint32_t uint_value;
                std::memcpy(&uint_value, &value, sizeof(value));
                file_out << uint_value;
            }

            for (int j = 0; j < m_time_stamp[i].size(); ++j) {
                file_out << VARINT(static_cast<uint64_t>(m_time_stamp[i].at(j)));
            }

            file_out << VARINT(static_cast<uint64_t>(m_offset[i]));
        }
    } catch (const std::exception& e) {
        LogPrintf("TrafficGraphWidget: error saving data: %s\n", e.what());
    }
}

bool TrafficGraphWidget::loadDataFromBinary()
{
    if (m_data_dir.empty()) return false;

    try {
        const fs::path path_traffic_graph{fs::PathFromString(m_data_dir) / "trafficgraph.dat"};
        FILE* file = fsbridge::fopen(path_traffic_graph, "rb");
        if (!file) return false;

        AutoFile file_in{file};
        if (file_in.IsNull()) return false;

        uint32_t version = 0;
        file_in >> version;
        if (version != 1) return false;

        quint64 total_bytes_recv = 0;
        quint64 total_bytes_sent = 0;
        file_in >> VARINT(total_bytes_recv) >> VARINT(total_bytes_sent);
        m_baseline_bytes_recv = total_bytes_recv;
        m_baseline_bytes_sent = total_bytes_sent;

        for (int i = 0; i < VALUES_SIZE; ++i) {
            m_samples_in[i].clear();
            m_samples_out[i].clear();
            m_time_stamp[i].clear();
            m_offset[i] = 0;
        }

        for (int i = 0; i < VALUES_SIZE; ++i) {
            uint32_t sample_size = 0;
            file_in >> VARINT(sample_size);
            if (sample_size > DESIRED_SAMPLES) sample_size = DESIRED_SAMPLES;

            for (uint32_t j = 0; j < sample_size; ++j) {
                uint32_t uint_value = 0;
                file_in >> uint_value;
                float value = 0.0f;
                std::memcpy(&value, &uint_value, sizeof(value));
                m_samples_in[i].push_back(value);
            }

            for (uint32_t j = 0; j < sample_size; ++j) {
                uint32_t uint_value = 0;
                file_in >> uint_value;
                float value = 0.0f;
                std::memcpy(&value, &uint_value, sizeof(value));
                m_samples_out[i].push_back(value);
            }

            for (uint32_t j = 0; j < sample_size; ++j) {
                uint64_t time_ms = 0;
                file_in >> VARINT(time_ms);
                m_time_stamp[i].push_back(static_cast<int64_t>(time_ms));
            }

            uint64_t offset = 0;
            file_in >> VARINT(offset);
            m_offset[i] = static_cast<int64_t>(offset);
        }

        return true;
    } catch (const std::exception& e) {
        LogPrintf("TrafficGraphWidget: error loading data: %s\n", e.what());
        return false;
    }
}

bool TrafficGraphWidget::loadData()
{
    const bool success = loadDataFromBinary();
    if (!success) return false;

    int first_non_full_band = VALUES_SIZE - 1;
    for (int i = 0; i < VALUES_SIZE; ++i) {
        if (m_time_stamp[i].size() < DESIRED_SAMPLES) {
            first_non_full_band = i;
            break;
        }
    }

    if (first_non_full_band > 0) {
        m_value = first_non_full_band - 1;
        m_bump_value = true;
        m_range = m_values[m_value];
    }

    return true;
}
