"""Small line icons drawn as SVG (original, no icon font needed on any OS)."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_PATHS = {
    "home": '<path d="M3 11 12 4l9 7"/><path d="M5 10v10h5v-6h4v6h5V10"/>',
    "script": '<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4"/><path d="M9 12h7M9 16h7M9 8h3"/>',
    "storyboard": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 9h18M3 15h18M8 5v4M16 5v4'
                  'M8 15v4M16 15v4"/>',
    "characters": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.6 3.3-5.5 6.5-5.5s5.9 1.9 6.5 5.5"/>'
                  '<circle cx="17" cy="9" r="2.6"/><path d="M16.5 14.6c2.6 0 4.5 1.6 5 4.4"/>',
    "render": '<circle cx="12" cy="12" r="9"/><path d="M10 8.5v7l6-3.5z"/>',
    "publish": '<path d="M12 16V4M7 9l5-5 5 5"/><path d="M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4"/>',
    "settings": '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/>'
                '<circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
    "spark": '<path d="M12 3l2.2 6.8L21 12l-6.8 2.2L12 21l-2.2-6.8L3 12l6.8-2.2z"/>',
}


def icon(name: str, colour: str = "#c9d4f0", size: int = 48) -> QIcon:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{colour}" '
           f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{_PATHS[name]}</svg>')
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    QSvgRenderer(QByteArray(svg.encode())).render(p, QRectF(0, 0, size, size))
    p.end()
    return QIcon(pix)
