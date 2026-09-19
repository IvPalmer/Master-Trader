import pytest
from app.tp_policy import snapshot_nearby, nearby_allocations
from .test_tp_reliability import trade


def filled(amount, short=False, mark=1):
    return dict(trade(amount,short), current_rate=mark)


def test_small_position_exits_first_not_last():
    p=snapshot_nearby([1.1,1.2,2],1,False)
    assert nearby_allocations(filled(15),p)==[(0,1.1,15)]


def test_valid_split_preserves_filled_inventory():
    p=snapshot_nearby([1.1,1.2,2],1,False)
    assert nearby_allocations(filled(40),p)==[(0,1.1,20),(1,1.2,20)]


def test_feasible_asymmetric_split_instead_of_failing_equal_weights():
    p=snapshot_nearby([.35,.362,.5],.33,False)
    assert nearby_allocations(filled(65,mark=.33),p)==[(0,.35,29),(1,.362,36)]


def test_short_second_order_minimum_and_residual():
    p=snapshot_nearby([.9,.8,.5],1,True)
    assert nearby_allocations(filled(40,True),p)==[(0,.9,20),(1,.8,20)]
    assert nearby_allocations(filled(20,True),p)==[(0,.9,20)]


def test_crossed_original_candidates_keep_original_indices():
    p=snapshot_nearby([.9,1.1,1.2],1,False)
    assert nearby_allocations(filled(15),p)==[(1,1.1,15)]


def test_crossed_after_entry_blocks_instead_of_moving_price():
    p=snapshot_nearby([1.1,1.2],1,False)
    with pytest.raises(ValueError,match='crossed'):
        nearby_allocations(filled(40,mark=1.15),p)


def test_too_small_entire_position_not_moved_later():
    p=snapshot_nearby([1.1,100],1,False)
    with pytest.raises(ValueError,match='whole position'):
        nearby_allocations(filled(5),p)


def test_filling_entry_waits():
    t=filled(40); t['orders']=[{'is_open':True,'ft_order_side':'buy'}]
    assert nearby_allocations(t,snapshot_nearby([1.1,1.2],1,False))==[]


@pytest.mark.parametrize('prices', [[],[.9,.8],[1.2,1.1]])
def test_missing_or_unordered_source_fails(prices):
    with pytest.raises(ValueError): snapshot_nearby(prices,1,False)


def test_frozen_fallback_is_used_by_existing_arming_path(monkeypatch):
    import json
    from unittest.mock import AsyncMock, patch
    from app import main as receiver
    from .test_phase2_active_tps import _setup_db, _run
    monkeypatch.setenv('KILLERS_EXECUTION_VENUE','hyperliquid')
    cfg,conn,pos=_setup_db()
    conn.execute('UPDATE positions SET tp_policy=? WHERE pos_id=?',(json.dumps(snapshot_nearby([1.1,1.2],1,False)),pos))
    t=filled(15)
    resting=dict(t,orders=[{'order_id':'synthetic','is_open':True,'order_type':'limit','ft_order_side':'sell','safe_price':1.1,'amount':15}])
    with patch.object(receiver,'ft_get_trade',new=AsyncMock(side_effect=[t,resting])), patch.object(receiver,'ft_force_exit_limit',new=AsyncMock(return_value={'status':200,'body':'{}'})) as post:
        rows=_run(receiver._place_target_limits(cfg,conn,pos,42,[1.1,1.2],7.5))
    assert [(r['idx'],r['price'],r['amount'],r['state']) for r in rows]==[(0,1.1,15,'active')]
    assert post.await_count==1


def test_incompatible_policy_settings_fail_startup(monkeypatch):
    from app.main import Config
    monkeypatch.setenv('KILLERS_TP_MODE','nearest_source')
    monkeypatch.setenv('KILLERS_TP_ALLOCATIONS','1:100')
    with pytest.raises(ValueError,match='cannot be combined'): Config()
