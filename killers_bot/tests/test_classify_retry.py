"""Falha de classificacao duravel, com nova tentativa e alerta (#95).

O que precisa ser provado:

- uma falha nao marca a mensagem como vista: ela fica na fila com o modo da
  falha, e uma passada posterior (ou um reinicio) a encaminha
- o encaminhamento acontece no maximo uma vez: nada que ja chegou ao receiver
  volta pela fila
- o operador e alertado, com msg_id e modo da falha, na 2a falha e ao desistir
- um `open` retido que foi superado por mensagem posterior do mesmo sinal nao
  e reaberto
- o classificador informa o modo de cada falha
"""
import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from killers_bot import classifier, classify_queue as cq, observer  # noqa: E402

SCHEMA = (ROOT / "killers_bot" / "schema.sql").read_text()
LOGIN_EXPIRED = "nonzero exit rc=1: Invalid API key · Please run /login"
FAR = time.time() + 10 * 86400       # depois de qualquer backoff


class _Cfg:
    """Sem fast-path nem regras: tudo vai ao Claude."""
    use_fast_path = False
    shadow_rules = False
    rules_primary = False
    receiver_url = "http://receiver.invalid/event"
    receiver_token = ""
    claude_binary = "claude"
    claude_model = None
    claude_timeout = 1
    classifier_template = None
    notify_url = "http://notify.invalid/test/notify"
    notify_token = ""
    feed_label = "killers"


MOVE_SL = {"kind": "move_sl", "symbol": "POL", "signal_id": 2143,
           "direction": "long", "sl": 0.09, "confidence": 0.95}


@pytest.fixture()
def env(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.executescript(SCHEMA)
    # post_results: um item por POST; None = 2xx, str = motivo da falha
    st = {"replies": [], "claude": [], "posted": [], "bodies": [], "alerts": [],
          "post_results": []}

    async def fake_chain(*a, **k):
        return []

    async def fake_claude(msg, chain, **k):
        st["claude"].append(msg["id"])
        reply = st["replies"].pop(0) if st["replies"] else None
        if isinstance(reply, str):          # modo de falha
            if k.get("on_failure"):
                k["on_failure"](reply)
            return None
        return dict(reply, id=msg["id"]) if reply else None

    async def fake_post(url, msg, cls, token=""):
        st["posted"].append((msg["id"], cls["kind"]))
        st["bodies"].append(json.loads(json.dumps(
            {"msg": msg, "classification": cls}, default=str)))
        return st["post_results"].pop(0) if st["post_results"] else None

    async def fake_notify(url, token, text):
        st["alerts"].append(text)
        return True

    monkeypatch.setattr(observer, "build_reply_chain", fake_chain)
    monkeypatch.setattr(observer.classifier, "classify", fake_claude)
    monkeypatch.setattr(observer, "_post_to_receiver", fake_post)
    # raising=False: contra o codigo anterior ao #95 o teste falha pelo
    # comportamento, nao por erro de fixture
    monkeypatch.setattr(observer, "_notify", fake_notify, raising=False)
    monkeypatch.setattr(observer.simulator, "open_paper_position", lambda *a: None)
    monkeypatch.setattr(observer.simulator, "update_paper_position", lambda *a: None)
    yield conn, st
    conn.close()


def _live(conn, cfg, mid, text="move stop to 0.09 on POL", source="new"):
    asyncio.run(observer.process_message(None, None, conn, cfg,
                                         {"id": mid, "text": text}, source))


def _retry(conn, cfg, now=FAR):
    return asyncio.run(observer.retry_due(None, None, conn, cfg, now=now))


def _row(conn, mid):
    return conn.execute(
        "SELECT state, attempts, last_error, next_retry_at FROM classify_queue "
        "WHERE msg_id = ?", (mid,)).fetchone()


# ── a falha e duravel ───────────────────────────────────────────────────────

def test_falha_fica_na_fila_com_o_modo_e_nada_e_encaminhado(env):
    conn, st = env
    st["replies"] = [LOGIN_EXPIRED]
    _live(conn, _Cfg(), 100)
    assert st["posted"] == []
    state, attempts, err, next_at = _row(conn, 100)
    assert (state, attempts) == (cq.RETRY, 1)
    assert "Please run /login" in err
    assert next_at == pytest.approx(time.time() + cq.BACKOFF_SEC[0], abs=5)
    # a mensagem crua continua gravada (auditoria), mas NAO conta como vista
    assert conn.execute("SELECT 1 FROM raw_messages WHERE msg_id = 100").fetchone()


def test_passada_posterior_encaminha_uma_vez(env):
    conn, st = env
    st["replies"] = [LOGIN_EXPIRED, MOVE_SL]
    cfg = _Cfg()
    _live(conn, cfg, 100)
    assert _retry(conn, cfg, now=time.time()) == 0     # backoff ainda nao venceu
    assert _retry(conn, cfg) == 1
    assert st["posted"] == [(100, "move_sl")]
    assert _row(conn, 100)[0] == cq.DONE
    assert conn.execute("SELECT kind FROM classifications WHERE msg_id = 100"
                        ).fetchone()[0] == "move_sl"
    # nada mais a fazer: nova passada nao reencaminha
    assert _retry(conn, cfg) == 0
    assert st["posted"] == [(100, "move_sl")]


def test_backoff_cresce_e_desiste_no_maximo(env):
    conn, st = env
    cfg = _Cfg()
    st["replies"] = [LOGIN_EXPIRED] * cq.DEFAULT_MAX_ATTEMPTS
    _live(conn, cfg, 100)
    for _ in range(cq.DEFAULT_MAX_ATTEMPTS - 1):
        assert _retry(conn, cfg) == 1
    state, attempts, _, next_at = _row(conn, 100)
    assert (state, attempts, next_at) == (cq.EXHAUSTED, cq.DEFAULT_MAX_ATTEMPTS, None)
    assert _retry(conn, cfg) == 0
    assert len(st["claude"]) == cq.DEFAULT_MAX_ATTEMPTS
    assert st["posted"] == []
    assert [cq.backoff(n) for n in (1, 2, 6, 9)] == [30, 120, 3600, 3600]


def test_reinicio_retoma_falha_pendente(env, tmp_path):
    _, st = env
    db = tmp_path / "state.sqlite"
    conn = observer.init_db(str(db))
    st["replies"] = [LOGIN_EXPIRED]
    _live(conn, _Cfg(), 100)
    conn.close()

    # novo processo: o cursor do backfill (MAX raw) ja passou de 100, mas a
    # fila nao esqueceu
    conn = observer.init_db(str(db))
    assert observer.last_msg_id(conn) == 100
    st["replies"] = [MOVE_SL]
    assert _retry(conn, _Cfg()) == 1
    assert st["posted"] == [(100, "move_sl")]
    conn.close()


def test_reinicio_retoma_mensagem_interrompida_no_meio(env, tmp_path):
    """O processo morreu durante a chamada ao Claude: a linha ficou
    `in_progress`. Na subida ela volta para a fila ja vencida."""
    _, st = env
    db = tmp_path / "state.sqlite"
    conn = observer.init_db(str(db))
    cq.begin(conn, 100, fresh=True, commit=False)
    observer.persist_raw(conn, {"id": 100, "text": "move stop to 0.09 on POL"})
    conn.close()

    conn = observer.init_db(str(db))
    assert cq.requeue_interrupted(conn) == 1
    st["replies"] = [MOVE_SL]
    assert _retry(conn, _Cfg(), now=time.time() + 1) == 1
    assert st["posted"] == [(100, "move_sl")]
    conn.close()


# ── no maximo uma vez no receiver ──────────────────────────────────────────

def test_excecao_depois_do_2xx_nao_reagenda(env, monkeypatch):
    conn, st = env
    st["replies"] = [MOVE_SL]

    async def boom(*a):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(observer, "_message_done", boom)
    _live(conn, _Cfg(), 100)
    assert st["posted"] == [(100, "move_sl")]
    state, _, err, _ = _row(conn, 100)
    assert state == cq.DONE and "after delivery" in err
    assert _retry(conn, _Cfg()) == 0
    assert st["posted"] == [(100, "move_sl")]


def _payload(conn, mid):
    return conn.execute("SELECT payload FROM classify_queue WHERE msg_id = ?",
                        (mid,)).fetchone()[0]


RECV_DOWN = "exhausted 3 fast attempts; last: HTTP 503: upstream down"


def test_entrega_sem_2xx_nao_e_done_e_reenvia_o_mesmo_corpo(env):
    """Revisao do #143: um close valido que o receiver nao confirmou nao pode
    sumir. Fica na fila com o corpo exato e e reenviado SEM reclassificar."""
    conn, st = env
    cfg = _Cfg()
    st["replies"] = [MOVE_SL]                     # o Claude responde UMA vez
    st["post_results"] = [RECV_DOWN, None]
    _live(conn, cfg, 100)
    state, attempts, err, _ = _row(conn, 100)
    assert (state, attempts) == (cq.RETRY, 1) and "HTTP 503" in err
    assert _payload(conn, 100) is not None

    assert _retry(conn, cfg) == 1
    assert st["claude"] == [100]                  # nao reclassificou
    assert st["posted"] == [(100, "move_sl"), (100, "move_sl")]
    assert st["bodies"][0] == st["bodies"][1]     # mesmo corpo, byte a byte
    assert _row(conn, 100)[0] == cq.DONE and _payload(conn, 100) is None
    assert _retry(conn, cfg) == 0


def test_4xx_deterministico_alerta_e_para_no_teto(env, tmp_path, capsys):
    from killers_bot.tools import requeue_classify
    _, st = env
    db = tmp_path / "state.sqlite"
    conn = observer.init_db(str(db))
    cfg = _Cfg()
    st["replies"] = [MOVE_SL]
    st["post_results"] = ["HTTP 401: invalid or missing ingress token"] * cq.DEFAULT_MAX_ATTEMPTS
    _live(conn, cfg, 100)
    for _ in range(cq.DEFAULT_MAX_ATTEMPTS - 1):
        assert _retry(conn, cfg) == 1
    state, attempts, err, _ = _row(conn, 100)
    assert (state, attempts) == (cq.EXHAUSTED, cq.DEFAULT_MAX_ATTEMPTS)
    assert "HTTP 401" in err
    assert _retry(conn, cfg) == 0                 # parou no teto
    assert len(st["posted"]) == cq.DEFAULT_MAX_ATTEMPTS
    assert st["claude"] == [100]
    assert len(st["alerts"]) == 2
    assert all("delivery FAILED" in a and "HTTP 401" in a for a in st["alerts"])
    assert "GAVE UP" in st["alerts"][1]

    # visivel na ferramenta, como etapa de entrega
    assert requeue_classify.main(["--db", str(db), "--list"]) == 0
    assert "100\texhausted\tdeliver" in capsys.readouterr().out
    # token corrigido; o operador reenfileira e o MESMO corpo e reenviado
    assert requeue_classify.main(["--db", str(db), "100"]) == 0
    assert _retry(conn, cfg) == 1
    assert st["claude"] == [100]
    assert st["bodies"][-1] == st["bodies"][0]
    assert _row(conn, 100)[0] == cq.DONE
    conn.close()


def test_queda_no_meio_do_post_reenvia_o_mesmo_corpo(env, tmp_path):
    """Resultado desconhecido: o corpo foi gravado e o processo morreu durante o
    POST. Na subida, reenvia o MESMO corpo; o receiver deduplica por msg_id."""
    _, st = env
    db = tmp_path / "state.sqlite"
    conn = observer.init_db(str(db))
    cq.begin(conn, 100, fresh=True, commit=False)
    observer.persist_raw(conn, {"id": 100, "text": "move stop to 0.09 on POL"})
    body = observer._receiver_body({"id": 100, "text": "move stop to 0.09 on POL"},
                                   dict(MOVE_SL, id=100))
    cq.set_payload(conn, 100, body)
    conn.close()

    conn = observer.init_db(str(db))
    assert cq.requeue_interrupted(conn) == 1
    assert _retry(conn, _Cfg(), now=time.time() + 1) == 1
    assert st["claude"] == []                     # nao reclassificou
    assert st["bodies"] == [json.loads(body)]
    assert _row(conn, 100)[0] == cq.DONE
    conn.close()


def test_edicao_descarta_entrega_pendente_e_reclassifica(env):
    conn, st = env
    cfg = _Cfg()
    st["replies"] = [MOVE_SL, dict(MOVE_SL, sl=0.091)]
    st["post_results"] = [RECV_DOWN, None]
    _live(conn, cfg, 100)
    _live(conn, cfg, 100, text="move stop to 0.091 on POL", source="edited")
    assert st["claude"] == [100, 100]
    assert st["bodies"][-1]["classification"]["sl"] == 0.091
    assert _row(conn, 100)[0] == cq.DONE
    assert _retry(conn, cfg) == 0


def test_open_em_reentrega_superado_nao_e_reaberto(env):
    conn, st = env
    cfg = _Cfg()
    open_cls = {"kind": "open", "symbol": "POL", "signal_id": 2143,
                "direction": "long", "confidence": 0.95}
    close_cls = {"kind": "close_full", "symbol": "POL", "signal_id": 2143,
                 "direction": "long", "confidence": 0.95}
    st["replies"] = [open_cls, close_cls]
    st["post_results"] = [RECV_DOWN, None]
    _live(conn, cfg, 100, text="POL long entry ...")
    _live(conn, cfg, 105, text="close POL")
    assert _retry(conn, cfg) == 1
    assert st["posted"] == [(100, "open"), (105, "close_full")]
    state, _, err, _ = _row(conn, 100)
    assert state == cq.DONE and "stale open NOT forwarded" in err


# ── _post_to_receiver informa o resultado ──────────────────────────────────

def _fake_aiohttp(script, calls):
    import types

    class _Resp:
        def __init__(self, status, body):
            self.status, self._body = status, body

        async def text(self):
            return self._body

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class _Session:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def post(self, url, **k):
            calls.append(k["data"])
            item = script.pop(0)
            if isinstance(item, Exception):
                raise item
            return _Resp(*item)

    return types.SimpleNamespace(ClientSession=_Session,
                                 ClientTimeout=lambda **k: None)


@pytest.mark.parametrize("script,ok,n_calls,expect", [
    ([(200, "ok")], True, 1, None),
    ([(401, "invalid token")], False, 1, "HTTP 401: invalid token"),
    ([(422, "bad payload")], False, 1, "HTTP 422"),
    ([(503, "down")] * 3, False, 3, "exhausted 3 fast attempts; last: HTTP 503"),
    ([ConnectionError("refused"), (200, "ok")], True, 2, None),
])
def test_post_to_receiver_devolve_o_resultado(monkeypatch, script, ok, n_calls, expect):
    calls = []
    monkeypatch.setitem(sys.modules, "aiohttp", _fake_aiohttp(list(script), calls))

    async def no_sleep(*a, **k):
        return None

    monkeypatch.setattr(observer.asyncio, "sleep", no_sleep)
    err = asyncio.run(observer._post_to_receiver(
        "http://receiver.invalid/event", {"id": 1}, {"kind": "close_full"}))
    assert (err is None) is ok and len(calls) == n_calls
    if expect:
        assert err.startswith(expect)


def test_excecao_antes_do_post_reagenda(env, monkeypatch):
    conn, st = env
    st["replies"] = [MOVE_SL, MOVE_SL]

    def boom(*a):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(observer.simulator, "update_paper_position", boom)
    _live(conn, _Cfg(), 100)
    assert st["posted"] == []
    state, attempts, err, _ = _row(conn, 100)
    assert (state, attempts) == (cq.RETRY, 1) and "disk I/O error" in err

    monkeypatch.setattr(observer.simulator, "update_paper_position", lambda *a: None)
    assert _retry(conn, _Cfg()) == 1
    assert st["posted"] == [(100, "move_sl")]


def test_edicao_ao_vivo_resolve_e_a_fila_nao_repete(env):
    conn, st = env
    st["replies"] = [LOGIN_EXPIRED, MOVE_SL]
    cfg = _Cfg()
    _live(conn, cfg, 100)
    _live(conn, cfg, 100, text="move stop to 0.091 on POL", source="edited")
    assert st["posted"] == [(100, "move_sl")]
    assert _row(conn, 100)[0] == cq.DONE
    assert _retry(conn, cfg) == 0
    assert st["posted"] == [(100, "move_sl")]


def test_retry_usa_a_versao_mais_recente_da_mensagem(env):
    conn, st = env
    st["replies"] = [LOGIN_EXPIRED, LOGIN_EXPIRED, MOVE_SL]
    cfg = _Cfg()
    _live(conn, cfg, 100, text="v1")
    _live(conn, cfg, 100, text="v2 editada", source="edited")
    seen = []
    orig = observer.classifier.classify

    async def spy(msg, chain, **k):
        seen.append(msg["text"])
        return await orig(msg, chain, **k)

    observer.classifier.classify = spy
    try:
        assert _retry(conn, cfg) == 1
    finally:
        observer.classifier.classify = orig
    assert seen == ["v2 editada"]


def test_open_retido_superado_por_mensagem_posterior_nao_e_reaberto(env):
    conn, st = env
    cfg = _Cfg()
    open_cls = {"kind": "open", "symbol": "POL", "signal_id": 2143,
                "direction": "long", "confidence": 0.95}
    close_cls = {"kind": "close_full", "symbol": "POL/USDT", "signal_id": 2143,
                 "direction": "long", "confidence": 0.95}
    st["replies"] = [LOGIN_EXPIRED, close_cls, open_cls]
    _live(conn, cfg, 100, text="POL long entry ...")
    _live(conn, cfg, 105, text="close POL")
    assert _retry(conn, cfg) == 1
    assert st["posted"] == [(105, "close_full")]
    state, _, err, _ = _row(conn, 100)
    assert state == cq.DONE and "stale open NOT forwarded" in err
    assert any("msg_id=100" in a and "Decide manually" in a for a in st["alerts"])


def test_open_retido_sem_mensagem_posterior_segue(env):
    conn, st = env
    cfg = _Cfg()
    st["replies"] = [LOGIN_EXPIRED, {"kind": "open", "symbol": "POL",
                                     "signal_id": 2143, "direction": "long",
                                     "confidence": 0.95}]
    _live(conn, cfg, 100)
    assert _retry(conn, cfg) == 1
    assert st["posted"] == [(100, "open")]


# ── alerta ─────────────────────────────────────────────────────────────────

def test_alerta_na_segunda_falha_com_msg_id_e_modo(env):
    conn, st = env
    cfg = _Cfg()
    st["replies"] = [LOGIN_EXPIRED, LOGIN_EXPIRED]
    _live(conn, cfg, 100)
    assert st["alerts"] == []              # 1a falha: transitoria, so log
    _retry(conn, cfg)
    assert len(st["alerts"]) == 1
    text = st["alerts"][0]
    assert "msg_id=100" in text and "Please run /login" in text
    assert "attempt 2/7" in text and "1 retrying" in text


def test_alerta_ao_desistir_e_aviso_de_recuperacao(env):
    conn, st = env
    cfg = _Cfg()
    st["replies"] = [LOGIN_EXPIRED] * cq.DEFAULT_MAX_ATTEMPTS
    _live(conn, cfg, 100)
    for _ in range(cq.DEFAULT_MAX_ATTEMPTS - 1):
        _retry(conn, cfg)
    assert len(st["alerts"]) == 2 and "GAVE UP" in st["alerts"][1]
    assert "requeue_classify" in st["alerts"][1]

    # operador reenfileira; o Claude voltou
    assert cq.requeue(conn, 100) is True
    assert cq.requeue(conn, 999) is False          # sem mensagem crua
    st["replies"] = [MOVE_SL]
    assert _retry(conn, cfg) == 1
    assert st["posted"] == [(100, "move_sl")]
    assert "nothing to replay" in st["alerts"][-1]


def test_sucesso_sem_falha_nao_alerta(env):
    conn, st = env
    st["replies"] = [MOVE_SL]
    _live(conn, _Cfg(), 100)
    assert st["alerts"] == [] and st["posted"] == [(100, "move_sl")]


def test_limite_de_alertas_por_hora(env):
    _, st = env
    cfg = _Cfg()

    async def go():
        return [await observer._alert(cfg, f"a{i}") for i in range(observer.ALERTS_PER_HOUR + 2)]

    sent = asyncio.run(go())
    assert sent.count(True) == observer.ALERTS_PER_HOUR
    assert len(st["alerts"]) == observer.ALERTS_PER_HOUR
    cfg._alert_times.clear()               # a janela de uma hora passou
    assert asyncio.run(observer._alert(cfg, "depois")) is True
    assert "+2 alert(s) suppressed" in st["alerts"][-1]


def test_sem_url_de_alerta_nao_quebra(env):
    _, st = env
    cfg = _Cfg()
    cfg.notify_url = ""
    assert asyncio.run(observer._alert(cfg, "x")) is False
    assert st["alerts"] == []


def test_timeout_padrao_cobre_a_latencia_medida(monkeypatch):
    monkeypatch.setattr(observer, "_load_dotenv", lambda: None)
    for k, v in (("KILLERS_TG_API_ID", "1"), ("KILLERS_TG_API_HASH", "h"),
                 ("KILLERS_TG_SESSION", "/tmp/s")):
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("KILLERS_CLAUDE_TIMEOUT_SEC", raising=False)
    assert observer.Config().claude_timeout == 20


# ── o classificador informa o modo da falha ────────────────────────────────

def _fake_cli(tmp_path, body: str) -> str:
    script = tmp_path / "fake_claude.py"
    script.write_text(body)
    return f"{sys.executable} {script}"


def _classify(binary, timeout=5.0):
    reasons = []
    out = asyncio.run(classifier.classify({"id": 7, "text": "x"}, [],
                                          binary=binary, timeout_sec=timeout,
                                          on_failure=reasons.append))
    return out, reasons


@pytest.mark.parametrize("body,expected", [
    ("import json,sys\nprint(json.dumps({'is_error': True, 'result': "
     "'Invalid API key · Please run /login'}))\nsys.exit(1)\n",
     "nonzero exit rc=1: Invalid API key · Please run /login"),
    ("import sys\nsys.stderr.write('boom')\nsys.exit(2)\n", "nonzero exit rc=2: boom"),
    ("print('sorry, no json here')\n", "no JSON in response"),
    ("import json\nprint(json.dumps({'result': json.dumps({'symbol': 'BTC'})}))\n",
     "response has no 'kind'"),
    ("import time\ntime.sleep(5)\n", "timeout after"),
])
def test_classificador_informa_o_modo(tmp_path, body, expected):
    out, reasons = _classify(_fake_cli(tmp_path, body), timeout=1.0)
    assert out is None
    assert len(reasons) == 1 and reasons[0].startswith(expected)


def test_classificador_binario_ausente(tmp_path):
    out, reasons = _classify(str(tmp_path / "nao-existe"))
    assert out is None and reasons[0].startswith("binary not found")


def test_classificador_sucesso_nao_chama_on_failure(tmp_path):
    body = ("import json\nprint(json.dumps({'result': json.dumps("
            "{'kind': 'chat', 'confidence': 0.9})}))\n")
    out, reasons = _classify(_fake_cli(tmp_path, body))
    assert out == {"kind": "chat", "confidence": 0.9, "id": 7} and reasons == []


# ── ferramenta do operador ─────────────────────────────────────────────────

def test_ferramenta_lista_e_reenfileira(env, tmp_path, capsys):
    from killers_bot.tools import requeue_classify
    _, st = env
    db = tmp_path / "state.sqlite"
    conn = observer.init_db(str(db))
    st["replies"] = [LOGIN_EXPIRED] * cq.DEFAULT_MAX_ATTEMPTS
    _live(conn, _Cfg(), 100)
    for _ in range(cq.DEFAULT_MAX_ATTEMPTS - 1):
        _retry(conn, _Cfg())
    assert _row(conn, 100)[0] == cq.EXHAUSTED

    assert requeue_classify.main(["--db", str(db), "--list"]) == 0
    assert "100\texhausted" in capsys.readouterr().out
    assert requeue_classify.main(["--db", str(db), "100", "555"]) == 1
    assert _row(conn, 100)[:2] == (cq.RETRY, 0)
    assert cq.due(conn, time.time() + 1) == [100]
    conn.close()
