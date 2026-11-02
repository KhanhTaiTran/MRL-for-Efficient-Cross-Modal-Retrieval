"""Phase -1 regression entry point. Add --e2e with IMG_BASE_DIR for live HTTP tests."""
import argparse
import os
import subprocess
import sys
from ai_worker.paths import WORKER_ROOT

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--e2e',action='store_true')
    args=parser.parse_args()
    folder=WORKER_ROOT
    env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
    subprocess.run([sys.executable,'-u','-m','tests.test_readiness'],cwd=folder,env=env,check=True)
    subprocess.run([sys.executable,'-u','-m','tests.test_index_reload'],cwd=folder,env=env,check=True)
    subprocess.run([sys.executable,'-u','-m','tests.test_search_regression'],cwd=folder,env=env,check=True)
    if args.e2e:
        subprocess.run([sys.executable,'-u','-m','tests.test_search_e2e'],cwd=folder,env=env,check=True)
