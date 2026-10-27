"""Cross-platform first-run setup and launch."""
import os
from pathlib import Path
import socket
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'src'
sys.path.insert(0,str(SOURCE))


def main():
    if sys.version_info < (3,11):
        raise RuntimeError('Install Python 3.11 or newer from python.org, then open the launcher again.')
    try:
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',8765))
    except OSError:
        raise RuntimeError('Another program is using port 8765. Close it and try again.')
    # Keep the virtual environment and database outside OneDrive / source folders.
    from musicharbor.branding import data_dir
    base=data_dir()
    from musicharbor.runtime_setup import ensure_runtime
    python=ensure_runtime(base,ROOT)
    print('Opening MusicHarbor in its own window…',flush=True)
    environment=os.environ.copy()
    environment['PYTHONPATH']=os.pathsep.join(filter(None,(str(SOURCE),environment.get('PYTHONPATH',''))))
    subprocess.run([str(python),'-m','musicharbor'],cwd=ROOT,env=environment,check=True)


if __name__=='__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as error:
        print(f'\nMusicHarbor could not start: {error}',file=sys.stderr)
        print('See README.md for setup and troubleshooting.',file=sys.stderr)
        if sys.stdin.isatty(): input('Press Enter to close…')
        sys.exit(1)
