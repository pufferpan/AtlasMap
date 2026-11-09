"""A timed neon engine card that slides from the screen's upper corner."""
import math
from PySide6.QtCore import QPoint, QRectF, Qt, QVariantAnimation, QLineF
from PySide6.QtGui import QColor, QFont, QGuiApplication, QLinearGradient, QPainter, QPen, QPainterPath
from PySide6.QtWidgets import QWidget

EFFECT_MS=3100

class PerformanceEffect(QWidget):
    def __init__(self,parent,count):
        super().__init__(parent,Qt.Tool|Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint|Qt.WindowDoesNotAcceptFocus)
        self.count=count;self.progress=0
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_DeleteOnClose)
        screen=parent.screen() or QGuiApplication.primaryScreen()
        area=screen.availableGeometry()
        self.resize(min(260,area.width()-24),min(306,area.height()-24))
        self.anchor=QPoint(area.right()-self.width()-15,area.top()+16)
        self.animation=QVariantAnimation(self)
        self.animation.setStartValue(0.0);self.animation.setEndValue(1.0)
        self.animation.setDuration(EFFECT_MS)
        self.animation.valueChanged.connect(self._frame)
        self.animation.finished.connect(self.close)

    def start(self):
        self._frame(0);self.show();self.raise_();self.animation.start()

    def _frame(self,value):
        self.progress=float(value)
        entry=min(1,self.progress/.16)
        entry=1-(1-entry)**3
        leave=max(0,(self.progress-.86)/.14)
        self.move(self.anchor+QPoint(0,round(-self.height()*(1-entry)-24*leave*leave)))
        self.setWindowOpacity(min(1,entry*2)*(1-leave))
        self.update()

    def mousePressEvent(self,event):
        self.close()

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.Antialiasing)
        p.scale(self.width()/260,self.height()/306)
        rect=QRectF(15,12,230,279)
        body=QPainterPath();body.addRoundedRect(rect,43,43)
        for width,alpha in ((18,9),(11,20),(6,48),(2.2,255)):
            p.setPen(QPen(QColor(255,33,105,alpha),width));p.drawPath(body)
        fill=QLinearGradient(0,12,245,291)
        fill.setColorAt(0,QColor(82,61,58,248));fill.setColorAt(.48,QColor(44,28,35,248));fill.setColorAt(1,QColor(94,60,49,248))
        p.fillPath(body,fill);p.setPen(QPen(QColor('#ff5c87'),1.4));p.drawPath(body)
        def text(y,h,size,color,value,bold=False):
            font=QFont('Microsoft YaHei UI');font.setPixelSize(size);font.setBold(bold)
            p.setFont(font);p.setPen(QColor(color));p.drawText(QRectF(18,y,224,h),Qt.AlignCenter,value)
        text(18,29,13,'#fff0de','ATLASMAP  TURBO',True)
        # Mechanical wings and turbine, matching the reference's neon silhouette.
        p.setBrush(QColor(255,30,85,28));p.setPen(QPen(QColor('#ff627c'),2))
        p.drawRoundedRect(QRectF(40,104,180,40),10,10)
        p.setBrush(QColor('#442632'));p.drawEllipse(QRectF(81,77,98,98))
        for r,color,width in ((49,'#ff536e',3),(42,'#fa3261',2),(33,'#ffaf61',4),(23,'#ab3354',2)):
            p.setPen(QPen(QColor(color),width));p.setBrush(Qt.NoBrush);p.drawEllipse(QRectF(130-r,126-r,2*r,2*r))
        for i in range(40):
            angle=i*math.tau/40+self.progress*math.tau*.6
            p.setPen(QPen(QColor('#ff9764') if i%3 else QColor('#ff3068'),2))
            p.drawLine(QLineF(130+36*math.cos(angle),126+36*math.sin(angle),130+41*math.cos(angle),126+41*math.sin(angle)))
        p.setPen(QPen(QColor('#ff376b'),3));p.drawEllipse(QRectF(122,118,16,16))
        for x in (46,208):
            p.setPen(QPen(QColor('#ffe3d1'),2));p.drawRoundedRect(QRectF(x,115,6,18),2,2)
        text(187,38,23,'#ff5d92','性能模式已开启',True)
        text(224,25,12,'#ffe1c4',f'{self.count} 个分块 · 全流程并行')
        line=QLinearGradient(35,0,225,0);line.setColorAt(0,QColor(255,101,112,0));line.setColorAt(.5,QColor('#ffb65c'));line.setColorAt(1,QColor(255,101,112,0))
        p.fillRect(QRectF(35,254,190,2),line)
        text(261,20,10,'#ffc3ae','导出加速中 · 点击关闭提示')
        p.end()


def show_performance_effect(parent,count):
    previous=getattr(parent,'_performance_effect',None)
    if previous is not None:previous.close()
    effect=PerformanceEffect(parent,count);parent._performance_effect=effect
    def clear():
        if getattr(parent,'_performance_effect',None) is effect:parent._performance_effect=None
    effect.destroyed.connect(clear);effect.start()
    return effect
