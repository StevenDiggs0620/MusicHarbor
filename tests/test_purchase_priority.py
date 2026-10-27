from purchase_order import purchase_groups


def test_mixed_release_types_follow_playlist_count_plays_price_and_names():
    p={'tracks':[], 'releases':{}}
    plays={}
    def add(key, count, kind, listens=0, price=1, artist='Artist', title=None):
        coverage=[f'{key}-{i}' for i in range(count)]
        p['tracks'].extend({'recording_id':rid} for rid in coverage)
        plays[coverage[0]]=listens
        p['releases'][key]=dict(id=key,release_id=key,kind=kind,
            purchase_type='track' if kind=='individual song' else 'release',
            name=title or key,release_name=title or key,artist=artist,
            coverage=coverage,price=price)
    add('awesome',7,'album',1)
    add('cool',5,'ep',1)
    add('fun',4,'album',1)
    add('two-song-single',2,'single',30)
    add('another-ep',2,'ep',20)
    add('popular-single',1,'single',40)
    add('album-song',1,'individual song',25)
    add('quiet-single',1,'single',5)
    add('cheap',1,'album',5,.5,'Zebra')
    add('alpha-z',1,'ep',5,1,'Alpha','Z title')
    add('alpha-a',1,'single',5,1,'Alpha','A title')
    add('unknown',1,'album',5,None,'Aardvark')
    # Duplicate appearances and non-playlist catalog recordings do not inflate rank.
    p['tracks'].append(dict(recording_id='quiet-single-0'))
    p['releases']['quiet-single']['coverage'].append('outside-playlist')
    ids=list(reversed(p['releases']))
    assert [g['release_ids'][0] for g in purchase_groups(p,ids,plays)]==[
        'awesome','cool','fun','two-song-single','another-ep','popular-single',
        'album-song','cheap','alpha-a','alpha-z','quiet-single','unknown']


def test_group_price_uses_individual_track_total_not_parent_album_price():
    p={'tracks':[{'recording_id':'a'},{'recording_id':'b'}], 'releases':{
        'album:A':dict(id='album:A',name='A',price=.01),
        'track:a':dict(id='track:a',release_id='A',coverage=['a'],price=1),
        'track:b':dict(id='track:b',release_id='A',coverage=['b'],price=2),
        'album:B':dict(id='album:B',name='B',coverage=['a','b'],price=2.5),
    }}
    assert [g['release_ids'] for g in purchase_groups(p,['track:a','track:b','album:B'])]==[
        ['album:B'],['track:a','track:b']]


def test_zero_plays_ignore_track_count_but_missing_history_does_not():
    p={'tracks':[{'recording_id':str(i)} for i in range(8)], 'releases':{}}
    for key,coverage,price,artist,name in [
        ('large',list(map(str,range(7))),9,'Alpha','Big album'),
        ('played',['7'],20,'Zebra','Played single'),
        ('cheap',['0'],1,'Zebra','Cheap single'),
        ('alpha-z',['1','2'],2,'Alpha','Z title'),
        ('alpha-a',['3'],2,'Alpha','A title')]:
        p['releases'][key]=dict(id=key,coverage=coverage,price=price,artist=artist,name=name)
    ids=list(p['releases'])
    order=lambda plays:[g['release_ids'][0] for g in purchase_groups(p,ids,plays)]
    assert order({'7':5})==['played','cheap','alpha-a','alpha-z','large']
    assert order({})==['cheap','alpha-a','alpha-z','large','played']
    assert order(None)==['large','alpha-z','cheap','alpha-a','played']
