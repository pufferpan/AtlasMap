"""Green completion artwork displayed within each original worker window."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient


SUCCESS_MS=120


def success_artwork(size,count,elapsed,dpr=1):
    pixmap=QPixmap(round(size.width()*dpr),round(size.height()*dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.transparent)
    painter=QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    w,h=size.width(),size.height()
    card=QPainterPath();card.addRoundedRect(QRectF(0,0,w,h),24,24)
    painter.setClipPath(card)
    painter.fillRect(QRectF(0,0,w,h),QColor('#042a1b'))
    glow=QRadialGradient(w*.5,h*.48,w*.58)
    glow.setColorAt(0,QColor('#16894f'));glow.setColorAt(.65,QColor('#075335'));glow.setColorAt(1,QColor('#021c13'))
    painter.fillRect(QRectF(0,0,w,h),glow)
    painter.setPen(QPen(QColor(107,255,167,15),1))
    for x in range(0,w,32):painter.drawLine(x,0,x,h)
    for y in range(0,h,32):painter.drawLine(0,y,w,y)
    font=QFont('Microsoft YaHei UI');font.setPixelSize(18);font.setBold(True)
    painter.setFont(font);painter.setPen(QColor('#9dffc3'))
    painter.drawText(QRectF(0,26,w,32),Qt.AlignCenter,'全流程导出完成')
    font.setPixelSize(min(int(h*.46),int(w*.27)))
    metrics=QFontMetricsF(font)
    text='成功';path=QPainterPath()
    path.addText((w-metrics.horizontalAdvance(text))/2,h*.57,font,text)
    painter.setBrush(Qt.NoBrush)
    for stroke,alpha in ((22,14),(12,26),(4,65)):
        painter.setPen(QPen(QColor(120,255,175,alpha),stroke));painter.drawPath(path)
    painter.fillPath(path,QColor('#d4ffe4'))
    font.setBold(False);font.setPixelSize(max(10,min(15,w//31)));painter.setFont(font)
    painter.setPen(QColor('#bcf8d1'))
    minutes,seconds=divmod(int(elapsed),60)
    painter.drawText(QRectF(0,h-98,w,28),Qt.AlignCenter,f'{count} 个分块全部校验并保存  ·  用时 {minutes} 分 {seconds} 秒')
    painter.setPen(QColor('#74bd96'));font.setPixelSize(13);painter.setFont(font)
    painter.drawText(QRectF(0,h-65,w,28),Qt.AlignCenter,'点击任意窗口查看日志  ·  Esc 关闭')
    painter.setClipping(False);painter.setBrush(Qt.NoBrush)
    painter.setPen(QPen(QColor(138,255,182,130),1.5))
    painter.drawRoundedRect(QRectF(1,1,w-2,h-2),24,24)
    painter.end()
    return pixmap
