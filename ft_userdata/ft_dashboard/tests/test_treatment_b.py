import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import compute_booked_pct


def test_partial_exit_booked_pct():
    assert compute_booked_pct(0.143, 0.488) == 70.7  # TAO live: ~71%

def test_single_exit_is_zero():
    assert compute_booked_pct(1.0, 1.0) == 0.0

def test_missing_denominator_is_none():
    assert compute_booked_pct(1.0, None) is None
    assert compute_booked_pct(1.0, 0) is None

def test_pending_entry_amount_zero_is_none():
    assert compute_booked_pct(0, 1.0) is None

def test_string_numerics_coerced():
    assert compute_booked_pct("0.143", "0.488") == 70.7

def test_fee_dust_floored_to_zero():
    assert compute_booked_pct(0.999, 1.0) == 0.0  # 0.1% shrink < dust threshold

def test_amount_exceeds_requested_clamps_zero():
    assert compute_booked_pct(1.2, 1.0) == 0.0

def test_garbage_is_none():
    assert compute_booked_pct("x", "y") is None

def test_nan_inputs_is_none():
    assert compute_booked_pct(float("nan"), 1.0) is None
    assert compute_booked_pct(1.0, float("nan")) is None
    assert compute_booked_pct("nan", "1.0") is None

def test_inf_inputs_is_none():
    assert compute_booked_pct(1.0, float("inf")) is None
    assert compute_booked_pct(float("inf"), 1.0) is None


import sqlite3
from app import killers_tp_ladder


def _make_receiver_db(path):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE positions (pos_id INTEGER PRIMARY KEY, ft_trade_id INTEGER, state TEXT);
        CREATE TABLE target_orders (target_id INTEGER PRIMARY KEY, pos_id INTEGER,
            idx INTEGER, price REAL, state TEXT);
    """)
    # pos 10 -> ft_trade_id 11 (TAO): 5 filled, idx5 active @295, idx6 pending
    conn.execute("INSERT INTO positions VALUES (10, 11, 'open')")
    rungs = [(0,210,'filled'),(1,220,'filled'),(2,235,'filled'),(3,250,'filled'),
             (4,270,'filled'),(5,295,'active'),(6,320,'pending')]
    for i,(idx,price,st) in enumerate(rungs):
        conn.execute("INSERT INTO target_orders VALUES (?,?,?,?,?)", (i, 10, idx, price, st))
    # a closed position must be ignored
    conn.execute("INSERT INTO positions VALUES (99, 5, 'closed')")
    conn.execute("INSERT INTO target_orders VALUES (100, 99, 0, 1.0, 'pending')")
    conn.commit(); conn.close()


def test_tp_ladder_counts_and_next(tmp_path):
    db = tmp_path / "receiver.sqlite"; _make_receiver_db(str(db))
    out = killers_tp_ladder(str(db))
    assert out[11] == {"tps_total": 7, "tps_hit": 5, "next_tp": 295.0}

def test_tp_ladder_ignores_closed_positions(tmp_path):
    db = tmp_path / "receiver.sqlite"; _make_receiver_db(str(db))
    assert 5 not in killers_tp_ladder(str(db))

def test_tp_ladder_missing_db_returns_empty(tmp_path):
    assert killers_tp_ladder(str(tmp_path / "nope.sqlite")) == {}

def test_tp_ladder_next_falls_back_to_pending(tmp_path):
    db = tmp_path / "r2.sqlite"
    conn = sqlite3.connect(str(db))
    conn.executescript("CREATE TABLE positions (pos_id INTEGER, ft_trade_id INTEGER, state TEXT);"
                       "CREATE TABLE target_orders (target_id INTEGER PRIMARY KEY, pos_id INTEGER, idx INTEGER, price REAL, state TEXT);")
    conn.execute("INSERT INTO positions VALUES (1, 7, 'open')")
    conn.execute("INSERT INTO target_orders VALUES (1,1,0,5.0,'pending')")
    conn.execute("INSERT INTO target_orders VALUES (2,1,1,6.0,'pending')")
    conn.commit(); conn.close()
    assert killers_tp_ladder(str(db))[7] == {"tps_total": 2, "tps_hit": 0, "next_tp": 5.0}
