import os,sys,time,subprocess,tempfile,json,socket
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import requests
from ai_worker.paths import REPOSITORY_ROOT

def main():
    root=REPOSITORY_ROOT
    worker=root/'ai-worker'; core=root/'core-api'
    meta=json.loads((worker/'vector_db/index_meta.json').read_text())
    images=Path(os.environ.get('IMG_BASE_DIR',meta.get('image_root','')))
    if not images.is_dir(): raise ValueError('Missing IMG_BASE_DIR / index metadata image_root')
    env={**os.environ,'IMG_BASE_DIR':str(images),'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
    infer_port=int(os.environ.get('TEST_INFER_PORT','18001'))
    api_port=int(os.environ.get('TEST_API_PORT','18080'))
    if infer_port == api_port:
        raise ValueError('E2E inference and gateway ports must differ')
    for port in (infer_port,api_port):
        with socket.socket() as probe:
            try: probe.bind(('127.0.0.1',port))
            except OSError: raise RuntimeError(f'Test port {port} is already in use; set TEST_INFER_PORT / TEST_API_PORT')
    logs=root/'tmp'; logs.mkdir(exist_ok=True); processes=[]
    try:
        subprocess.run(['go','build','-o',str(logs/'phase-gateway.exe'),'./cmd/server'],cwd=core,check=True)
        for command,cwd,extra,name in [([sys.executable,'-m','uvicorn','ai_worker.api.server:app','--host','127.0.0.1','--port',str(infer_port)],worker,{},'worker'),([str(logs/'phase-gateway.exe')],core,{'PORT':str(api_port),'INFER_API_URL':f'http://127.0.0.1:{infer_port}','INFER_TIMEOUT':'15s'},'gateway')]:
            log=open(logs/f'phase-{name}.log','w')
            processes.append(subprocess.Popen(command,cwd=cwd,env={**env,**extra},stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0))
            log.close()
        base=f'http://127.0.0.1:{api_port}'
        for _ in range(120):
            if any(p.poll() is not None for p in processes): raise RuntimeError('Service exited; inspect tmp/phase-*.log')
            try:
                cfg=requests.get(base+'/api/search/config',timeout=2)
                if cfg.status_code==200:break
            except requests.RequestException:pass
            time.sleep(1)
        else:raise TimeoutError('Startup timeout')
        assert cfg.json()['active_index_version'] == meta['index_version']
        assert cfg.json()['num_vectors'] == meta['num_vectors']
        print('ACTIVE DATASET:', cfg.json(),flush=True)
        def search(i):
            dim=[16,32,64,128,256,512][i%6]
            r=requests.post(base+'/api/search/text',data={'query':'red dress','mrl_dimension':dim,'search_mode':'direct'},timeout=30)
            r.raise_for_status(); p=r.json(); assert p['search_config']['stage1_dim']==dim
            return p
        with ThreadPoolExecutor(max_workers=10) as pool:results=list(pool.map(search,range(10)))
        print('PASS: 10 concurrent real Go -> Python searches',flush=True)
        name=results[0]['data'][0]['product_id']
        r=requests.get(base+'/images/'+name,timeout=5);assert r.status_code==200,(name,r.status_code)
        for mode in ['direct','adaptive']:
            with open(images/name,'rb') as f:r=requests.post(base+'/api/search/image',data={'mrl_dimension':512,'search_mode':mode},files={'image':(name,f,'image/jpeg')},timeout=30)
            r.raise_for_status(); assert r.json()['data'];print('PASS: image + Find Similar',mode,flush=True)
        # Verify index provenance numerically on one indexed image (raw vector, not ranking alone).
        names=json.loads((worker/'vector_db/image_paths.json').read_text())
        with open(images/names[0],'rb') as f:
            p=requests.post(base+'/api/search/image',data={'mrl_dimension':512,'search_mode':'direct'},files={'image':(names[0],f,'image/jpeg')},timeout=30).json()
        self_result=next((x for x in p['data'] if x['product_id']==names[0]),None)
        assert self_result is not None and self_result['similarity_score'] > .999, 'Checkpoint/index provenance mismatch'
        print('PASS: indexed image self-match cosine > .999',flush=True)
        bad=requests.post(base+'/api/search/text',data={'query':'red','mrl_dimension':8},timeout=10);assert bad.status_code==400
        print('PASS: unsupported dimension is HTTP 400',flush=True)
    finally:
        for p in processes:
            p.terminate()
        for p in processes:
            try:p.wait(timeout=10)
            except subprocess.TimeoutExpired:p.kill()


if __name__ == "__main__":
    main()
