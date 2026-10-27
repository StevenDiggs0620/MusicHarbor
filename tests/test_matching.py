import pytest
from matching import score, title_base, rebuild_coverage
from conftest import project_with_options


def song(title='Graves', artist='KB, Brandon Lake', duration=180, explicit=False, isrc=None):
    return dict(title=title,artist=artist,duration=duration,explicit=explicit,isrc=isrc)


def test_featured_artists_and_punctuation():
    assert title_base('Graves (feat. Brandon Lake)')==title_base('GRAVES')
    result=score(song(),song(artist='KB & Brandon Lake'))
    assert result['confidence']=='high'


@pytest.mark.parametrize('version',['Live','Acoustic','Remix','Instrumental','Radio Edit','Remastered'])
def test_distinct_versions_are_blocked(version):
    result=score(song(),song(title=f'Graves ({version})'))
    assert not result['compatible']


def test_different_named_remixes_need_review():
    result=score(song(title='Graves (Club Remix)'),song(title='Graves (Dance Remix)'))
    assert result['confidence']!='high'


def test_explicit_preferences():
    assert not score(song(),song(explicit=True))['compatible']
    assert score(song(),song(explicit=True),{'clean_explicit_equivalent':True})['confidence']=='high'


def test_featured_artist_alone_is_not_enough():
    assert score(song(),song(artist='Brandon Lake'))['confidence']!='high'


def test_missing_duration_needs_review_without_isrc():
    assert score(song(),song(duration=0))['confidence']!='high'


def test_isrc_does_not_override_version_conflict():
    result=score(song(isrc='US1234567890'),song(title='Graves (Live)',isrc='US1234567890'))
    assert not result['compatible']


def test_manual_reference_and_rejected_alternate():
    p=project_with_options();r=p['recordings']['a']
    r['selected']={'trackId':10,'trackName':'a','artistName':'Artist','trackTimeMillis':180000,'trackExplicitness':'notExplicit'}
    p['releases']['album']['songs']=[dict(r['selected'],trackId=11)]
    rebuild_coverage(p,{})
    assert p['releases']['album']['coverage']==['a']
    r['rejected']=['11'];rebuild_coverage(p,{})
    assert p['releases']['album']['coverage']==[]
