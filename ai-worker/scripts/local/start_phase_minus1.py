"""Start Phase -1 backends using the active index's dataset and checkpoint.

Run from any directory with the project's virtualenv Python. Processes are hidden
on Windows and persist after this launcher exits; logs and PIDs go to tmp/.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
from ai_worker.paths import REPOSITORY_ROOT


def main():
    root=REPOSITORY_ROOT
    worker=root/'ai-worker'
    meta=json.loads((worker/'vector_db/index_meta.json').read_text(encoding='utf-8'))
    images=Path(os.environ.get('IMG_BASE_DIR',meta['image_root']))
    if not images.is_dir(): raise FileNotFoundError(images)
    for port in (8001,8080):
        with socket.socket() as probe:
            try:probe.bind(('127.0.0.1',port))
            except OSError:raise RuntimeError(f'Port {port} is already in use. Stop the existing project service first.')
    logs=root/'tmp'; logs.mkdir(exist_ok=True)
    binary=logs/('phase-local-gateway.exe' if os.name=='nt' else 'phase-local-gateway')
    subprocess.run(['go','build','-o',str(binary),'./cmd/server'],cwd=root/'core-api',check=True)
    env={**os.environ,'IMG_BASE_DIR':str(images),'VECTOR_DB_DIR':str(worker/'vector_db'),
         'CHECKPOINT_PATH':str(worker/meta['checkpoint_path']),
         'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1',
         'OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','INFER_API_URL':'http://127.0.0.1:8001','PORT':'8080'}
    started=[]
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    try:
        for name,cmd,cwd in [
            ('inference',[sys.executable,'-m','uvicorn','ai_worker.api.server:app','--host','127.0.0.1','--port','8001'],worker),
            ('gateway',[str(binary)],root/'core-api')]:
            with (logs/f'{name}-local.log').open('w') as log:
                process=subprocess.Popen(cmd,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
            started.append(process)
        for _ in range(120):
            if any(p.poll() is not None for p in started):raise RuntimeError('Service exited; inspect tmp/*-local.log')
            try:
                with urllib.request.urlopen('http://127.0.0.1:8080/api/search/config',timeout=2) as response:
                    config=json.load(response)
                if config['active_index_version']==meta['index_version']:break
            except (OSError,ValueError):pass
            time.sleep(1)
        else:raise TimeoutError('Services did not become ready')
        (logs/'phase-minus1-services.json').write_text(json.dumps({'inference_pid':started[0].pid,'gateway_pid':started[1].pid,'index_version':meta['index_version'],'image_root':str(images)},indent=2))
        print(json.dumps(config,indent=2))
        print('Ready: inference :8001, gateway :8080. Start frontend separately with pnpm dev.')
    except BaseException:
        for p in started:
            p.terminate()
        raise


if __name__=='__main__':main()
