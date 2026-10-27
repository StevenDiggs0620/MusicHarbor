from pathlib import Path
import musicharbor.branding as branding


def test_new_install_and_existing_collection_share_location_policy(tmp_path, monkeypatch):
    monkeypatch.delenv('MUSICHARBOR_DATA', raising=False)
    monkeypatch.delenv('PLAYLIST_PURCHASER_DATA', raising=False)
    monkeypatch.setattr(branding.sys, 'platform', 'darwin')
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: tmp_path))
    root = tmp_path / 'Library/Application Support'
    assert branding.data_dir() == root / 'MusicHarbor'
    legacy = root / 'Playlist Purchaser'
    legacy.mkdir(parents=True)
    assert branding.data_dir() == legacy


def test_new_override_precedes_legacy_override(tmp_path, monkeypatch):
    monkeypatch.setenv('PLAYLIST_PURCHASER_DATA', str(tmp_path / 'old'))
    monkeypatch.delenv('MUSICHARBOR_DATA', raising=False)
    assert branding.data_dir() == tmp_path / 'old'
    monkeypatch.setenv('MUSICHARBOR_DATA', str(tmp_path / 'new'))
    assert branding.data_dir() == tmp_path / 'new'
