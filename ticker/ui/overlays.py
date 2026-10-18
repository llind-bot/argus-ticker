"""Always-on-top windows: the floating widget and the scrolling ticker strip."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPoint, QPointF, QRectF, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCursor, QFont, QGuiApplication, QPainter
from PySide6.QtWidgets import QMenu, QWidget

from . import theme
from .state import LiveState, Row

_FLAGS = Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint


class _Overlay(QWidget):
    """Frameless on-top window with a right-click menu; draggable when ``movable``."""
    open_main = Signal()
    switch_to = Signal(str)                       # "widget" | "strip"
    movable = True

    def __init__(self, state: LiveState):
        super().__init__(None, _FLAGS)
        self.state = state
        self.setAttribute(Qt.WA_TranslucentBackground)
        state.changed.connect(self.update)
        self._drag: Optional[QPoint] = None

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton and self.movable:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e) -> None:
        if self._drag is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, e) -> None:
        self._drag = None

    def contextMenuEvent(self, e) -> None:
        m = QMenu(self)
        self.extend_menu(m)
        m.addSeparator()
        m.addAction("Open watchlist", self.open_main.emit)
        other = "strip" if isinstance(self, TickerStrip) else "widget"
        m.addAction("Switch to ticker strip" if other == "strip" else "Switch to floating widget",
                    lambda: self.switch_to.emit(other))
        m.addAction("Close", self._close_to_main)
        m.exec(e.globalPos())

    def extend_menu(self, m: QMenu) -> None:
        pass

    def _close_to_main(self) -> None:
        self.hide()
        self.open_main.emit()


class FloatingWidget(_Overlay):
    W, HEAD, HERO, ROW, FOOT = 320, 40, 132, 48, 8

    def __init__(self, state: LiveState):
        super().__init__(state)
        self.headline_id: Optional[int] = QSettings().value("widget/headline", None, type=int) or None
        self._row_hits: list[tuple[QRectF, int]] = []
        self._close_rect = QRectF()
        state.changed.connect(self._fit)
        self._fit()
        pos = QSettings().value("widget/pos")
        if isinstance(pos, QPoint):
            self.move(pos)
        else:
            g = QGuiApplication.primaryScreen().availableGeometry()
            self.move(g.right() - self.W - 24, g.top() + 80)

    def _headline(self) -> Optional[Row]:
        rows = self.state.rows()
        if not rows:
            return None
        return next((r for r in rows if r.entry.id == self.headline_id), rows[0])

    def _fit(self) -> None:
        n = max(0, len(self.state.entries) - 1)
        h = self.HEAD + (self.HERO if self.state.entries else 60) + n * self.ROW + self.FOOT + 8
        if self.height() != h or self.width() != self.W:
            self.setFixedSize(self.W, h)

    def moveEvent(self, e) -> None:
        QSettings().setValue("widget/pos", self.pos())
        super().moveEvent(e)

    def mousePressEvent(self, e) -> None:
        if self._close_rect.contains(e.position()):
            self._close_to_main()
            return
        for rect, entry_id in self._row_hits:
            if rect.contains(e.position()):
                self.headline_id = entry_id
                QSettings().setValue("widget/headline", entry_id)
                self.update()
                return
        super().mousePressEvent(e)

    def paintEvent(self, _e) -> None:
        s = self.state
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        theme.rounded(p, r, 14, theme.with_alpha(theme.PANEL, 0.97), theme.BORDER)
        x, w = 16, self.W - 32
        theme.text(p, QRectF(x, 12, 80, 18), "ARGUS", theme.sans(11, QFont.DemiBold), theme.SOFT)
        label = {"open": "Market open", "pre": "Pre-market", "post": "After hours"}.get(s.session, "Stocks closed")
        lf = theme.sans(11)
        p.setFont(lf)
        lw = p.fontMetrics().horizontalAdvance(label)
        self._close_rect = QRectF(self.W - 38, 8, 28, 26)
        theme.text(p, QRectF(self._close_rect.left() - 6 - lw, 12, lw, 18), label, lf, theme.MUTED)
        theme.dot(p, QPointF(self._close_rect.left() - 14 - lw, 21), 3.5, s.market_color())
        p.setPen(theme.MUTED)
        c = self._close_rect.center()
        p.drawLine(QPointF(c.x() - 5, c.y() - 5), QPointF(c.x() + 5, c.y() + 5))
        p.drawLine(QPointF(c.x() + 5, c.y() - 5), QPointF(c.x() - 5, c.y() + 5))

        self._row_hits = []
        hero = self._headline()
        if hero is None:
            theme.text(p, QRectF(x, self.HEAD, w, 60), "Add entries in the watchlist", theme.sans(13),
                       theme.MUTED, Qt.AlignCenter)
            return
        y = self.HEAD
        sub = f"{hero.symbol} · {hero.name}" if hero.name else hero.symbol
        theme.text(p, QRectF(x, y, w, 18), theme.elided(p, sub, theme.sans(12), w), theme.sans(12), theme.MUTED)
        price_font = theme.mono(32, QFont.Medium)
        p.setFont(price_font)
        pw = p.fontMetrics().horizontalAdvance(hero.price)
        if hero.flash:
            theme.rounded(p, QRectF(x - 6, y + 20, pw + 12, 40), 6,
                          theme.with_alpha(s.up_color if hero.flash > 0 else s.down_color, 0.22))
        theme.text(p, QRectF(x, y + 18, w, 44), hero.price, price_font, theme.TEXT if hero.live else theme.SOFT)
        if hero.pct:
            theme.text(p, QRectF(x, y + 60, w, 18), f"{'▲' if hero.up else '▼'} {hero.pct.lstrip('+−')}   {hero.change}",
                       theme.mono(13), hero.color)
        theme.sparkline(p, QRectF(x, y + 84, w, 38), hero.points, hero.color, 1.8, fill=True,
                        alpha=1.0 if hero.live else 0.55)
        y += self.HERO
        p.setPen(theme.BORDER)
        p.drawLine(QPointF(0, y), QPointF(self.W, y))
        for row in s.rows():
            if row.entry.id == hero.entry.id:
                continue
            rect = QRectF(0, y, self.W, self.ROW)
            self._row_hits.append((rect, row.entry.id))
            p.save()
            p.setOpacity(1.0 if row.live else 0.6)
            theme.rounded(p, QRectF(x, y + 11, 3, 26), 1.5, row.color)
            theme.text(p, QRectF(x + 14, y + 6, 150, 20), row.symbol, theme.sans(14, QFont.DemiBold), theme.TEXT)
            theme.text(p, QRectF(x + 14, y + 25, 150, 16), theme.elided(p, row.name, theme.sans(11), 140),
                       theme.sans(11), theme.MUTED)
            if row.flash:
                pf = theme.mono(15, QFont.Medium)
                p.setFont(pf)
                fw = p.fontMetrics().horizontalAdvance(row.price)
                theme.rounded(p, QRectF(x + w - fw - 6, y + 5, fw + 10, 22), 5,
                              theme.with_alpha(s.up_color if row.flash > 0 else s.down_color, 0.22))
            theme.text(p, QRectF(x, y + 5, w, 22), row.price, theme.mono(15, QFont.Medium), theme.TEXT,
                       Qt.AlignRight | Qt.AlignVCenter)
            if row.pct:
                theme.text(p, QRectF(x, y + 25, w, 18), f"{'▲' if row.up else '▼'} {row.pct.lstrip('+−')}",
                           theme.mono(12), row.color, Qt.AlignRight | Qt.AlignVCenter)
            p.restore()
            y += self.ROW


class TickerStrip(_Overlay):
    """Full-width bar at the top or bottom of the screen; scrolls continuously, pauses on hover."""
    H, BADGE_W, FPS = 44, 150, 50
    SPEEDS = {"slow": 30, "medium": 60, "fast": 110}          # px per second
    movable = False

    def __init__(self, state: LiveState):
        super().__init__(state)
        st = QSettings()
        self.position = st.value("strip/position", "top")
        self.speed = st.value("strip/speed", "medium")
        self._offset = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self.place()

    def place(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        y = g.top() if self.position == "top" else g.bottom() - self.H + 1
        self.setGeometry(g.left(), y, g.width(), self.H)

    def showEvent(self, e) -> None:
        self._timer.start(1000 // self.FPS)
        super().showEvent(e)

    def hideEvent(self, e) -> None:
        self._timer.stop()
        super().hideEvent(e)

    def _step(self) -> None:
        if not self.geometry().contains(QCursor.pos()):          # pause while the mouse is over it
            self._offset += self.SPEEDS.get(self.speed, 60) / self.FPS
            self.update()

    def extend_menu(self, m: QMenu) -> None:
        pos = m.addMenu("Position")
        for name in ("top", "bottom"):
            a = QAction(name.title(), pos, checkable=True, checked=self.position == name)
            a.triggered.connect(lambda _=False, n=name: self._set("position", n))
            pos.addAction(a)
        spd = m.addMenu("Speed")
        for name in self.SPEEDS:
            a = QAction(name.title(), spd, checkable=True, checked=self.speed == name)
            a.triggered.connect(lambda _=False, n=name: self._set("speed", n))
            spd.addAction(a)

    def _set(self, key: str, value: str) -> None:
        setattr(self, key, value)
        QSettings().setValue(f"strip/{key}", value)
        self.place()

    def _item_width(self, p: QPainter, row: Row) -> float:
        p.setFont(theme.sans(13, QFont.DemiBold))
        w = p.fontMetrics().horizontalAdvance(row.short)
        p.setFont(theme.mono(17, QFont.Medium))
        w += p.fontMetrics().horizontalAdvance(row.price)
        p.setFont(theme.mono(13))
        w += p.fontMetrics().horizontalAdvance(f"▲ {row.pct}")
        return w + 2 * 10 + 48

    def paintEvent(self, _e) -> None:
        s = self.state
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), theme.BG)
        p.setPen(theme.BORDER)
        edge = self.H - 1 if self.position == "top" else 0
        p.drawLine(0, edge, self.width(), edge)
        rows = s.rows()
        widths = [self._item_width(p, r) for r in rows]
        total = sum(widths)
        lane = QRectF(self.BADGE_W, 0, self.width() - self.BADGE_W, self.H)
        if rows and total > 0:
            p.save()
            p.setClipRect(lane)
            x = lane.left() - (self._offset % total)
            while x < lane.right():
                for row, w in zip(rows, widths):
                    if x + w > lane.left():
                        self._item(p, QRectF(x, 0, w, self.H), row)
                    x += w
                    if x >= lane.right():
                        break
            p.restore()
        badge = QRectF(0, 0, self.BADGE_W, self.H)
        p.fillRect(badge, theme.PANEL)
        p.setPen(theme.BORDER)
        p.drawLine(QPointF(badge.right(), 0), QPointF(badge.right(), self.H))
        label = {"open": "Market open", "pre": "Pre-market", "post": "After hours"}.get(s.session, "Stocks closed")
        theme.dot(p, QPointF(18, self.H / 2), 4, s.market_color())
        theme.text(p, QRectF(30, 0, self.BADGE_W - 36, self.H), label, theme.sans(12), theme.SOFT)

    def _item(self, p: QPainter, r: QRectF, row: Row) -> None:
        s = self.state
        p.save()
        p.setOpacity(1.0 if row.live else 0.6)
        x = r.left() + 24
        sym = theme.sans(13, QFont.DemiBold)
        p.setFont(sym)
        sw = p.fontMetrics().horizontalAdvance(row.short)
        theme.text(p, QRectF(x, 0, sw + 2, self.H), row.short, sym, theme.SOFT)
        x += sw + 10
        pf = theme.mono(17, QFont.Medium)
        p.setFont(pf)
        pw = p.fontMetrics().horizontalAdvance(row.price)
        if row.flash:
            theme.rounded(p, QRectF(x - 5, self.H / 2 - 13, pw + 10, 26), 5,
                          theme.with_alpha(s.up_color if row.flash > 0 else s.down_color, 0.22))
        theme.text(p, QRectF(x, 0, pw + 2, self.H), row.price, pf, theme.TEXT)
        x += pw + 10
        if row.pct:
            theme.text(p, QRectF(x, 0, r.right() - x, self.H), f"{'▲' if row.up else '▼'} {row.pct.lstrip('+−')}",
                       theme.mono(13), row.color)
        p.setOpacity(1.0)
        p.setPen(theme.BORDER)
        p.drawLine(QPointF(r.right(), 12), QPointF(r.right(), self.H - 12))
        p.restore()
