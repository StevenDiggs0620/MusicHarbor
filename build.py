"""Build a portable desktop bundle on the target operating system."""
from pathlib import Path
import os
import subprocess
import sys
import hashlib
import json
import platform
import plistlib
import stat
from datetime import datetime, timezone
from importlib.metadata import version, distributions

ROOT=Path(__file__).resolve().parent
arguments=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir',
           '--name','MusicHarbor','--add-data',f'{ROOT / "static"}{os.pathsep}static',
           '--collect-all','scipy','--collect-all','mutagen','--hidden-import','uvicorn.logging',
           '--hidden-import','uvicorn.loops.auto','--hidden-import','uvicorn.protocols.http.auto',
           '--hidden-import','uvicorn.protocols.websockets.auto','--hidden-import','uvicorn.lifespan.on']
if sys.platform in ('darwin','win32'): arguments+=['--windowed']
if sys.platform=='darwin': arguments+=['--osx-bundle-identifier','local.musicharbor.app']
arguments.append(str(ROOT/'desktop.py'))

def build():
    if sys.platform=='darwin':
        for line in (ROOT/'requirements-macos.lock').read_text().splitlines():
            if not line or line.startswith('#'): continue
            name,expected=line.split('==',1)
            if version(name)!=expected: raise RuntimeError(f'Release dependency differs from lock: {name}. Install the release lock before packaging.')
    output=ROOT/'build';output.mkdir(exist_ok=True)
    release_id=datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    destination=ROOT/'dist'/'releases'/release_id
    destination.mkdir(parents=True,exist_ok=False)
    sources=list(ROOT.glob('*.py'))+list((ROOT/'static').glob('*'))
    manifest=dict(app='MusicHarbor',release_id=release_id,version='1.3.0',python=sys.version,platform=sys.platform,architecture=platform.machine(),
                  dependencies={d.metadata['Name']:d.version for d in distributions()},
                  sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources if p.is_file()},
                  verification='Packaging only; application and regression checks not run.')
    manifest_path=output/'release-manifest.json'
    manifest_path.write_text(json.dumps(manifest,indent=2))
    command=arguments[:-1]+['--distpath',str(destination),'--add-data',f'{manifest_path}{os.pathsep}.']+arguments[-1:]
    env=dict(os.environ,PYINSTALLER_CONFIG_DIR=str(output/'.pyinstaller-cache'))
    subprocess.run(command,cwd=ROOT,env=env,check=True)
    if sys.platform=='darwin':
        bundle=destination/'MusicHarbor.app'
        # Never replace a bundle which an already-running process may be using.
        info_path=bundle/'Contents/Info.plist'
        info=plistlib.loads(info_path.read_bytes())
        info.update(CFBundleShortVersionString='1.3.0',CFBundleVersion='1.3.0')
        info_path.write_bytes(plistlib.dumps(info))
        executable=bundle/'Contents/MacOS'/info['CFBundleExecutable']
        if not executable.is_file(): raise RuntimeError('Packaged executable is missing.')
        executable.chmod(executable.stat().st_mode|stat.S_IXUSR|stat.S_IXGRP|stat.S_IXOTH)
        with executable.open('rb') as stream: magic=stream.read(4)
        if magic not in (b'\xcf\xfa\xed\xfe',b'\xfe\xed\xfa\xcf',b'\xca\xfe\xba\xbe',b'\xbe\xba\xfe\xca'):
            raise RuntimeError('Packaged executable is not a supported macOS binary.')
        subprocess.run(['xattr','-crs',str(bundle)],check=True)
        identity=os.getenv('MUSICHARBOR_SIGNING_IDENTITY') or os.getenv('PLAYLIST_SIGNING_IDENTITY','-')
        command=['codesign','--force','--deep','--sign',identity]
        if identity!='-': command+=['--options','runtime','--timestamp']
        subprocess.run(command+[str(bundle)],check=True)
        subprocess.run(['xattr','-crs',str(bundle)],check=True)
        subprocess.run(['codesign','--verify','--deep','--strict',str(bundle)],check=True)
        # Archive retains the bundle layout and executable permissions during transfer.
        subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(bundle),str(destination/'MusicHarbor.zip')],check=True)
        (ROOT/'dist'/'LATEST_RELEASE.txt').write_text(str(bundle)+'\n',encoding='utf-8')
        print(f'Packaged app: {bundle}',flush=True)
    else:
        bundle=destination/'MusicHarbor'
        (ROOT/'dist'/'LATEST_RELEASE.txt').write_text(str(bundle)+'\n',encoding='utf-8')
        print(f'Packaged app: {bundle}',flush=True)

if __name__=='__main__': build()
