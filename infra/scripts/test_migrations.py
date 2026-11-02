"""Check migration up/repeat/down/up using only a fresh temporary database."""
import argparse
from pathlib import Path
import subprocess
from uuid import uuid4


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--env-file',default='infra/test.env.example')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[2]
    compose=['docker','compose','--env-file',args.env_file]
    def run(arguments):subprocess.run(compose+arguments,cwd=root,check=True)
    name='aurafind_migration_'+uuid4().hex[:12]
    run(['exec','-T','postgres','psql','-U','aurafind','-d','postgres','-v','ON_ERROR_STOP=1','-c',f'CREATE DATABASE {name}'])
    # Run inside the Compose network and use the container's configured password.
    try:
        for operation in ['up','up','down','up']:
            script='migrate -path /migrations -database "postgres://aurafind:$POSTGRES_PASSWORD@postgres:5432/'+name+'?sslmode=disable" '+('down -all' if operation=='down' else 'up')
            # Password is supplied through Compose environment, not interpolated by the host shell.
            run(['run','--rm','--no-deps','--entrypoint','/bin/sh','migrate','-ec',script])
        print('PASS: temporary database migration up/repeat/down/up')
    finally:
        run(['exec','-T','postgres','psql','-U','aurafind','-d','postgres','-v','ON_ERROR_STOP=1','-c',f'DROP DATABASE {name}'])


if __name__=='__main__':main()
