"""Part C title and body classifiers (#229): pure, outcome-blind rules (O8–O10, O12, O17).

    python3 -m pytest tests/test_news_event_studies_classify.py -q
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "research" / "news_event_studies"))

import nes_classify as nc  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "news_event_studies"


@pytest.mark.parametrize("title,tokens", [
    ("원화 마켓 신규 상장 (이오스 EOS)", ("EOS",)),
    ("원화 마켓 디지털 자산 추가 (AXS, STX, FLOW, DAWN)", ("AXS", "STX", "FLOW", "DAWN")),
    ("KRW, BTC 마켓 디지털 자산 추가 (SOL, MATIC, NU)", ("SOL", "MATIC", "NU")),
    ("닐리온(NIL) KRW 마켓 디지털 자산 추가", ("NIL",)),
    ("콘크리트(CT) 신규 거래지원 안내 (KRW, BTC, USDT 마켓)", ("CT",)),
    ("액시스로보틱스(AXIS) 신규 거래지원 안내 (KRW, BTC, USDT 마켓) (매도 최저가 기준 가격 안내)",
     ("AXIS",)),
    ("에이(AAA), 비(BBB) KRW 마켓 디지털 자산 추가", ("AAA", "BBB")),
    ("BTC, USDT 마켓 디지털 자산 추가 (ABC)", None),
])
def test_upbit_addition_formats(title, tokens):
    assert nc.upbit_addition(title) == tokens


@pytest.mark.parametrize("word", ["종료", "유의", "제거", "변경", "중단", "연기", "재개"])
def test_upbit_exclude_words(word):
    assert nc.upbit_addition(f"닐리온(NIL) KRW 마켓 디지털 자산 추가 {word}") is None


def test_exclude_words_constant():
    assert nc.EXCLUDE_WORDS == ("종료", "유의", "제거", "변경", "중단", "연기", "재개")


def test_upbit_end_and_market_specific_end():
    assert nc.upbit_end("닐리온(NIL) 거래지원 종료 안내") == ("NIL",)
    assert nc.upbit_end("닐리온(NIL) 상장폐지 안내") == ("NIL",)
    assert nc.upbit_end("닐리온(NIL) KRW 마켓 거래지원 종료 안내") == ("NIL",)
    assert nc.upbit_end("닐리온(NIL) BTC 마켓 거래지원 종료 안내") is None
    assert nc.upbit_end("닐리온(NIL) BTC, USDT 마켓 거래지원 종료 안내") is None
    assert nc.upbit_end("닐리온(NIL) 거래지원 종료 연기 안내") is None
    assert nc.upbit_end("닐리온(NIL) 거래지원 종료 결정 철회 안내") is None
    assert nc.upbit_end("닐리온(NIL) KRW 및 BTC 마켓 거래지원 종료 안내") == ("NIL",)
    assert nc.upbit_end("닐리온(NIL) KRW와 BTC 마켓 거래지원 종료 안내") == ("NIL",)
    assert nc.upbit_end("닐리온(NIL) 거래지원 종료 취소 안내") is None
    assert nc.upbit_end("닐리온(NIL) KRW 마켓 디지털 자산 추가") is None


def test_upbit_needs_review():
    assert nc.upbit_needs_review("닐리온(NIL) KRW 마켓 입금 안내") is True
    assert nc.upbit_needs_review("닐리온(NIL) KRW 마켓 디지털 자산 추가") is False
    assert nc.upbit_needs_review("닐리온(NIL) 거래지원 종료 안내") is False
    assert nc.upbit_needs_review("닐리온(NIL) KRW 마켓 거래 유의 안내") is False   # exclude word
    assert nc.upbit_needs_review("닐리온(NIL) BTC 마켓 입금 안내") is False        # no KRW marker


T_START = 1793089800000      # 2026-10-27T08:30Z = 17:30 KST


@pytest.mark.parametrize("body", [
    "거래지원 개시 시점 : 2026년 10월 27일 17:30 KST",
    "- 거래 지원 개시 시점: 2026-10-27 17:30",
    "거래지원 개시 시점: 2026.10.27 17:30",
    "거래 오픈 : 2026년 10월 27일 17시 30분",
    "거래지원 개시 시점 : 10월 27일 오후 5시 30분 예정",
])
def test_upbit_trading_start_line_formats(body):
    assert nc.upbit_trading_start_ms(body, "NIL", T_START) == T_START


def test_upbit_trading_start_missing_line_is_none():
    body = "* 입출금 서비스 개시 이후, 일정 수준의 유동성을 확보하지 못하는 경우 거래지원 개시 시점이 연기될 수 있습니다."
    assert nc.upbit_trading_start_ms(body, "NIL", T_START) is None


def test_upbit_trading_start_from_table_row_of_token():
    body = json.loads((FIX / "upbit_detail.json").read_text(encoding="utf-8"))["data"]["body"]
    t0 = 1709294430000              # 2024-03-01T12:00:30Z = 21:00:30 KST
    assert nc.upbit_trading_start_ms(body, "TST", t0) == 1709296200000   # 21:30 KST
    assert nc.upbit_trading_start_ms(body, "OTHER", t0) is None


def test_upbit_trading_start_table_picks_the_tokens_row():
    body = ("<table><thead><tr><th>디지털 자산</th><th>마켓</th><th>거래지원 개시 시점</th></tr></thead>"
            "<tbody><tr><td>에이(AAA)</td><td>KRW</td><td>3월 1일 21시 30분 예정</td></tr>"
            "<tr><td>비(BBB)</td><td>KRW</td><td>3월 1일 20시 00분 예정</td></tr></tbody></table>")
    t0 = 1709294430000
    assert nc.upbit_trading_start_ms(body, "AAA", t0) == 1709296200000
    assert nc.upbit_trading_start_ms(body, "BBB", t0) == 1709290800000   # 20:00 KST, before t0


def test_upbit_trading_start_conflicting_lines_is_none():
    body = "거래지원 개시 시점: 2026-10-27 17:30\n거래 오픈 : 2026-10-27 18:00"
    assert nc.upbit_trading_start_ms(body, "NIL", T_START) is None


def test_upbit_trading_start_mixed_year_and_yearless_is_none():
    body = "거래지원 개시 시점: 2026년 10월 27일 17:30 또는 10월 27일 18:00"
    assert nc.upbit_trading_start_ms(body, "NIL", T_START) is None


def test_upbit_trading_start_rowspan_and_weekday():
    body = ("<table><tr><th>디지털 자산</th><th>마켓</th><th>거래지원 개시 시점</th></tr>"
            "<tr><td>에이(AAA)</td><td>KRW</td><td rowspan=\"2\">2024년 3월 1일(금) 21:30</td></tr>"
            "<tr><td>비(BBB)</td><td>KRW</td></tr></table>")
    assert nc.upbit_trading_start_ms(body, "BBB", 1709294430000) == 1709296200000


def test_upbit_trading_start_table_without_token_ignores_lines():
    body = ("<table><tr><th>디지털 자산</th><th>거래지원 개시 시점</th></tr>"
            "<tr><td>에이(AAA)</td><td>3월 1일 21시 30분</td></tr></table>\n"
            "거래 오픈 : 2024-03-01 20:00")
    assert nc.upbit_trading_start_ms(body, "BBB", 1709294430000) is None


AB_TITLE = "에이(AAA), 비(BBB) KRW 마켓 디지털 자산 추가"
AB_T0 = 1709294430000               # 2024-03-01 21:00:30 KST
AT_20 = 1709290800000               # 2024-03-01 20:00 KST, before t0


def test_upbit_start_lines_do_not_borrow_another_tokens_time():
    body = "AAA 거래지원 개시 시점: 2024-03-01 20:00\nBBB 거래지원 개시 시점: 추후 공지"
    assert nc.upbit_trading_start_ms(body, "AAA", AB_T0, AB_TITLE) == AT_20
    assert nc.upbit_trading_start_ms(body, "BBB", AB_T0, AB_TITLE) is None       # no parseable start
    # A token-less start line next to token-specific ones has no clear scope: it is not borrowed.
    body += "\n거래지원 개시 시점: 2024-03-01 21:30"
    assert nc.upbit_trading_start_ms(body, "AAA", AB_T0, AB_TITLE) == AT_20
    assert nc.upbit_trading_start_ms(body, "BBB", AB_T0, AB_TITLE) is None


def test_upbit_korean_start_lines_do_not_borrow_time():
    body = "에이 거래지원 개시 시점: 2024-03-01 20:00\n비 거래지원 개시 시점: 추후 공지"
    assert nc.upbit_trading_start_ms(body, "AAA", AB_T0, AB_TITLE) == AT_20
    assert nc.upbit_trading_start_ms(body, "BBB", AB_T0, AB_TITLE) is None
    # A name inside a longer word is not that token: "서비스" does not name 비.
    body = "에이 거래지원 개시 시점: 2024-03-01 20:00\n입출금 서비스 거래지원 개시 시점: 2024-03-01 21:30"
    assert nc.upbit_trading_start_ms(body, "BBB", AB_T0, AB_TITLE) is None
    # The "(name TICKER)" title form gives a name too.
    body = "이오스 거래지원 개시 시점: 2024-03-01 20:00\n에이 거래지원 개시 시점: 추후 공지"
    assert nc.upbit_trading_start_ms(body, "AAA", AB_T0, "원화 마켓 신규 상장 (이오스 EOS, 에이 AAA)") is None
    assert nc.upbit_trading_start_ms(body, "EOS", AB_T0, "원화 마켓 신규 상장 (이오스 EOS, 에이 AAA)") == AT_20


@pytest.mark.parametrize("body", [
    "<h3>AAA</h3><p>거래지원 개시 시점: 2024-03-01 20:00</p>\n<h3>BBB</h3><p>거래지원 개시 시점: 추후 공지</p>",
    "<p><strong>에이(AAA)</strong></p><p>거래지원 개시 시점: 2024-03-01 20:00</p>"
    "<p><strong>비(BBB)</strong></p><p>거래지원 개시 시점: 추후 공지</p>",
    "디지털 자산: 에이(AAA)\n거래지원 개시 시점: 2024-03-01 20:00\n"
    "디지털 자산: 비(BBB)\n거래지원 개시 시점: 추후 공지",
    "<p>AAA 안내<h3>BBB</h3>거래지원 개시 시점: 추후 공지</p>"
    "<h3>AAA</h3><p>거래지원 개시 시점: 2024-03-01 20:00</p>",
])
def test_upbit_token_headings_do_not_borrow_time(body):
    # Headings and labels do not scope a start line (round 3): the declarations name no token
    # and one is not parseable, so neither token has a stated start. Fail closed.
    assert nc.upbit_trading_start_ms(body, "AAA", AB_T0, AB_TITLE) is None
    assert nc.upbit_trading_start_ms(body, "BBB", AB_T0, AB_TITLE) is None


AT_2130 = 1709296200000             # 2024-03-01 21:30 KST


def test_upbit_table_without_start_column_then_shared_line():
    body = ("<table><tr><th>디지털 자산/마켓</th></tr><tr><td>AAA/KRW</td></tr><tr><td>BBB/KRW</td></tr>"
            "</table>\n<p>거래지원 개시 시점: 2024-03-01 21:30</p>")
    for tok in ("AAA", "BBB"):
        assert nc.upbit_trading_start_ms(body, tok, AB_T0, AB_TITLE) == AT_2130


def test_upbit_common_section_shared_start():
    body = ("<h3>AAA</h3><p>AAA 입출금 안내</p><h3>BBB</h3><p>BBB 입출금 안내</p>"
            "<h3>공통 안내</h3><p>거래지원 개시 시점: 2024-03-01 21:30</p>")
    for tok in ("AAA", "BBB"):
        assert nc.upbit_trading_start_ms(body, tok, AB_T0, AB_TITLE) == AT_2130


def test_upbit_dateless_caveat_keeps_shared_start():
    body = ("<p>거래지원 개시 시점: 2024-03-01 21:30</p><h3>에이(AAA)</h3><p>입출금 안내</p>"
            "<p>* 거래지원 개시 시점이 연기될 수 있습니다.</p>")
    for tok in ("AAA", "BBB"):
        assert nc.upbit_trading_start_ms(body, tok, AB_T0, AB_TITLE) == AT_2130


@pytest.mark.parametrize("extra,expected", [("거래 오픈: 2024-03-01 21:30", AT_2130),
                                            ("거래 오픈: 2024-03-01 22:00", None),
                                            ("거래 오픈: 추후 공지", None)])
def test_upbit_tokenless_declarations_must_agree(extra, expected):
    body = "거래지원 개시 시점: 2024-03-01 21:30\n" + extra
    for tok in ("AAA", "BBB"):
        assert nc.upbit_trading_start_ms(body, tok, AB_T0, AB_TITLE) == expected


def test_upbit_korean_particles_name_the_token():
    title = "스택스(STX), 플로우(FLOW) KRW 마켓 디지털 자산 추가"
    body = "스택스의 거래지원 개시 시점: 2024-03-01 20:00\n플로우의 거래지원 개시 시점: 추후 공지"
    assert nc.upbit_trading_start_ms(body, "STX", AB_T0, title) == AT_20
    assert nc.upbit_trading_start_ms(body, "FLOW", AB_T0, title) is None
    body = "스택스는 거래지원 개시 시점: 2024-03-01 20:00\n플로우에서 거래 오픈: 2024-03-01 21:30"
    assert nc.upbit_trading_start_ms(body, "FLOW", AB_T0, title) == AT_2130


def test_upbit_name_prefix_of_other_word_does_not_match():
    # 비 (BBB) is not named by 비트코인: with no declaration naming a token, the line is shared.
    body = "비트코인 마켓 거래지원 개시 시점: 2024-03-01 21:30"
    assert nc.upbit_trading_start_ms(body, "AAA", AB_T0, AB_TITLE) == AT_2130
    assert nc.upbit_trading_start_ms(body, "BBB", AB_T0, AB_TITLE) == AT_2130
    body = "에이 거래지원 개시 시점: 2024-03-01 20:00\n비트코인 거래지원 개시 시점: 2024-03-01 21:30"
    assert nc.upbit_trading_start_ms(body, "BBB", AB_T0, AB_TITLE) is None


def test_upbit_single_token_notice_reads_every_start_line():
    body = "거래지원 개시 시점: 2024-03-01 20:00\n에이(AAA) 안내\n거래 오픈: 2024-03-01 21:30"
    assert nc.upbit_trading_start_ms(body, "AAA", AB_T0, "에이(AAA) KRW 마켓 디지털 자산 추가") is None
    body = "거래지원 개시 시점: 2024-03-01 20:00\n에이(AAA) 안내"
    assert nc.upbit_trading_start_ms(body, "AAA", AB_T0, "에이(AAA) KRW 마켓 디지털 자산 추가") == AT_20


def test_upbit_shared_start_line_applies_to_every_token():
    body = ("에이(AAA), 비(BBB) KRW 마켓 추가\n거래지원 개시 시점: 2024-03-01 21:30 KST\n"
            "* 거래지원 개시 시점이 연기될 수 있습니다.")
    for tok in ("AAA", "BBB"):
        assert nc.upbit_trading_start_ms(body, tok, AB_T0, AB_TITLE) == 1709296200000   # 21:30 KST
        assert nc.upbit_trading_start_ms(body, tok, AB_T0) == 1709296200000
    # A single token-less start line with no token named anywhere is shared too.
    body = "거래지원 개시 시점: 2024-03-01 21:30\n* 거래지원 개시 시점이 연기될 수 있습니다."
    for tok in ("AAA", "BBB"):
        assert nc.upbit_trading_start_ms(body, tok, AB_T0, AB_TITLE) == 1709296200000


def test_upbit_trading_start_year_nearest_t0():
    t0 = 1704036600000             # 2023-12-31T15:30Z = 2024-01-01 00:30 KST
    assert nc.upbit_trading_start_ms("거래지원 개시 시점: 12월 31일 23시 50분", "X", t0) == \
        1704034200000              # 2023-12-31 23:50 KST
    assert nc.upbit_trading_start_ms("거래지원 개시 시점: 1월 1일 01:00", "X", t0) == \
        1704038400000              # 2024-01-01 01:00 KST


def test_upbit_trading_start_invalid_date_is_none():
    assert nc.upbit_trading_start_ms("거래지원 개시 시점: 2월 30일 10:00", "X", T_START) is None


@pytest.mark.parametrize("title,kind,tokens", [
    ("Binance Will Delist EPIC, QUICK on 2026-10-28", "full_delist", ("EPIC", "QUICK")),
    ("Binance Will Delist BTCST, DREP, MOB & SNM on 2024-04-10", "full_delist",
     ("BTCST", "DREP", "MOB", "SNM")),
    ("Binance Will Delist ABC and DEF on 2024-04-10", "full_delist", ("ABC", "DEF")),
    ("Binance Will Delist XYZ", "full_delist", ("XYZ",)),
    ("Binance Will Delist Ankr (ANKR) on 2024-04-10", "unclassified", ()),
    ("Binance Will Extend the Monitoring Tag to Include ACT, BLUR, PIVX & QKC on 2026-06-18",
     "monitoring_add", ("ACT", "BLUR", "PIVX", "QKC")),
    ("Binance Will Extend the Monitoring Tag to Include ABC and Remove the Monitoring Tag on XYZ on 2026-01-02",
     "monitoring_add", ("ABC",)),
    ("Binance Will Add Monitoring Tag to ABC, DEF on 2024-01-05", "monitoring_add",
     ("ABC", "DEF")),
    ("Binance Will Remove the Monitoring Tag on XYZ on 2026-01-02", "excluded:tag_removal", ()),
    ("Notice of Removal of Spot Trading Pairs - 2026-10-31", "excluded:pair_removal", ()),
    ("Binance Will Delist ABC/USDT on 2024-01-01", "excluded:pair_removal", ()),
    ("Binance Margin Will Delist ABC/USDT Cross Margin Pair", "excluded:margin", ()),
    ("Binance Futures Will Delist USDⓈ-M ABCUSDT Perpetual Contract", "excluded:futures", ()),
    ("Binance Will Delist ABCUP and ABCDOWN Leveraged Tokens", "excluded:leveraged", ()),
    ("Binance Options Will Delist ABC Options", "excluded:options", ()),
    ("Vote to Delist Results - 2026-03", "excluded:vote", ()),
    ("Binance Will Cancel the Delisting of ABC", "excluded:retraction", ()),
    ("Binance Will Delist ABC on 2024-03-10 (Cancelled)", "full_delist", ("ABC",)),
    ("Binance Will Delist ABC, DEF (Update)", "full_delist", ("ABC", "DEF")),
    ("Binance Simple Earn Will Delist ABC Products", "excluded:other_product", ()),
    ("Binance Updates Its Tokenomics Guidelines", "unclassified", ()),
])
def test_classify_binance(title, kind, tokens):
    assert nc.classify_binance(title) == nc.BinanceClass(kind, tokens)


def test_mentions_token():
    assert nc.mentions_token("Binance Will List Pepe (PEPE)", "PEPE")
    assert nc.mentions_token("Binance Futures Will Launch USDⓈ-M 1000PEPE Perpetual Contract", "PEPE")
    assert not nc.mentions_token("Binance Will Add APE on Earn", "PE")
    assert nc.mentions_token("Binance Will List ARKMUSDT Perpetual", "ARKM")
    assert not nc.mentions_token("Binance Will List ARKMX", "ARKM")
