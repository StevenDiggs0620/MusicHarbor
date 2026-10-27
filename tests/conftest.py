import pytest
from fastapi.testclient import TestClient
import musicharbor.store as store
import app


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path)
    monkeypatch.setattr(store,'DB',tmp_path/'test.sqlite3')
    monkeypatch.setenv('MUSICHARBOR_LEGACY',str(tmp_path/'absent.sqlite3'))
    monkeypatch.delenv('SPOTIFY_CLIENT_ID',raising=False)
    monkeypatch.delenv('SPOTIFY_CLIENT_SECRET',raising=False)
    store.init()
    return tmp_path


@pytest.fixture
def client(isolated_store):
    app.JOBS.clear(); app.BUSY.clear()
    with TestClient(app.app,headers={'X-App-Token':app.SESSION}) as client:
        yield client


def recording(rid, title=None, **extra):
    return dict(id=rid,title=title or rid,artist='Artist',album='Album',duration=180,
                explicit=False,isrc=None,spotify_id=rid,spotify_url='',included=True,
                required=False,owned=False,ownership_override=None,match_status='confirmed',
                selected=None,candidates=[],rejected=[],**extra)


def project_with_options():
    p=store.new_project('Optimizer fixture')
    p['recordings']={rid:recording(rid) for rid in ('a','b','c')}
    p['tracks']=[{'id':store.uid(),'recording_id':rid} for rid in ('a','b','a','c')]
    def release(key, coverage, price, **extra):
        return dict(id=key,catalog_id=key,name=key,artist='Artist',kind='album',date='2025-01-01',
                    price=price,currency='USD',coverage=coverage,owned=False,excluded=False,
                    partial=[],songs=[],url='',artwork='',checked=store.now(),**extra)
    p['releases']={
        'album':release('album',['a','b','c'],6),
        'a':release('a',['a'],1),
        'b':release('b',['b'],1),
        'c':release('c',['c'],1),
    }
    return p
