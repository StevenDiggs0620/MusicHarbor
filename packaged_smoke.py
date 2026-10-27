"""Opt-in packaged runtime/window checks. Never run during ordinary packaging."""
import json
import os
from pathlib import Path
import tempfile
import time
from urllib.request import urlopen

def main(window=False):
    import store
    import desktop
    with tempfile.TemporaryDirectory(prefix='playlist-package-check-') as temporary:
        store.DATA=Path(temporary);store.DB=store.DATA/'test.sqlite3'
        os.environ['MUSICHARBOR_LEGACY']=str(store.DATA/'absent.sqlite3')
        server,thread,listener=desktop.start_server()
        try:
            with urlopen(desktop.URL+'/api/health',timeout=15) as response:
                assert json.load(response)['app']=='musicharbor'
            for resource in ('/','/static/ui.js','/static/workflows.js','/static/ui.css'):
                with urlopen(desktop.URL+resource,timeout=15) as response: assert response.status==200 and response.read()
            import backup_schema, export_policy, library_index, planning, portable, retention
            if window:
                import webview
                result={}
                view=webview.create_window('Packaged smoke check',desktop.URL)
                def inspect():
                    try:
                        deadline=time.monotonic()+20
                        while time.monotonic()<deadline:
                            if view.evaluate_js("document.querySelector('#main h1')?.textContent || ''"):
                                result['loaded']=True;break
                            time.sleep(.2)
                    except Exception as exc: result['error']=str(exc)
                    finally: view.destroy()
                webview.start(inspect,private_mode=True,storage_path=str(store.DATA/'browser'))
                assert result.get('loaded'),result
        finally:
            server.should_exit=True;thread.join(timeout=15);listener.close()

