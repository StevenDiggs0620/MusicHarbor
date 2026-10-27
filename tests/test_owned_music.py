from conftest import project_with_options
from musicharbor.owned_music import owned_collection


def track(p, rid, cid, price, artist='Artist', number=1, kind='album'):
    key='track:'+rid
    p['releases'][key]=dict(id=key,purchase_type='track',release_id=cid,release_name=cid,
        name=rid,artist=artist,price=price,currency='USD',coverage=[rid],track_number=number,
        kind='individual song',release_kind=kind,artwork='https://is1-ssl.mzstatic.com/image.jpg')
    p['recordings'][rid]['owned']=True


def test_owned_playlist_unique_counts_value_and_album_track_order():
    p=project_with_options()
    track(p,'a','A',1.29,number=2);track(p,'b','A',.99,number=1)
    result=owned_collection(p)
    assert (result['count'],result['total'],result['percent'],result['value'])==(2,3,66.7,2.28)
    assert len(result['groups'])==1
    assert result['groups'][0]['release_ids']==['owned:b','owned:a']
    assert result['releases']['owned:a']['artwork']


def test_full_album_value_counts_only_owned_playlist_tracks():
    p=project_with_options()
    track(p,'a','A',1.29);track(p,'b','A',.99)
    p['releases']['album:A']=dict(id='album:A',release_id='A',kind='album',name='A',artist='Artist',
        price=19.99,currency='USD',coverage=['a','b'],owned=True,artwork='cover')
    p['recordings']['outside']=dict(p['recordings']['a'],id='outside')
    track(p,'outside','A',5)
    result=owned_collection(p)
    assert result['value']==2.28 and result['count']==2
    assert result['groups'][0]['release_ids']==['owned-album:A']
    assert result['releases']['owned-album:A']['coverage']==['a','b']
    assert result['releases']['owned-album:A']['price']==19.99


def test_unknown_prices_and_unmatched_owned_recordings_remain_visible():
    p=project_with_options();p['recordings']['a']['owned']=True
    track(p,'b','B',2);p['releases']['track:b']['currency']='CAD'
    result=owned_collection(p)
    assert result['count']==2 and result['unpriced']==2 and result['value']==0
    assert len(result['releases'])==2
    assert all(r['price'] is None for r in result['releases'].values())


def test_owned_groups_use_plays_then_price_then_artist():
    p=project_with_options()
    track(p,'a','A',1,'Zebra');track(p,'b','B',1,'Alpha');track(p,'c','C',.5,kind='single')
    result=owned_collection(p)
    assert [g['release_ids'] for g in result['groups']]==[['owned:c'],['owned:b'],['owned:a']]
    p['releases']['track:a']['price']=.75
    assert owned_collection(p)['groups'][1]['release_ids']==['owned:a']
    assert owned_collection(p,{'a':10,'b':1,'c':20})['groups'][0]['release_ids']==['owned:c']


def test_owned_override_excludes_recording_from_owned_album():
    p=project_with_options();track(p,'a','A',1)
    p['recordings']['a']['ownership_override']=False
    result=owned_collection(p)
    assert result['count']==0 and result['value']==0 and result['groups']==[]
