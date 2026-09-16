import importlib.util
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).parents[1]/'research/profit_retention'
sys.path.insert(0,str(ROOT))
import accounting as a
import ledger as l


def trade(short=False):
    return dict(trade_id=1,is_short=short,base_currency='X',is_open=False,close_timestamp=5000,
        fee_close=.001,funding_fees=-.3,_fee_observations=[dict(ts=0,taker_rate=.001)],enter_tag='sl:110' if short else 'sl:90',close_profit_abs=9.29,
        orders=[dict(order_id='entry',ft_order_side='sell' if short else 'buy',filled=2),
                dict(order_id='tp',ft_order_side='buy' if short else 'sell',filled=1),
                dict(order_id='sl',ft_order_side='stoploss',filled=1)])


def events():
    return [dict(ts=1000,kind='entry',qty=2,price=100,fee=.2,stop=False),
        dict(ts=2000,kind='funding',cash=-.2,position=2),
        dict(ts=3000,kind='exit',qty=1,price=120,fee=.12,stop=False),
        dict(ts=4000,kind='funding',cash=-.1,position=1),
        dict(ts=5000,kind='exit',qty=1,price=90,fee=.09,stop=True)]


def snap(ts,mark):
    return dict(ts=ts,trades=[dict(trade_id=1,stop_loss_abs=90)],market={'X':dict(mark=mark,
        book_time=ts,mark_requested=ts,mark_received=ts,
        levels=[[dict(px=str(mark),sz='20')],[dict(px=str(mark),sz='20')]])})


def test_partial_exit_and_settled_funding_net_reconciliation():
    cash,qty=a.baseline(events(),False)
    assert cash==pytest.approx(9.29)
    assert qty==0
    result=a.replay(events(),[snap(1.1,100),snap(3.5,130),snap(4.5,119)],trade())
    assert result['flags']==[]
    assert result['net_usd']==pytest.approx(38.261)
    assert result['risk_usd']==20


def test_no_funding_after_candidate_exit_and_positive_funding_sign():
    rows=[dict(ts=1000,kind='entry',qty=1,price=100,fee=.1,stop=False),
        dict(ts=3500,kind='funding',cash=2,position=1),
        dict(ts=5000,kind='exit',qty=1,price=100,fee=.1,stop=False)]
    result=a.replay(rows,[snap(1.1,130),snap(2.1,119)],trade())
    assert result['net_usd']==pytest.approx(18.781)
    assert a.baseline(rows,False)[0]==pytest.approx(1.8)


def test_unchanged_candidate_inherits_actual_source_exit():
    result=a.replay(events(),[snap(1.1,100),snap(3.5,105),snap(4.5,100)],trade())
    assert not result['armed']
    assert result['net_usd']==pytest.approx(9.29)


def test_latency_and_nonfill_do_not_borrow_original_stop_fill():
    result=a.replay(events(),[snap(1.1,100),snap(3.5,130),snap(4.5,119)],trade(),delay=1)
    assert result['net_usd'] is None
    assert 'baseline_stop_filled_before_modeled_exit' in result['flags']
    result=a.replay(events(),[snap(1.1,100),snap(3.5,130),snap(4.5,110)],trade())
    assert result['nonfill_observations']==1
    assert result['net_usd'] is None


def test_funding_cannot_be_assigned_to_wrong_position():
    rows=events(); rows[1]=dict(rows[1],position=3)
    with pytest.raises(ValueError,match='Funding position'):
        a.baseline(rows,False)


def test_short_cash_flow_and_funding():
    rows=[dict(ts=1000,kind='entry',qty=1,price=100,fee=.1,stop=False),
          dict(ts=2000,kind='funding',cash=.5,position=-1),
          dict(ts=5000,kind='exit',qty=1,price=90,fee=.09,stop=False)]
    assert a.baseline(rows,True)==pytest.approx((10.31,0))


def test_depth_haircut_and_slippage_respect_limit():
    m=snap(1,120)['market']['X']
    assert a.book_fill(m,15,False,117,.5,0) is None
    assert a.book_fill(m,2,False,120,1,10) is None
    assert a.book_fill(m,2,False,117,1,10)==pytest.approx(119.88)


def test_ledger_overlap_dedup_and_conflict():
    fill=dict(coin='X',tid=1,time=10)
    b=dict(start_ms=0,end_ms=100,fills=[fill],funding=[])
    fs,_,coverage=a.merge_ledger([b,b])
    assert len(fs)==1 and coverage==[(0,100)]
    with pytest.raises(ValueError,match='Conflicting'):
        a.merge_ledger([b,dict(b,fills=[dict(fill,time=11)])])


def test_saturated_pagination_splits_without_losing_equal_timestamps():
    def request(body):
        if body['startTime']==0 and body['endTime']==3:
            return [dict(time=1)]*500
        return [dict(time=t) for t in range(body['startTime'],body['endTime']+1)]
    assert [r['time'] for r in l.fetch_interval(request,'userFunding',0,3)]==[0,1,2,3]
    with pytest.raises(ValueError,match='Saturated'):
        l.fetch_interval(lambda b:[dict(time=1)]*500,'userFunding',1,1)


def test_bootstrap_uses_dates_and_reports_lost_winners():
    rows=[dict(date='a',delta_r=-1,baseline_r=2,candidate_r=1,closed_ms=1),
          dict(date='a',delta_r=-1,baseline_r=2,candidate_r=1,closed_ms=2)]
    result=a.paired_summary(rows)
    assert result['date_cluster_ci95'] is None
    assert result['missed_baseline_winners']==2
    rows.append(dict(date='b',delta_r=2,baseline_r=-1,candidate_r=1,closed_ms=3))
    result=a.paired_summary(rows)
    assert result==a.paired_summary(rows)
    assert result['date_clusters']==2


def raw_batch():
    def fill(oid,tid,ts,qty,px,fee,side):
        return dict(oid=oid,tid=tid,time=ts,coin='X',sz=str(qty),px=str(px),fee=str(fee),side=side,feeToken='USDC')
    return dict(start_ms=0,end_ms=6000,fee_observation=dict(ts=0,taker_rate=.001),
        fills=[fill('entry',1,900,1,100,.1,'B'),fill('entry',2,1000,1,100,.1,'B'),
               fill('tp',3,3000,1,120,.12,'A'),fill('sl',4,5000,1,90,.09,'A')],
        funding=[dict(time=2000,hash='a',delta=dict(coin='X',usdc='-.2',szi='2')),
                 dict(time=4000,hash='b',delta=dict(coin='X',usdc='-.1',szi='1'))])


def analysis_input():
    rows=[snap(1.1,100),snap(3.5,130),snap(4.5,119),snap(5.1,90)]
    for i,row in enumerate(rows):
        row['collector_sha256']='frozen'
        row['trades']=[dict(trade(),is_open=i!=3)]
    return rows,dict(start=0,collector_sha256='frozen',max_gap_seconds=120)


def test_full_join_partial_entry_fills_and_paired_report():
    rows,protocol=analysis_input()
    report=a.analyze(rows,protocol,[raw_batch(),raw_batch()])
    assert report['exchange_reconciled_closed_trades']==1
    assert report['scenarios']['quoted']['completed_pairs']==1
    assert report['scenarios']['quoted']['mean_delta_r']==pytest.approx((38.261-9.29)/20)
    assert report['scenarios']['one_sample_half_depth']['completed_pairs']==0


def test_no_score_on_missing_ledger_or_fee_lookahead():
    rows,protocol=analysis_input()
    batch=raw_batch(); batch['start_ms']=1000
    assert a.analyze(rows,protocol,[batch])['exclusions']['Ledger coverage incomplete']==1
    batch=raw_batch(); batch['fee_observation']['ts']=6000
    report=a.analyze(rows,protocol,[batch])
    assert report['scenarios']['quoted']['completed_pairs']==0
    assert report['scenarios']['quoted']['flagged']['missing_causal_taker_fee']==1


def test_executor_mismatch_and_missing_partial_fill_fail_closed():
    batch=raw_batch()
    batch['fills'].pop(0)
    with pytest.raises(ValueError,match='quantity does not reconcile'):
        a.trade_events(trade(),batch['fills'],batch['funding'])
    rows,protocol=analysis_input()
    rows[-1]['trades'][0]['close_profit_abs']=99
    report=a.analyze(rows,protocol,[raw_batch()])
    assert report['scenarios']['quoted']['completed_pairs']==0
    assert report['exclusions']['Executor net PnL disagrees with settled exchange cash flows']==1


def test_report_uses_settled_funding_even_when_executor_omits_it():
    rows,protocol=analysis_input()
    rows[-1]['trades'][0].update(funding_fees=0,close_profit_abs=9.59)
    report=a.analyze(lambda:iter(rows),protocol,lambda:iter([raw_batch()]))
    assert report['executor_funding_discrepancies']==1
    assert report['exchange_reconciled_closed_trades']==1
    assert report['scenarios']['quoted']['baseline_mean_r']==pytest.approx(9.29/20)
