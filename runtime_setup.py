"""Serialize setup and publish complete, interpreter-specific private runtimes."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import uuid

@contextmanager
def setup_lock(base):
    base.mkdir(parents=True,exist_ok=True)
    with (base/'runtime-setup.lock').open('a+b') as handle:
        handle.seek(0);handle.write(b'0');handle.flush();handle.seek(0)
        deadline=time.monotonic()+600
        while True:
            try:
                if os.name=='nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic()>deadline: raise RuntimeError('Another setup is still running. Wait for it to finish and retry.')
                time.sleep(.25)
        try: yield
        finally:
            handle.seek(0)
            if os.name=='nt': msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else: fcntl.flock(handle.fileno(),fcntl.LOCK_UN)

def ensure_runtime(base,root):
    lock=root/'requirements-macos.lock'
    requirements=lock if sys.platform=='darwin' and sys.version_info[:2]==(3,14) and lock.exists() else root/'requirements.txt'
    identity='|'.join((sys.version,sys.implementation.name,platform.machine(),sys.platform))
    fingerprint=hashlib.sha256(identity.encode()+requirements.read_bytes()).hexdigest()
    env=base/'runtimes'/fingerprint[:24]
    relative=Path('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    with setup_lock(base):
        if not (env/relative).exists() or not (env/'complete').exists():
            env.parent.mkdir(parents=True,exist_ok=True)
            staging=env.parent/('preparing-'+uuid.uuid4().hex)
            try:
                subprocess.run([sys.executable,'-m','venv',str(staging)],check=True)
                subprocess.run([str(staging/relative),'-m','pip','install','--disable-pip-version-check','-r',str(requirements)],check=True)
                (staging/'complete').write_text(fingerprint)
                # An incomplete old target is retained for diagnosis, never launched.
                if env.exists(): env.rename(env.with_name(env.name+'-incomplete-'+uuid.uuid4().hex))
                staging.rename(env)
            except BaseException:
                shutil.rmtree(staging,ignore_errors=True)
                raise
    return env/relative
