// Copyright (c) 2011-2022 The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <interfaces/node.h>
#include <qt/trafficgraphwidget.h>
#include <qt/clientmodel.h>
#include <qt/guiutil.h>

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
        const quint64 bytes_in = model->node().getTotalBytesRecv();
        const quint64 bytes_out = model->node().getTotalBytesSent();
        const int64_t now = GetTime<std::chrono::milliseconds>().count();
        for (int i = 0; i < VALUES_SIZE; ++i) {
            m_last_bytes_in[i] = bytes_in;
            m_last_bytes_out[i] = bytes_out;
            m_last_time[i] = now - m_timer->interval();
        }
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
}

void TrafficGraphWidget::updateRates(int i)
{
    int64_t now = GetTime<std::chrono::milliseconds>().count();
    int64_t actual_gap = now - m_last_time[i];
    quint64 bytesIn = clientModel->node().getTotalBytesRecv();
    quint64 bytesOut = clientModel->node().getTotalBytesSent();
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
