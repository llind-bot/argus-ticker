"""Cards and List live views (painted, inside the main window)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QFont, QPainter
from PySide6.QtWidgets import QScrollArea, QWidget

from .. import market
from ..models import CRYPTO, METAL, STOCK
from . import theme
from .state import LiveState, Row


class _Canvas(QWidget):
    """A painted view: keeps hit areas for double-click → edit."""
    activated = Signal(int)                      # entry id

    def __init__(self, state: LiveState, parent=None):
        super().__init__(parent)
        self.state = state
        self._hits: list[tuple[QRectF, int]] = []
        state.changed.connect(self._changed)
        self.setMouseTracking(True)

    def _changed(self) -> None:
        h = self.content_height(self.width())
        if h != self.minimumHeight():
            self.setMinimumHeight(h)
        self.update()

    def resizeEvent(self, e) -> None:
        self.setMinimumHeight(self.content_height(self.width()))
        super().resizeEvent(e)

    def mouseDoubleClickEvent(self, e) -> None:
        for rect, entry_id in self._hits:
            if rect.contains(e.position()):
                self.activated.emit(entry_id)
                return

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), theme.BG)
        self._hits = []
        if not self.state.entries:
            theme.text(p, QRectF(self.rect()), "Your watchlist is empty — switch to Edit to add stocks and crypto.",
                       theme.sans(14), theme.MUTED, Qt.AlignCenter)
            return
        self.draw(p)

    def content_height(self, width: int) -> int:
        raise NotImplementedError

    def draw(self, p: QPainter) -> None:
        raise NotImplementedError

    @staticmethod
    def flash_bg(p: QPainter, rect: QRectF, row: Row, state: LiveState) -> None:
        if row.flash:
            theme.rounded(p, rect, 6, theme.with_alpha(state.up_color if row.flash > 0 else state.down_color, 0.22))


class CardsView(_Canvas):
    PAD, GAP, MIN_W, H = 20, 14, 250, 152

    def _cols(self, width: int) -> int:
        return max(1, (width - 2 * self.PAD + self.GAP) // (self.MIN_W + self.GAP))

    def content_height(self, width: int) -> int:
        n = len(self.state.entries)
        rows = -(-n // self._cols(width)) if n else 1
        return 2 * self.PAD + rows * self.H + (rows - 1) * self.GAP

    def draw(self, p: QPainter) -> None:
        cols = self._cols(self.width())
        cw = (self.width() - 2 * self.PAD - (cols - 1) * self.GAP) / cols
        for i, row in enumerate(self.state.rows()):
            x = self.PAD + (i % cols) * (cw + self.GAP)
            y = self.PAD + (i // cols) * (self.H + self.GAP)
            rect = QRectF(x, y, cw, self.H)
            self._hits.append((rect, row.entry.id))
            self._card(p, rect, row)

    def _card(self, p: QPainter, r: QRectF, row: Row) -> None:
        s = self.state
        p.save()
        p.setOpacity(1.0 if row.live else 0.62)
        theme.rounded(p, r.adjusted(0.5, 0.5, -0.5, -0.5), 12, theme.PANEL, theme.BORDER)
        x, w = r.left() + 16, r.width() - 32
        tag = "CRYPTO" if row.entry.kind == CRYPTO else (("METAL" if row.entry.kind == METAL else "STOCK")
                                                          if row.live else "CLOSED")
        theme.text(p, QRectF(x, r.top() + 12, w, 20), tag, theme.sans(10, QFont.DemiBold), theme.MUTED,
                   Qt.AlignRight | Qt.AlignVCenter)
        sym_font = theme.sans(15, QFont.DemiBold)
        p.setFont(sym_font)
        sym_w = p.fontMetrics().horizontalAdvance(row.symbol)
        theme.text(p, QRectF(x, r.top() + 12, w, 20), row.symbol, sym_font, theme.TEXT)
        if row.name:
            theme.text(p, QRectF(x + sym_w + 8, r.top() + 13, w - sym_w - 70, 20),
                       theme.elided(p, row.name, theme.sans(12), w - sym_w - 70), theme.sans(12), theme.MUTED)
        price_font = theme.mono(26, QFont.Medium)
        p.setFont(price_font)
        pw = p.fontMetrics().horizontalAdvance(row.price)
        price_rect = QRectF(x, r.top() + 38, w, 36)
        self.flash_bg(p, QRectF(x - 6, price_rect.top() + 2, pw + 12, 32), row, s)
        theme.text(p, price_rect, row.price, price_font, theme.TEXT)
        if row.has_quote and row.up is not None:
            arrow = "▲" if row.up else "▼"
            pct = row.pct.lstrip("+−")
            chg_font = theme.mono(13)
            p.setFont(chg_font)
            first = f"{arrow} {pct}"
            fw = p.fontMetrics().horizontalAdvance(first)
            theme.text(p, QRectF(x, r.top() + 76, w, 20), first, chg_font, row.color)
            theme.text(p, QRectF(x + fw + 10, r.top() + 76, w - fw - 10, 20), row.change, chg_font, theme.MUTED)
        theme.sparkline(p, QRectF(x, r.top() + 104, w, 34), row.points, row.color, fill=True)
        p.restore()


class ListView(_Canvas):
    PAD_X, HEAD, ROW = 28, 40, 60

    def _groups(self) -> list[tuple[str, object, list[Row]]]:
        s = self.state
        out = []
        crypto, metals, stocks = s.rows(CRYPTO), s.rows(METAL), s.rows(STOCK)
        if crypto:
            out.append(("CRYPTO · LIVE", s.up_color, crypto))
        if metals:
            out.append((f"METALS · SPOT · {market.metals_label().replace('Metals ', '').upper()}",
                        s.up_color if s.metals_live else theme.CLOSED, metals))
        if stocks:
            out.append((f"STOCKS · {s.market_label().upper()}", s.market_color(), stocks))
        return out

    def content_height(self, width: int) -> int:
        return 16 + sum(self.HEAD + len(rows) * self.ROW for _, _, rows in self._groups()) + 16

    def draw(self, p: QPainter) -> None:
        s = self.state
        x0, x1 = self.PAD_X, self.width() - self.PAD_X
        y = 16
        for title, color, rows in self._groups():
            theme.dot(p, QPointF(x0 + 4, y + self.HEAD - 15), 3.5, color)
            theme.text(p, QRectF(x0 + 16, y + self.HEAD - 26, x1 - x0, 22), title,
                       theme.sans(11, QFont.DemiBold), theme.MUTED)
            y += self.HEAD
            for row in rows:
                r = QRectF(x0, y, x1 - x0, self.ROW)
                self._hits.append((r, row.entry.id))
                p.setPen(theme.PANEL_HI)
                p.drawLine(QPointF(x0, y), QPointF(x1, y))
                self._row(p, r, row)
                y += self.ROW

    def _row(self, p: QPainter, r: QRectF, row: Row) -> None:
        s = self.state
        name_w, price_w, pill_w, gap = 190, 170, 92, 20
        theme.text(p, QRectF(r.left(), r.top() + 10, name_w, 22), row.symbol, theme.sans(15, QFont.DemiBold),
                   theme.TEXT if row.live else theme.SOFT)
        theme.text(p, QRectF(r.left(), r.top() + 31, name_w, 18),
                   theme.elided(p, row.name or {CRYPTO: "Crypto", METAL: "Spot · per oz"}.get(row.entry.kind, "Stock"),
                                theme.sans(12), name_w),
                   theme.sans(12), theme.MUTED)
        pill = QRectF(r.right() - pill_w, r.center().y() - 14, pill_w, 28)
        price = QRectF(pill.left() - gap - price_w, r.top(), price_w, r.height())
        spark = QRectF(r.left() + name_w + gap, r.top() + 14, price.left() - gap - (r.left() + name_w + gap), r.height() - 28)
        if spark.width() > 60:
            theme.sparkline(p, spark, row.points, row.color, 1.5, alpha=1.0 if row.live else 0.5)
        price_font = theme.mono(18, QFont.Medium)
        p.setFont(price_font)
        pw = p.fontMetrics().horizontalAdvance(row.price)
        self.flash_bg(p, QRectF(price.right() - pw - 8, price.center().y() - 14, pw + 16, 28), row, s)
        theme.text(p, price, row.price, price_font, theme.TEXT if row.live else theme.SOFT, Qt.AlignRight | Qt.AlignVCenter)
        if row.has_quote and row.pct:
            fill = row.color if row.live else theme.CLOSED
            theme.rounded(p, pill, 6, fill)
            theme.text(p, pill, row.pct, theme.mono(13, QFont.DemiBold), theme.BG, Qt.AlignCenter)


def scrolling(view: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidget(view)
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setStyleSheet("QScrollArea { background: #0B0F14; }")
    return area
