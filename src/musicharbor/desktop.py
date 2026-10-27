"""Native desktop entry point; the existing loopback server stays private to this app."""
import logging
from logging.handlers import RotatingFileHandler
import socket
import threading
import time

from musicharbor import store

URL = 'http://127.0.0.1:8765'

class FolderPicker:
    """Only the local workspace may request a user-controlled folder dialog."""
    def __init__(self):
        self._window=None
        self._lock=threading.Lock()

    def choose_folder(self):
        from urllib.parse import urlparse
        import webview
        if self._window is None: return None
        url=urlparse(self._window.get_current_url() or '')
        if url.scheme!='http' or url.netloc not in ('127.0.0.1:8765','localhost:8765'):
            raise ValueError('Open the local workspace before selecting a folder.')
        if not self._lock.acquire(blocking=False):
            raise ValueError('A folder dialog is already open. Finish or cancel it first.')
        try:
            selected=self._window.create_file_dialog(webview.FileDialog.FOLDER)
            return str(selected[0]) if selected else None
        finally: self._lock.release()


def start_server():
    import uvicorn
    from musicharbor.app import app
    listener = socket.socket()
    try:
        listener.bind(('127.0.0.1', 8765))
    except OSError:
        listener.close()
        raise RuntimeError('MusicHarbor is already running, or another app is using its port. '
                           'Close the previous browser/terminal version and its server, then reopen this app.')
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8765,
                            access_log=False, log_config=None, timeout_graceful_shutdown=10))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 45
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            server.should_exit = True
            thread.join(timeout=12)
            listener.close()
            raise RuntimeError('The music workspace could not start. See desktop.log in the app data folder.')
        time.sleep(.05)
    return server, thread, listener


def main():
    import webview
    store.DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    logging.basicConfig(level=logging.INFO, handlers=[RotatingFileHandler(
        store.DATA / 'desktop.log', maxBytes=2_000_000, backupCount=2, encoding='utf-8')])
    server = thread = listener = None
    try:
        server, thread, listener = start_server()
        webview.settings['ALLOW_DOWNLOADS'] = True
        webview.settings['ALLOW_FILE_URLS'] = False
        webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True
        picker=FolderPicker()
        picker._window=webview.create_window('MusicHarbor', URL, width=1280, height=850,
                              min_size=(800, 600), background_color='#f5f7f2',
                              text_select=True, zoomable=True)
        from musicharbor.app import app
        app.state.folder_picker=picker.choose_folder
        webview.start(private_mode=False, storage_path=str(store.DATA / 'desktop-browser'))
    except Exception as error:
        logging.exception('Desktop startup failed')
        # Render the error inside a window even in a console-free packaged build.
        from html import escape
        webview.create_window('MusicHarbor — could not start', html=
            '<html><body style="font:18px system-ui;padding:32px"><h2>Could not open MusicHarbor</h2>'
            f'<p>{escape(str(error))}</p><p>Your saved projects have not been removed.</p></body></html>',
            width=620, height=320)
        webview.start()
    finally:
        from musicharbor.app import app
        app.state.folder_picker=None
        if server:
            server.should_exit = True
            thread.join(timeout=15)
        if listener:
            listener.close()


if __name__ == '__main__':
    main()
