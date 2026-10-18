"""Single-process loopback deployment: python -m scripts.serve --port 8005."""
import argparse
import logging
import sys

import uvicorn

from app.config import Settings
from scripts.check import inspect


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8005)
    args=parser.parse_args()
    if not 1<=args.port<=65535:
        parser.error('port must be 1..65535')
    try:
        settings=Settings()
        report=inspect(settings)
        if not all(report['checks'][key] for key in ('python_3_12','dependencies','state_directory','log_directory','database_integrity')):
            print('Local runtime/storage check failed; run python -m scripts.check for safe details.')
            raise SystemExit(1)
    except SystemExit:
        raise
    except Exception as error:
        print('Startup configuration rejected:',type(error).__name__)
        raise SystemExit(1)
    print(f'Issue assistant V5: http://127.0.0.1:{args.port} (one local user, one process)',flush=True)
    print('Local analysis configuration:',report['status'],'(remote services not checked)',flush=True)
    # Avoid raw HTTP URLs/query strings in access logs. App events contain route templates only.
    for name in ('httpx','httpx2','openai'):
        logging.getLogger(name).setLevel(logging.WARNING)
    uvicorn.run('app.api:app',host='127.0.0.1',port=args.port,workers=1,access_log=False,log_level='warning')

if __name__=='__main__':
    main()
