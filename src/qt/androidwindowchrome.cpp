// Copyright (c) 2026 The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <qt/androidwindowchrome.h>

#include <QApplication>
#include <QColorDialog>
#include <QComboBox>
#include <QDialog>
#include <QEvent>
#include <QFileDialog>
#include <QFontDialog>
#include <QHBoxLayout>
#include <QInputDialog>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPainter>
#include <QPlainTextEdit>
#include <QProgressDialog>
#include <QPushButton>
#include <QScopedValueRollback>
#include <QTextEdit>
#include <QTimer>
#include <QVBoxLayout>
#include <QVariant>

namespace {
constexpr auto CHROME_NAME = "androidWindowChrome";

class WindowTitle : public QLabel
{
protected:
    void paintEvent(QPaintEvent*) override
    {
        QPainter painter(this);
        painter.setPen(palette().color(QPalette::WindowText));
        painter.drawText(rect(), Qt::AlignVCenter | Qt::AlignLeft,
                         fontMetrics().elidedText(text(), Qt::ElideRight, width()));
    }
};

bool CanClose(QWidget* window)
{
    return window->windowFlags().testFlag(Qt::WindowCloseButtonHint);
}

class AndroidWindowChrome : public QObject
{
    bool m_updating_palette{false};
    bool m_palette_refresh_queued{false};

    void UpdatePlaceholder(QWidget* widget)
    {
        if (m_updating_palette || !widget) return;
        if (!qobject_cast<QLineEdit*>(widget) && !qobject_cast<QTextEdit*>(widget) &&
            !qobject_cast<QPlainTextEdit*>(widget) && !qobject_cast<QComboBox*>(widget)) return;
        auto palette = widget->palette();
        bool changed{false};
        for (auto group : {QPalette::Active, QPalette::Inactive, QPalette::Disabled}) {
            const auto text = palette.color(group, QPalette::Text);
            const auto base = palette.color(group, QPalette::Base);
            // Android can supply a black placeholder even with a dark Base.
            // Blend into an opaque color so the platform cannot dim it again.
            const auto blend = [](int foreground, int background) {
                return (65 * foreground + 35 * background + 50) / 100;
            };
            const QColor placeholder{blend(text.red(), base.red()),
                                     blend(text.green(), base.green()),
                                     blend(text.blue(), base.blue())};
            if (palette.brush(group, QPalette::PlaceholderText) != QBrush(placeholder)) {
                palette.setColor(group, QPalette::PlaceholderText, placeholder);
                changed = true;
            }
        }
        if (changed) {
            // Retain the widget's existing resolve mask for every other role.
            // Inherited Text/Base colors can then follow live theme changes.
            QScopedValueRollback<bool> guard(m_updating_palette, true);
            widget->setPalette(palette);
        }
    }

public:
    using QObject::QObject;

protected:
    bool eventFilter(QObject* object, QEvent* event) override
    {
        if (event->type() == QEvent::ApplicationPaletteChange && !m_palette_refresh_queued) {
            m_palette_refresh_queued = true;
            QTimer::singleShot(0, this, [this] {
                m_palette_refresh_queued = false;
                for (auto* widget : QApplication::allWidgets()) UpdatePlaceholder(widget);
            });
        }
        if (event->type() == QEvent::PaletteChange || event->type() == QEvent::Polish || event->type() == QEvent::Show) {
            UpdatePlaceholder(qobject_cast<QWidget*>(object));
        }
        if (event->type() != QEvent::Show) return false;
        auto* window = qobject_cast<QWidget*>(object);
        if (!window || !window->isWindow()) return false;
        const auto type = window->windowType();
        if (type == Qt::Popup || type == Qt::ToolTip || type == Qt::SplashScreen) return false;
        if (!qobject_cast<QDialog*>(window) && !window->inherits("RPCConsole")) return false;
        // Framework dialogs provide their own action buttons and may rely on
        // their private root layout type. Leave those layouts intact, including
        // progress dialogs whose cancellation has deliberately been disabled.
        if (qobject_cast<QMessageBox*>(window) || qobject_cast<QFileDialog*>(window) ||
            qobject_cast<QInputDialog*>(window) || qobject_cast<QFontDialog*>(window) ||
            qobject_cast<QColorDialog*>(window) || qobject_cast<QProgressDialog*>(window)) return false;
        if (window->property(CHROME_NAME).toBool()) {
            auto* close = window->findChild<QPushButton*>(QStringLiteral("androidWindowCloseButton"));
            if (close) close->setVisible(CanClose(window));
            return false;
        }
        if (!window->layout() || !CanClose(window)) return false;
        window->setProperty(CHROME_NAME, true);

        auto* content = new QWidget;
        content->setObjectName(QStringLiteral("androidWindowContent"));
        content->setLayout(window->layout());
        auto* header = new QWidget(window);
        header->setObjectName(QString::fromLatin1(CHROME_NAME));
        header->setFixedHeight(48);
        auto* header_layout = new QHBoxLayout(header);
        header_layout->setContentsMargins(8, 0, 8, 0);
        auto* title = new WindowTitle;
        title->setObjectName(QStringLiteral("androidWindowTitle"));
        title->setText(window->windowTitle());
        title->setSizePolicy(QSizePolicy::Ignored, QSizePolicy::Preferred);
        connect(window, &QWidget::windowTitleChanged, title, &QLabel::setText);
        auto* close = new QPushButton(QApplication::translate("QPlatformTheme", "Close"), header);
        close->setObjectName(QStringLiteral("androidWindowCloseButton"));
        close->setMinimumSize(72, 48);
        close->setAutoDefault(false);
        connect(close, &QPushButton::clicked, window, &QWidget::close);
        header_layout->addWidget(title, 1);
        header_layout->addWidget(close);
        auto* layout = new QVBoxLayout(window);
        layout->setContentsMargins(0, 0, 0, 0);
        layout->setSpacing(0);
        layout->addWidget(header);
        layout->addWidget(content, 1);
        return false;
    }
};
} // namespace

void InstallAndroidWindowChrome(QApplication& application)
{
    application.installEventFilter(new AndroidWindowChrome(&application));
}
