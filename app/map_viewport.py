"""Interactive geometry canvas; FluentPy has no 3D rendering surface."""
import ctypes
import math
import numpy as np
from PySide6.QtCore import Qt,Signal
from PySide6.QtGui import QColor,QMatrix4x4,QOpenGLContext,QPainter,QPolygonF,QVector3D
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication,QWidget
from PySide6.QtOpenGLWidgets import QOpenGLWidget

COLORS={'queued':(.42,.51,.63),'running':(1,.62,.18),'finished':(.18,.78,.53),
        'failed':(.94,.28,.31),'stopped':(.5,.5,.54)}


class Navigation:
    def navigation_init(self):
        self.chunks={};self.states={};self.selected=-1
        self.origin=np.zeros(3);self.pan=np.zeros(3)
        self.yaw=-45.;self.pitch=50.;self.distance=10.;self.radius=4.;self.drag=None
        self.setMinimumSize(620,380)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_chunk(self,index,vertices):
        first=not self.chunks
        self.chunks[index]=vertices
        if first:self.fit()
        self.update()

    def set_states(self,states):
        if self.states!=states:self.states=dict(states);self.update()
    def select_chunk(self,index):self.selected=index;self.fit();self.update()

    def fit(self):
        arrays=[v[:,:3] for i,v in self.chunks.items() if len(v) and self.selected in (-1,i)]
        if arrays:
            lo=np.min([v.min(axis=0) for v in arrays],axis=0)
            hi=np.max([v.max(axis=0) for v in arrays],axis=0)
            self.origin=(lo+hi)/2
            self.radius=max(float(np.linalg.norm(hi-lo))/2,1)
            self.distance=self.radius*2.6
        self.pan=np.zeros(3);self.update()

    def matrix(self):
        yaw,pitch=np.radians([self.yaw,self.pitch])
        eye=self.pan+np.array((math.cos(yaw)*math.cos(pitch),math.sin(yaw)*math.cos(pitch),math.sin(pitch)))*self.distance
        view=QMatrix4x4();view.lookAt(QVector3D(*eye),QVector3D(*self.pan),QVector3D(0,0,1))
        projection=QMatrix4x4()
        projection.perspective(45.,max(1,self.width())/max(1,self.height()),max(.005,self.distance/10000),self.distance+self.radius*30)
        return projection*view

    def mousePressEvent(self,event):
        self.drag=(event.position(),event.button());self.setFocus()

    def mouseMoveEvent(self,event):
        if self.drag is None:return
        old,button=self.drag;delta=event.position()-old;self.drag=(event.position(),button)
        if button==Qt.LeftButton:
            self.yaw-=delta.x()*.4;self.pitch=float(np.clip(self.pitch+delta.y()*.3,-85,85))
        else:
            yaw=math.radians(self.yaw);scale=self.distance/max(1,self.height())
            self.pan+=np.array((-math.sin(yaw)*delta.x(),math.cos(yaw)*delta.x(),delta.y()))*scale
        self.update()

    def mouseReleaseEvent(self,event):self.drag=None
    def wheelEvent(self,event):
        self.distance=float(np.clip(self.distance*math.exp(-event.angleDelta().y()/1000),self.radius*.04,self.radius*100))
        self.update();event.accept()
    def mouseDoubleClickEvent(self,event):self.fit()


class SoftwareViewport(Navigation,QWidget):
    def __init__(self,parent=None):
        super().__init__(parent);self.navigation_init()

    def paintEvent(self,event):
        painter=QPainter(self);painter.fillRect(self.rect(),QColor('#111c2b'))
        painter.setRenderHint(QPainter.Antialiasing)
        faces=[]
        transform=np.asarray(self.matrix().data()).reshape(4,4).T
        for index,data in self.chunks.items():
            if not len(data) or self.selected not in (-1,index):continue
            step=max(1,len(data)//3//max(1,5000//max(1,len(self.chunks))))
            sample=data.reshape(-1,3,9)[::step]
            xyz=sample[:,:,:3].reshape(-1,3)-self.origin
            clip=np.column_stack((xyz,np.ones(len(xyz))))@transform.T
            screen=(clip[:,:3]/np.maximum(clip[:,3,None],1e-8)).reshape(-1,3,3)
            tint=np.asarray(COLORS.get(self.states.get(index,'queued'),COLORS['queued']))
            colors=sample[:,0,6:9]*.5+tint*.5
            light=.4+.6*np.abs(sample[:,0,3:6]@np.array((.3,-.4,.866)))
            for points,color in zip(screen,np.clip(colors*light[:,None],0,1)):
                if not np.isfinite(points).all() or np.any(np.abs(points[:,:2])>20):continue
                faces.append((points[:,2].mean(),points,color))
        painter.setPen(Qt.NoPen)
        for _,points,color in sorted(faces,key=lambda row:-row[0]):
            painter.setBrush(QColor.fromRgbF(*color))
            painter.drawPolygon(QPolygonF([QPointF((v[0]+1)*self.width()/2,(1-v[1])*self.height()/2) for v in points]))
        if not faces:
            painter.setPen(QColor('#9dadc4'));painter.drawText(self.rect(),Qt.AlignCenter,'地图数据准备中…\n模型生成后会逐步显示')


class GLViewport(Navigation,QOpenGLWidget):
    failed=Signal(str)
    def __init__(self,parent=None):
        super().__init__(parent);self.navigation_init();self.buffers={};self.dirty=set();self.program=None

    def set_chunk(self,index,vertices):
        super().set_chunk(index,vertices);self.dirty.add(index)

    def initializeGL(self):
        try:
            from OpenGL import GL
            from OpenGL.GL.shaders import compileProgram,compileShader
            self.gl=GL
            vertex='''#version 120
attribute vec3 position; attribute vec3 normal; attribute vec3 color;
uniform mat4 mvp; uniform vec3 origin; varying vec3 n; varying vec3 c;
void main(){gl_Position=mvp*vec4(position-origin,1.0);n=normal;c=color;}'''
            fragment='''#version 120
varying vec3 n; varying vec3 c; uniform vec3 tint;
void main(){float light=.38+.62*abs(dot(normalize(n),normalize(vec3(.3,-.4,.866))));
gl_FragColor=vec4(mix(c,tint,.48)*light,1.0);}'''
            self.program=compileProgram(compileShader(vertex,GL.GL_VERTEX_SHADER),compileShader(fragment,GL.GL_FRAGMENT_SHADER))
            GL.glEnable(GL.GL_DEPTH_TEST);GL.glDisable(GL.GL_CULL_FACE)
            GL.glClearColor(.067,.11,.17,1.)
            self.context().aboutToBeDestroyed.connect(self.release)
        except Exception as exc:self.failed.emit(str(exc))

    def paintGL(self):
        if self.program is None:return
        gl=self.gl;gl.glClear(gl.GL_COLOR_BUFFER_BIT|gl.GL_DEPTH_BUFFER_BIT)
        gl.glUseProgram(self.program)
        gl.glUniformMatrix4fv(gl.glGetUniformLocation(self.program,'mvp'),1,False,np.asarray(self.matrix().data(),np.float32))
        gl.glUniform3f(gl.glGetUniformLocation(self.program,'origin'),*self.origin)
        locations=[gl.glGetAttribLocation(self.program,name) for name in ('position','normal','color')]
        for index in self.dirty:
            if index not in self.buffers:self.buffers[index]=gl.glGenBuffers(1)
            buffer=self.buffers[index]
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER,buffer)
            data=np.ascontiguousarray(self.chunks[index],np.float32)
            gl.glBufferData(gl.GL_ARRAY_BUFFER,data.nbytes,data,gl.GL_STATIC_DRAW)
        self.dirty.clear()
        for index,buffer in self.buffers.items():
            if self.selected not in (-1,index):continue
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER,buffer)
            for slot,location in enumerate(locations):
                gl.glEnableVertexAttribArray(location)
                gl.glVertexAttribPointer(location,3,gl.GL_FLOAT,False,36,ctypes.c_void_p(slot*12))
            gl.glUniform3f(gl.glGetUniformLocation(self.program,'tint'),*COLORS.get(self.states.get(index,'queued'),COLORS['queued']))
            gl.glDrawArrays(gl.GL_TRIANGLES,0,len(self.chunks[index]))
        for location in locations:gl.glDisableVertexAttribArray(location)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER,0);gl.glUseProgram(0)

    def release(self):
        if self.program is None:return
        self.makeCurrent()
        for buffer in self.buffers.values():self.gl.glDeleteBuffers(1,[buffer])
        self.gl.glDeleteProgram(self.program);self.buffers.clear();self.program=None
        self.doneCurrent()


def viewport(parent=None):
    app=QApplication.instance()
    if app.platformName() not in ('offscreen','minimal'):
        context=QOpenGLContext()
        if context.create():return GLViewport(parent)
    return SoftwareViewport(parent)
