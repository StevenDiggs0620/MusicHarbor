"""Desktop lifecycle checks without opening a GUI or accessing the user's database."""
from types import SimpleNamespace
import sys
import pytest
import desktop


def test_folder_dialog_is_local_only_and_handles_cancel(monkeypatch):
    calls=[]
    monkeypatch.setitem(sys.modules,'webview',SimpleNamespace(FileDialog=SimpleNamespace(FOLDER=20)))
    picker=desktop.FolderPicker()
    picker._window=SimpleNamespace(get_current_url=lambda:desktop.URL,
        create_file_dialog=lambda kind:calls.append(kind))
    assert picker.choose_folder() is None
    assert calls==[20]
    picker._window.create_file_dialog=lambda kind:('/Music',)
    assert picker.choose_folder()=='/Music'
    picker._window.get_current_url=lambda:'https://example.com'
    with pytest.raises(ValueError,match='local workspace'):picker.choose_folder()


def test_port_conflict_explained(monkeypatch):
    class Occupied:
        def bind(self, address): raise OSError('in use')
        def close(self): self.closed = True
    sock = Occupied()
    monkeypatch.setattr(desktop.socket, 'socket', lambda: sock)
    with pytest.raises(RuntimeError, match='already running'):
        desktop.start_server()
    assert sock.closed


def test_window_closes_its_server(isolated_store, monkeypatch):
    calls = []
    server = SimpleNamespace(should_exit=False)
    thread = SimpleNamespace(join=lambda **kw: calls.append('joined'))
    listener = SimpleNamespace(close=lambda: calls.append('closed'))
    monkeypatch.setattr(desktop, 'start_server', lambda: (server, thread, listener))
    view = SimpleNamespace(settings={}, create_window=lambda *a, **kw: calls.append((a, kw)),
                           start=lambda **kw: calls.append(kw))
    monkeypatch.setitem(sys.modules, 'webview', view)
    desktop.main()
    assert calls[0][0] == ('MusicHarbor', desktop.URL)
    assert calls[1]['private_mode'] is False
    assert view.settings['ALLOW_DOWNLOADS'] is True
    assert server.should_exit
    assert calls[-2:] == ['joined', 'closed']
