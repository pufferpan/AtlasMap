"""Bounded failure evidence, shared by subprocesses, parallel workers and the UI."""
from collections import deque
from dataclasses import dataclass,asdict,replace
import json
import re
import threading
from pathlib import Path

MARKER='@ATLASMAP_FAILURE '


@dataclass
class ExportFailure:
    kind:str
    title:str
    reason:str
    advice:str
    stage:str=''
    worker:int|None=None
    exit_code:int=1
    evidence:str=''
    log_path:str=''

    def text(self):
        location=self.stage or '导出任务'
        if self.worker is not None and not re.search(r'\d+/\d+',location): location=f'分块 {self.worker} · '+location
        parts=[f'失败位置：{location}',f'原因：{self.reason}',f'建议：{self.advice}']
        if self.evidence:parts.append('错误原文：'+self.evidence)
        parts.append(f'退出码：{self.exit_code}')
        if self.log_path:parts.append('完整日志：'+self.log_path)
        return '\n'.join(parts)

    def event(self):return MARKER+json.dumps(asdict(self),ensure_ascii=False)


def classify(text):
    lower=text.lower()
    if any(s in lower for s in ('memoryerror','out of memory','outofmemoryexception','ran out of memory',
            'malloc returns null','bad_alloc','bad allocation','页面文件太小','内存不足','内存资源不足',
            'not enough memory resources','insufficient system resources','map_memory_full',
            '0x80070008','0x8007000e','0x800705aa','0x800705af','[errno 12]','[winerror 1455]')):
        return (100,'memory','内存或虚拟内存不足','导出进程无法分配所需内存，当前分块未能完成。',
                '关闭占内存的软件，检查 Windows 虚拟内存；降低同时导出的进程数，或增加分块数量以减小单块负载。')
    if any(s in lower for s in ('no space left on device','磁盘空间不足','not enough space on the disk',
            'map_disk_full','disk full','0x80070070','[errno 28]','[winerror 112]')):
        return (100,'disk','磁盘空间不足','导出盘或工作盘没有足够空间保存本次结果。',
                '为错误路径所在磁盘释放空间，或把工作目录和导出工程移到空间充足的磁盘。')
    if any(s in lower for s in ('permissionerror','permission denied','access is denied','拒绝访问','[winerror 5]','[errno 13]')):
        return (90,'permission','文件无法写入或被占用','导出进程没有读写目标文件的权限，或文件被其他程序占用。',
                '关闭占用该工程的 Blender、虚幻或同步软件，并选择当前用户可写的目录。')
    if any(s in lower for s in ('filename too long','路径太长','[winerror 206]','[errno 36]')):
        return (90,'path','文件路径过长','当前工具无法访问这个长度的文件路径。','把导出目录移到较短的路径，例如 I:\\AtlasMaps；保留完整日志中的出错路径。')
    if any(s in lower for s in ('modulenotfounderror','dll load failed','无法加载 dll','could not load file or assembly')):
        return (85,'dependency','导出组件或依赖无法加载','运行所需的脚本模块、DLL 或运行时不可用。','使用完整新版软件，检查 Blender、虚幻及运行时安装，勿只复制便携目录中的主程序。')
    if any(s in lower for s in ('filenotfounderror','no such file or directory','[缺少脚本]','[缺少输入]','[winerror 2]')):
        return (80,'missing','所需文件不存在','输入模型、贴图、脚本或导出工具在指定路径不存在。','按错误原文核对路径；还原缺失文件，或重新导出缺失的上一步数据。')
    if any(s in lower for s in ('[输出校验失败]','未生成有效数据','没有可用实例','没有可用的 split','没有生成本次完成报告','目标关卡不匹配','steps did not complete')):
        return (75,'validation','导出结果未通过校验','当前步骤的输出缺失、不完整或与所选地图不匹配。','查看错误原文指出的文件和地图；重新执行失败步骤，避免使用旧导出结果。')
    if any(s in lower for s in ('jsondecodeerror','invalid json','文件损坏','unexpected end of file')):
        return (70,'data','中间数据损坏或不完整','读取模型、材质或清单时发现不完整的数据。','保留日志，重新生成错误路径对应的数据；不要混用不同次导出的文件。')
    return None


class FailureTracker:
    def __init__(self,stage=''):
        self.stage=stage;self.worker=None
        self._tail=deque(maxlen=12);self._candidate=None;self._reported=None
        self._lock=threading.RLock()

    def observe(self,line):
        with self._lock:self._observe(str(line))

    def _observe(self,line):
        if line.startswith('[公共] '):line=line[len('[公共] '):]
        # Nested worker messages retain their own stage and one-based block ID.
        if line.startswith('@ATLASMAP_PARALLEL '):
            try:
                event=json.loads(line[len('@ATLASMAP_PARALLEL '):])
                child=FailureTracker(str(event.get('stage') or self.stage))
                child.worker=int(event['worker'])+1
                child._observe(event.get('text',''))
                if child._reported:self._reported=replace(child._reported,worker=child.worker,stage=child.stage)
                if child._candidate and (self._candidate is None or child._candidate[0]>=self._candidate[0]):
                    self._candidate=child._candidate
                if child._tail:self._tail.extend(child._tail)
            except (ValueError,TypeError,KeyError):pass
            return
        if line.startswith(MARKER):
            try:
                data=json.loads(line[len(MARKER):])
                report=ExportFailure(**data)
                if report.exit_code not in (0,-2,130):self._reported=report
            except (ValueError,TypeError):pass
            return
        if line.startswith('═══ 步骤 '):
            match=re.search(r'：(.+?)\s*═*$',line)
            if match:self.stage=match[1].rstrip(' ═')
            self._candidate=None;self._tail.clear();self._reported=None
        if line.strip():self._tail.append(line[-1600:])
        candidate=classify(line)
        if candidate and (self._candidate is None or candidate[0]>=self._candidate[0]):
            self._candidate=(*candidate,line.strip()[-800:],self.stage,self.worker)

    def finish(self,code,log_path=''):
        if code in (0,-2,130):return None
        with self._lock:
            if self._reported:return replace(self._reported,exit_code=code,log_path=log_path or self._reported.log_path)
            if self._candidate:
                _,kind,title,reason,advice,evidence,stage,worker=self._candidate
            else:
                kind,title='process','导出子进程异常退出'
                reason='导出步骤发生错误，尚未识别到足够明确的具体原因。'
                advice='复制本页错误详情或导出完整日志，按原始错误排查；请保留现有工程。'
                useful=[line for line in self._tail if not line.startswith(('@ATLASMAP_','── 步骤','[残留清理]'))]
                errors=[line for line in useful if re.search(r'error|exception|失败|错误|fatal',line,re.I)]
                evidence='\n'.join((errors or useful)[-3:])[-1200:]
                stage,worker=self.stage,self.worker
            return ExportFailure(kind,title,reason,advice,stage,worker,code,evidence,log_path)


def latest_failure(directory):
    """Read only the tail of the latest completed task, including older releases."""
    try:
        files=list(Path(directory).glob('AtlasMap-*.txt'))
        if not files:return None
        path=max(files,key=lambda p:p.stat().st_mtime_ns)
        with path.open('rb') as stream:
            start=max(0,path.stat().st_size-65536)
            stream.seek(start)
            if start:stream.readline()
            tail=stream.read().decode('utf-8-sig',errors='replace')
        end=re.findall(r'\[任务结束\] 退出码 (-?\d+)',tail)
        if not end:return None
        code=int(end[-1])
        tracker=FailureTracker('上次导出')
        for line in tail.splitlines():
            tracker.observe(re.sub(r'^\[\d{2}:\d{2}:\d{2}(?:\.\d+)?\]\s*','',line))
        return tracker.finish(code,str(path))
    except (OSError,ValueError):return None
