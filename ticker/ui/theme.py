"""Dark theme: colors, fonts and the painting helpers the live views share."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QApplication

BG = QColor("#0B0F14")
PANEL = QColor("#121821")
PANEL_HI = QColor("#161D27")
BORDER = QColor("#1C2430")
TEXT = QColor("#E6EDF3")
SOFT = QColor("#A7B3BF")
MUTED = QColor("#8B98A5")
CLOSED = QColor("#6B7785")
PRE_POST = QColor("#D97706")

SCHEMES = {                      # name → (up, down); blue/orange reads for red-green colorblindness
    "green-red": (QColor("#3FB950"), QColor("#F85149")),
    "blue-orange": (QColor("#4C9AFF"), QColor("#F59E0B")),
}
SCHEME_LABELS = {"green-red": "Green / red", "blue-orange": "Blue / orange (colorblind-friendly)"}

_SANS = ["Segoe UI Variable Text", "Segoe UI", "SF Pro Text", "Helvetica Neue", "Arial"]
_MONO = ["Cascadia Mono", "Consolas", "SF Mono", "Menlo", "Courier New"]


def sans(px: int, weight: QFont.Weight = QFont.Normal) -> QFont:
    f = QFont()
    f.setFamilies(_SANS)
    f.setPixelSize(px)
    f.setWeight(weight)
    return f


def mono(px: int, weight: QFont.Weight = QFont.Normal) -> QFont:
    f = QFont()
    f.setFamilies(_MONO)
    f.setPixelSize(px)
    f.setWeight(weight)
    f.setStyleHint(QFont.Monospace)
    return f


def apply_dark_palette(app: QApplication) -> None:
    """Fusion + dark palette so dialogs, menus and the edit table match the live views."""
    app.setStyle("Fusion")
    pal = QPalette()
    for role, color in ((QPalette.Window, PANEL), (QPalette.WindowText, TEXT), (QPalette.Base, BG),
                        (QPalette.AlternateBase, PANEL), (QPalette.Text, TEXT), (QPalette.Button, PANEL_HI),
                        (QPalette.ButtonText, TEXT), (QPalette.ToolTipBase, PANEL_HI), (QPalette.ToolTipText, TEXT),
                        (QPalette.Highlight, QColor("#2F4B6E")), (QPalette.HighlightedText, TEXT),
                        (QPalette.PlaceholderText, MUTED), (QPalette.Link, QColor("#4C9AFF"))):
        pal.setColor(role, color)
    pal.setColor(QPalette.Disabled, QPalette.Text, MUTED)
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, MUTED)
    pal.setColor(QPalette.Disabled, QPalette.WindowText, MUTED)
    app.setPalette(pal)


def with_alpha(c: QColor, a: float) -> QColor:
    out = QColor(c)
    out.setAlphaF(a)
    return out


def sparkline(p: QPainter, rect: QRectF, values: list[float], color: QColor, width: float = 1.6,
              fill: bool = False, alpha: float = 1.0) -> None:
    """Trend line scaled into ``rect``; optional soft fill under it."""
    if len(values) < 2:
        return
    lo, hi = min(values), max(values)
    span = (hi - lo) or abs(hi) * 0.001 or 1.0
    n = len(values) - 1
    pts = [QPointF(rect.left() + rect.width() * i / n,
                   rect.bottom() - (v - lo) / span * rect.height()) for i, v in enumerate(values)]
    path = QPainterPath(pts[0])
    for pt in pts[1:]:
        path.lineTo(pt)
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    if fill:
        area = QPainterPath(path)
        area.lineTo(rect.right(), rect.bottom())
        area.lineTo(rect.left(), rect.bottom())
        area.closeSubpath()
        p.fillPath(area, with_alpha(color, 0.12 * alpha))
    pen = QPen(with_alpha(color, alpha), width)
    pen.setJoinStyle(Qt.RoundJoin)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.drawPath(path)
    p.restore()


def text(p: QPainter, rect: QRectF, s: str, font: QFont, color: QColor,
         align: Qt.AlignmentFlag = Qt.AlignLeft | Qt.AlignVCenter) -> None:
    p.setFont(font)
    p.setPen(color)
    p.drawText(rect, int(align), s)


def elided(p: QPainter, s: str, font: QFont, width: float) -> str:
    p.setFont(font)
    return p.fontMetrics().elidedText(s, Qt.ElideRight, int(width))


def rounded(p: QPainter, rect: QRectF, radius: float, fill: QColor, border: Optional[QColor] = None) -> None:
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(border, 1) if border else Qt.NoPen)
    p.setBrush(fill)
    p.drawRoundedRect(rect, radius, radius)
    p.restore()


def dot(p: QPainter, center: QPointF, r: float, color: QColor) -> None:
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawEllipse(center, r, r)
    p.restore()
