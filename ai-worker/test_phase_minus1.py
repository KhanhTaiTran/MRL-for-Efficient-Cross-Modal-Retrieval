"""Phase -1 regression entry point. Add --e2e with IMG_BASE_DIR for live HTTP tests."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--e2e',action='store_true')
    args=parser.parse_args()
    folder=Path(__file__).resolve().parent
    env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
    subprocess.run([sys.executable,'-u','test_search_regression.py'],cwd=folder,env=env,check=True)
    if args.e2e:
        subprocess.run([sys.executable,'-u','test_search_e2e.py'],cwd=folder,env=env,check=True)
