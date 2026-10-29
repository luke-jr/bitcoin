// Copyright (c) 2011-2022 The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <bitcoin-build-config.h> // IWYU pragma: keep

#include <qt/splashscreen.h>

#include <clientversion.h>
#include <common/system.h>
#include <interfaces/handler.h>
#include <interfaces/node.h>
#include <interfaces/wallet.h>
#include <qt/guiutil.h>
#include <qt/networkstyle.h>
#include <qt/walletmodel.h>
#include <util/translation.h>

#include <functional>

#include <Qt>
#include <QtGlobal>
#include <QApplication>
#include <QCloseEvent>
#include <QPainter>
#include <QRadialGradient>
#include <QScreen>


SplashScreen::SplashScreen(const NetworkStyle* networkStyle)
    : QWidget()
{
    // set reference point, paddings
    int paddingRight            = 50;
    int titleVersionVSpace      = 17;
    int titleCopyrightVSpace    = 40;

    float fontFactor            = 1.0;
    float devicePixelRatio      = 1.0;
    devicePixelRatio = static_cast<QGuiApplication*>(QCoreApplication::instance())->devicePixelRatio();

    // define text to place
    QString titleText       = CLIENT_NAME;
    QString versionText     = QString("Version %1").arg(QString::fromStdString(FormatFullVersion()));
    QString copyrightText   = QString::fromUtf8(CopyrightHolders(strprintf("\xc2\xA9 %u-%u ", 2009, COPYRIGHT_YEAR)).c_str());
    const QString& titleAddText    = networkStyle->getTitleAddText();

    QString font            = GUIUtil::fixedPitchFont(/*use_embedded_font=*/ true).toString();

    // create a bitmap according to device pixelratio
    QSize splashSize(480*devicePixelRatio,320*devicePixelRatio);
    pixmap = QPixmap(splashSize);
#ifdef Q_OS_ANDROID
    // Paint the background across the native window, independently of the artwork.
    pixmap.fill(Qt::transparent);
#endif

    // change to HiDPI if it makes sense
    pixmap.setDevicePixelRatio(devicePixelRatio);

    QPainter pixPaint(&pixmap);
    pixPaint.setPen(QColor(0x17, 0x17, 0x17));

    // draw a slightly radial gradient
    QRadialGradient gradient(QPoint(0,0), splashSize.width()/devicePixelRatio);
    gradient.setColorAt(0, networkStyle->AdjustColour(QColor(0xde, 0x7e, 0x11)));
    gradient.setColorAt(1, networkStyle->AdjustColour(QColor(0xfe, 0xaa, 0x35)));
#ifdef Q_OS_ANDROID
    m_background_start = gradient.stops().first().second;
    m_background_end = gradient.stops().last().second;
#else
    QRect rGradient(QPoint(0,0), splashSize);
    pixPaint.fillRect(rGradient, gradient);
#endif

    // draw the bitcoin icon, expected size of PNG: 1024x1024
    const QPoint nonstatus_centre(splashSize.width() / 2 / devicePixelRatio, (splashSize.height() - (3 * QFontMetrics(font).lineSpacing() / 2)) / 2 / devicePixelRatio);
    const int icon_top{nonstatus_centre.y() - (nonstatus_centre.x() / 2)};
    QRect rectIcon(QPoint(0, icon_top), QSize(nonstatus_centre.x(), nonstatus_centre.x()));

    QPixmap icon(":/icons/splash");
    icon = icon.scaledToWidth(nonstatus_centre.x() * devicePixelRatio, Qt::SmoothTransformation);

    pixPaint.drawPixmap(rectIcon, icon);

    // check font size and drawing with
    QStringList titleParts = titleText.split(' ');
    assert(titleParts.size() == 2);
    pixPaint.setFont(QFont(font, 33*fontFactor));
    QFontMetrics fm = pixPaint.fontMetrics();
    int titleTextWidth = GUIUtil::TextWidth(fm, titleParts[0]);
    pixPaint.setFont(QFont(font, 50*fontFactor));
    fm = pixPaint.fontMetrics();
    titleTextWidth = qMax(titleTextWidth, GUIUtil::TextWidth(fm, titleParts[1]));
    const int titleTextMaxWidth{nonstatus_centre.x() - 10 - paddingRight};
    if (titleTextWidth > titleTextMaxWidth) {
        fontFactor = fontFactor * titleTextMaxWidth / titleTextWidth;
        titleTextWidth = titleTextMaxWidth;
    }

    // pixPaint.setBackgroundMode(Qt::OpaqueMode);  // TODO
    // pixPaint.setBackground(QBrush(QColor(255, 0, 0)));  // TODO
    pixPaint.setFont(QFont(font, 50*fontFactor));
    fm = pixPaint.fontMetrics();
    int titleTextWidth2{GUIUtil::TextWidth(fm, titleParts[1]) - 5};
    if (titleTextWidth != titleTextWidth2) {
        QFont tweaked_font(font, 50*fontFactor);
        tweaked_font.setPointSizeF(50.*fontFactor * titleTextWidth / titleTextWidth2);
        pixPaint.setFont(tweaked_font);
        fm = pixPaint.fontMetrics();
    }
    pixPaint.drawText(nonstatus_centre.x() + 3, nonstatus_centre.y(), titleParts[1]);
    const int titleTextHeight2{fm.ascent()};

    pixPaint.setFont(QFont(font, 33*fontFactor));
    fm = pixPaint.fontMetrics();
    titleTextWidth2 = GUIUtil::TextWidth(fm, titleParts[0]);
    if (titleTextWidth != titleTextWidth2) {
        QFont tweaked_font(font, 33*fontFactor);
        tweaked_font.setPointSizeF(33.*fontFactor * titleTextWidth / titleTextWidth2);
        pixPaint.setFont(tweaked_font);
    }
    pixPaint.drawText(nonstatus_centre.x() + 5, nonstatus_centre.y() - titleTextHeight2, titleParts[0]);
    // pixPaint.drawLine(nonstatus_centre.x()+5, nonstatus_centre.y(), nonstatus_centre.x()+5+titleTextWidth, nonstatus_centre.y()); // TODO
    // pixPaint.drawLine(nonstatus_centre.x()+5, nonstatus_centre.y() - titleTextHeight2, nonstatus_centre.x()+5+titleTextWidth, nonstatus_centre.y() - titleTextHeight2); // TODO

    pixPaint.setFont(QFont(font, 15*fontFactor));

    // if the version string is too long, reduce size
    fm = pixPaint.fontMetrics();
    int versionTextWidth  = GUIUtil::TextWidth(fm, versionText);
    int versionTextMaxWidth{titleTextWidth + paddingRight - 20};
    if(versionTextWidth > versionTextMaxWidth) {
        pixPaint.setFont(QFont(font, 15 * fontFactor * versionTextMaxWidth / versionTextWidth));
        fm = pixPaint.fontMetrics();
    }
    titleVersionVSpace = fm.lineSpacing() * 2;
    pixPaint.drawText(nonstatus_centre.x() + 10, nonstatus_centre.y() + titleVersionVSpace, versionText);

    // draw copyright stuff
    {
        pixPaint.setFont(QFont(QApplication::font().toString(), 10*fontFactor));
        fm = pixPaint.fontMetrics();
        titleCopyrightVSpace = titleVersionVSpace + (fm.lineSpacing() * (2 + copyrightText.count('\n')));
        const int x = nonstatus_centre.x() + 10;
        const int y = nonstatus_centre.y() + titleCopyrightVSpace;
        QRect copyrightRect(x, y, pixmap.width() - x, pixmap.height() - y);
        pixPaint.drawText(copyrightRect, Qt::AlignLeft | Qt::AlignTop | Qt::TextWordWrap, copyrightText);
    }

    // draw additional text if special network
    if(!titleAddText.isEmpty()) {
        QFont boldFont = QFont(font, 10*fontFactor);
        boldFont.setWeight(QFont::Bold);
        pixPaint.setFont(boldFont);
        fm = pixPaint.fontMetrics();
        int titleAddTextWidth  = GUIUtil::TextWidth(fm, titleAddText);
        pixPaint.drawText(pixmap.width()/devicePixelRatio-titleAddTextWidth-10,15,titleAddText);
    }

    pixPaint.end();

    // Set window title
    setWindowTitle(titleText + " " + titleAddText);

#ifdef Q_OS_ANDROID
    // Android owns the native window size, including orientation changes.
    QScreen* splash_screen = screen();
    setGeometry(splash_screen->availableGeometry());
    connect(splash_screen, &QScreen::availableGeometryChanged, this, [this](const QRect& geometry) {
        setGeometry(geometry);
    });
#else
    // Resize window and move to center of desktop, disallow resizing
    QRect r(QPoint(), QSize(pixmap.size().width()/devicePixelRatio,pixmap.size().height()/devicePixelRatio));
    resize(r.size());
    setFixedSize(r.size());
    move(QGuiApplication::primaryScreen()->geometry().center() - r.center());
#endif

    installEventFilter(this);

    GUIUtil::handleCloseWindowShortcut(this);
}

SplashScreen::~SplashScreen()
{
    if (m_node) unsubscribeFromCoreSignals();
}

void SplashScreen::setNode(interfaces::Node& node)
{
    assert(!m_node);
    m_node = &node;
    subscribeToCoreSignals();
    if (m_shutdown) m_node->startShutdown();
}

void SplashScreen::shutdown()
{
    m_shutdown = true;
    if (m_node) m_node->startShutdown();
}

bool SplashScreen::eventFilter(QObject * obj, QEvent * ev) {
    if (ev->type() == QEvent::KeyPress) {
        QKeyEvent *keyEvent = static_cast<QKeyEvent *>(ev);
        if (keyEvent->key() == Qt::Key_Q) {
            shutdown();
        }
    }
    return QObject::eventFilter(obj, ev);
}

static void InitMessage(SplashScreen *splash, const std::string &message)
{
    bool invoked = QMetaObject::invokeMethod(splash, "showMessage",
        Qt::QueuedConnection,
        Q_ARG(QString, QString::fromStdString(message)),
        Q_ARG(int, Qt::AlignBottom|Qt::AlignHCenter),
        Q_ARG(QColor, QColor(55,55,55)));
    assert(invoked);
}

static void ShowProgress(SplashScreen *splash, const std::string &title, int nProgress, bool resume_possible)
{
    InitMessage(splash, title + std::string("\n") +
            (resume_possible ? SplashScreen::tr("(press q to shutdown and continue later)").toStdString()
                                : SplashScreen::tr("press q to shutdown").toStdString()) +
            strprintf("\n%d", nProgress) + "%");
}

void SplashScreen::subscribeToCoreSignals()
{
    // Connect signals to client
    m_handler_init_message = m_node->handleInitMessage(std::bind(InitMessage, this, std::placeholders::_1));
    m_handler_show_progress = m_node->handleShowProgress(std::bind(ShowProgress, this, std::placeholders::_1, std::placeholders::_2, std::placeholders::_3));
    m_handler_init_wallet = m_node->handleInitWallet([this]() { handleLoadWallet(); });
}

void SplashScreen::handleLoadWallet()
{
#ifdef ENABLE_WALLET
    if (!WalletModel::isWalletEnabled()) return;
    m_handler_load_wallet = m_node->walletLoader().handleLoadWallet([this](std::unique_ptr<interfaces::Wallet> wallet) {
        m_connected_wallet_handlers.emplace_back(wallet->handleShowProgress(std::bind(ShowProgress, this, std::placeholders::_1, std::placeholders::_2, false)));
        m_connected_wallets.emplace_back(std::move(wallet));
    });
#endif
}

void SplashScreen::unsubscribeFromCoreSignals()
{
    // Disconnect signals from client
    m_handler_init_message->disconnect();
    m_handler_show_progress->disconnect();
    for (const auto& handler : m_connected_wallet_handlers) {
        handler->disconnect();
    }
    m_connected_wallet_handlers.clear();
    m_connected_wallets.clear();
}

void SplashScreen::showMessage(const QString &message, int alignment, const QColor &color)
{
    curMessage = message;
    curAlignment = alignment;
    curColor = color;
    update();
}

void SplashScreen::paintEvent(QPaintEvent *event)
{
    QPainter painter(this);
    QFont font = GUIUtil::fixedPitchFont(/*use_embedded_font=*/ true);
#ifdef Q_OS_ANDROID
    QRadialGradient background(QPointF(0, 0), qMax(width(), height()));
    background.setColorAt(0, m_background_start);
    background.setColorAt(1, m_background_end);
    painter.fillRect(rect(), background);

    // Keep progress text readable and outside the artwork when the phone rotates.
    font.setPointSizeF(qMax(12., QApplication::font().pointSizeF()));
    painter.setFont(font);
    const int padding{qMax(12, qMin(width(), height()) / 25)};
    const QRect content{rect().adjusted(padding, padding, -padding, -padding)};
    const int text_flags{curAlignment | Qt::TextWordWrap};
    const int message_height{qMin(content.height(), QFontMetrics(font).boundingRect(
        QRect(0, 0, content.width(), 0), text_flags, curMessage).height())};
    const QRect message_rect{content.left(), content.bottom() - message_height + 1,
                             content.width(), message_height};
    const QRect artwork_area{content.left(), content.top(), content.width(),
                             qMax(0, content.height() - message_height - padding)};
    const QSize artwork_size{pixmap.deviceIndependentSize().toSize().scaled(artwork_area.size(), Qt::KeepAspectRatio)};
    QRect artwork_rect{QPoint(), artwork_size};
    artwork_rect.moveCenter(artwork_area.center());
    painter.setRenderHint(QPainter::SmoothPixmapTransform);
    painter.drawPixmap(artwork_rect, pixmap);
    painter.setPen(curColor);
    painter.drawText(message_rect, text_flags, curMessage);
#else
    painter.drawPixmap(0, 0, pixmap);
    painter.setFont(font);
    QRect r = rect().adjusted(5, 5, -5, -5 - QFontMetrics(font).height() / 4);
    painter.setPen(curColor);
    painter.drawText(r, curAlignment, curMessage);
#endif
}

void SplashScreen::closeEvent(QCloseEvent *event)
{
    shutdown(); // allows an "emergency" shutdown during startup
    event->ignore();
}
