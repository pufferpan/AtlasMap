"""End only owned process trees, without blocking the Qt thread."""
import os
import subprocess
import threading


def terminate_processes(processes,on_error=None):
    processes=list({proc.pid:proc for proc in processes if proc is not None and proc.poll() is None}.values())
    if not processes:return None
    def run():
        alive=[proc for proc in processes if proc.poll() is None]
        if os.name=='nt' and alive:
            args=['taskkill','/F','/T']
            for proc in alive:args.extend(['/PID',str(proc.pid)])
            try:
                subprocess.run(args,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                               creationflags=0x08000000,timeout=8)
            except (OSError,subprocess.TimeoutExpired):pass
        for proc in alive:
            if proc.poll() is None:
                try:proc.kill()
                except OSError as exc:
                    if on_error:on_error(f'无法终止本次导出进程 {proc.pid}：{exc}')
    thread=threading.Thread(target=run,name='atlasmap-stop-processes',daemon=False)
    thread.start()
    return thread
