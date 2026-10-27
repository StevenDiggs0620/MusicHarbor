from musicharbor.optimizer import calculate, cents
from musicharbor.matching import rec_owned
from conftest import project_with_options


def test_cheapest_and_fewest_are_distinct():
    p=project_with_options()
    cheap=calculate(p)
    few=calculate(p,'fewest')
    assert cheap['optimal'] and cheap['complete'] and cheap['cost']==3
    assert set(cheap['release_ids'])=={'a','b','c'}
    assert few['release_ids']==['album'] and few['cost']==6


def test_priority_is_dynamic_and_not_cheapest():
    p=project_with_options()
    result=calculate(p,'most-songs')
    assert result['release_ids']==['album']
    assert not result['optimal']
    p['releases']['album']['owned']=True
    assert calculate(p)['remaining']==0
    p['releases']['album']['owned']=False
    assert calculate(p)['remaining']==3


def test_unknown_negative_nan_and_wrong_currency_are_not_buyable():
    p=project_with_options()
    for key, price in zip(p['releases'],[None,-1,float('nan'),float('inf')]):
        p['releases'][key]['price']=price
    assert calculate(p)['unavailable']==['a','b','c']
    p['releases']['album'].update(price=1,currency='CAD')
    assert not calculate(p)['complete']


def test_free_product_is_valid():
    p=project_with_options();p['releases']['album']['price']=0
    result=calculate(p)
    assert result['complete'] and result['cost']==0 and result['release_ids']==['album']
    assert cents(1.295)==130


def test_partial_ownership_and_explicit_override():
    p=project_with_options();p['releases']['album']['partial']=['a','b']
    assert rec_owned(p,'a') and not rec_owned(p,'c')
    assert calculate(p)['release_ids']==['c']
    p['recordings']['a']['ownership_override']=False
    assert not rec_owned(p,'a')
    assert calculate(p)['remaining']==2


def test_budget_maximizes_coverage_and_honors_required():
    p=project_with_options();p['recordings']['c']['required']=True
    result=calculate(p,'best-value',budget=2)
    assert result['covered']==2 and result['cost']==2 and 'c' in result['release_ids']
    assert not result['complete']
    assert not calculate(p,'best-value',budget=0)['release_ids']


def test_unavailable_required_is_not_silently_ignored():
    p=project_with_options();p['recordings']['c']['required']=True
    p['releases']['album']['excluded']=True;p['releases']['c']['price']=None
    result=calculate(p,'best-value',budget=10)
    assert not result['complete'] and 'required' in result['status']


def test_price_then_newer_date_break_coverage_ties():
    p=project_with_options()
    p['releases']['album']['excluded']=True
    p['releases']['b']['date']='2026-01-01'
    result=calculate(p,'most-songs')
    assert result['release_ids'][0]=='b'
    assert result['covered']==3


def test_excluded_recording_is_not_required_for_complete_plan():
    p=project_with_options();p['recordings']['c']['included']=False
    result=calculate(p)
    assert result['complete'] and result['cost']==2 and result['remaining']==2


def test_budget_prioritizes_played_songs_before_unplayed_bargains():
    p=project_with_options()
    p['releases']['a']['price']=1.29
    p['releases']['b']['price']=.99
    p['releases']['c']['price']=.99
    result=calculate(p,'best-value',budget=2,play_counts={'a':5,'b':0,'c':0})
    assert result['release_ids']==['a']
    assert calculate(p,'best-value',budget=2)['covered']==2
    assert calculate(p,'best-value',budget=2,play_counts={})['covered']==2


def test_budget_plays_break_coverage_ties_and_required_still_wins():
    p=project_with_options()
    counts={'a':1,'b':20,'c':0}
    assert calculate(p,'best-value',budget=1,play_counts=counts)['release_ids']==['b']
    assert calculate(p,'best-value',budget=3,play_counts=counts)['covered']==3
    p['recordings']['c']['required']=True
    assert calculate(p,'best-value',budget=1,play_counts=counts)['release_ids']==['c']
