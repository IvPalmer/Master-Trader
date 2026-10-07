"""Widget contract v1: the single validator (spec: The widget contract, A1).

The gateway runs it on every app response at the boundary; each app keeps an
unchanged copy for its conformance test. Stdlib only. Beyond the shapes, it
checks that default_view is one of views, that widget and action ids are
unique, that a payload's id is the widget asked for, that a payload carries
only views its catalog entry lists, that an item's actions exist in its
catalog entry, and that as_of is a real instant. A catalog's version is
judged before its shape, so a newer contract reads as an unknown version.

Errors name a path ("data.list.groups[0].items[3].title: empty"), never a
value: these lines go to the gateway log and payloads are private.
"""
from __future__ import annotations

import math
import re
from datetime import datetime

CONTRACTS = frozenset({1})
APP_RE = re.compile(r"[a-z][a-z0-9]{0,15}")
ID_RE = re.compile(r"[a-z][a-z0-9_]{0,31}")
AS_OF_RE = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})"
    r"(?:\.[0-9]+)?(?:Z|[+-]([0-9]{2}):([0-9]{2}))")
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
VIEWS = ("stat", "list", "spark", "alert")
TONES = ("neutral", "good", "warn", "bad")
RISKS = ("low", "medium", "high")
RISK_RANK = {"low": 0, "medium": 1, "high": 2}
MAX_STR = 500
MAX_PAYLOAD = 256 * 1024
REFRESH_MIN, REFRESH_MAX = 30, 86400

# view → (required keys, optional keys)
_VIEW_KEYS = {
    "stat": (("value", "label"), ("delta", "tone")),
    "list": (("groups",), ()),
    "spark": (("label", "points"), ("unit",)),
    "alert": (("text", "tone"), ()),
}


class ContractError(ValueError):
    """One reason a document breaks contract v1."""


class UnknownContract(ContractError):
    """A catalog speaking a contract version this gateway does not know."""

    def __init__(self, version) -> None:
        super().__init__("catalog.contract: unknown version")
        self.version = version


def _key(k) -> str:
    """An app-chosen key name for an error line: quoted, so a newline cannot
    start a log line of its own, and cut short."""
    r = repr(k)
    return r if len(r) <= 40 else r[:40] + "..."


def _obj(v, where: str, required: tuple, optional: tuple = ()) -> dict:
    if not isinstance(v, dict):
        raise ContractError(f"{where}: not an object")
    missing = [k for k in required if k not in v]
    if missing:
        raise ContractError(f"{where}: missing {', '.join(missing)}")
    extra = sorted(set(v) - set(required) - set(optional))
    if extra:
        raise ContractError(f"{where}: unknown key {_key(extra[0])}")
    return v


def _str(v, where: str, *, empty: bool = False) -> str:
    if not isinstance(v, str):
        raise ContractError(f"{where}: not a string")
    if len(v) > MAX_STR:
        raise ContractError(f"{where}: longer than {MAX_STR} characters")
    if not empty and not v:
        raise ContractError(f"{where}: empty")
    try:
        v.encode("utf-8")
    except UnicodeEncodeError:  # a lone surrogate, which json.loads accepts
        raise ContractError(f"{where}: not valid UTF-8") from None
    return v


def _int(v, where: str, lo: int, hi: int) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ContractError(f"{where}: not an integer in {lo}..{hi}")
    return v


def _enum(v, where: str, allowed: tuple) -> str:
    if not isinstance(v, str) or v not in allowed:
        raise ContractError(f"{where}: not one of {', '.join(allowed)}")
    return v


def _list(v, where: str, lo: int, hi: int | None) -> list:
    if not isinstance(v, list) or len(v) < lo or (hi is not None and len(v) > hi):
        bound = f"{lo}..{hi}" if hi is not None else f"at least {lo}"
        raise ContractError(f"{where}: not a list of {bound}")
    return v


def _pattern(v, where: str, rx: re.Pattern) -> str:
    if not isinstance(v, str) or not rx.fullmatch(v):
        raise ContractError(f"{where}: bad format")
    return v


def _finite(v) -> bool:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return False
    try:
        return math.isfinite(v)
    except OverflowError:  # an int past float range: json.loads accepts it
        return False


def _as_of(v, where: str) -> str:
    """RFC 3339 with an offset, and a real instant: month 13 or hour 24 is no
    timestamp. Second 60 is allowed (a leap second)."""
    if isinstance(v, str) and len(v) > MAX_STR:    # the fraction is unbounded
        raise ContractError(f"{where}: longer than {MAX_STR} characters")
    m = AS_OF_RE.fullmatch(v) if isinstance(v, str) else None
    if not m:
        raise ContractError(f"{where}: bad format")
    year, month, day, hour, minute, second, off_h, off_m = m.groups()
    try:
        datetime(int(year), int(month), int(day))
    except ValueError:
        raise ContractError(f"{where}: not a real date") from None
    if (int(hour) > 23 or int(minute) > 59 or int(second) > 60
            or (off_h is not None and (int(off_h) > 23 or int(off_m) > 59))):
        raise ContractError(f"{where}: not a real time")
    return v


def _unique(values: list, where: str) -> None:
    if len(set(values)) != len(values):
        raise ContractError(f"{where}: repeated")


def check_catalog(doc, app: str) -> dict:
    """A catalog from the app registered as `app`."""
    # The version comes first: a catalog from a newer contract may well have a
    # shape this validator does not know, and must still read as "unavailable:
    # speaks contract N", not as a broken catalog.
    version = doc.get("contract") if isinstance(doc, dict) else None
    if isinstance(version, int) and not isinstance(version, bool) and version not in CONTRACTS:
        raise UnknownContract(version)
    _obj(doc, "catalog", ("contract", "app", "widgets"))
    if isinstance(version, bool) or not isinstance(version, int):
        raise ContractError("catalog.contract: not an integer")
    _pattern(doc["app"], "catalog.app", APP_RE)
    if doc["app"] != app:
        raise ContractError(f"catalog.app: not the name it is registered as ({app})")
    ids: list[str] = []
    for i, w in enumerate(_list(doc["widgets"], "catalog.widgets", 0, None)):
        where = f"catalog.widgets[{i}]"
        _obj(w, where, ("id", "title", "views", "default_view", "refresh_s", "actions"))
        ids.append(_pattern(w["id"], f"{where}.id", ID_RE))
        _str(w["title"], f"{where}.title")
        views = _list(w["views"], f"{where}.views", 1, len(VIEWS))
        for v in views:
            _enum(v, f"{where}.views", VIEWS)
        _unique(views, f"{where}.views")
        _enum(w["default_view"], f"{where}.default_view", VIEWS)
        if w["default_view"] not in views:
            raise ContractError(f"{where}.default_view: not one of its views")
        _int(w["refresh_s"], f"{where}.refresh_s", REFRESH_MIN, REFRESH_MAX)
        action_ids: list[str] = []
        for j, a in enumerate(_list(w["actions"], f"{where}.actions", 0, None)):
            aw = f"{where}.actions[{j}]"
            _obj(a, aw, ("id", "label", "scope", "risk"), ("confirm",))
            action_ids.append(_pattern(a["id"], f"{aw}.id", ID_RE))
            _str(a["label"], f"{aw}.label")
            _enum(a["scope"], f"{aw}.scope", ("item",))
            _enum(a["risk"], f"{aw}.risk", RISKS)
            if "confirm" in a:
                _str(a["confirm"], f"{aw}.confirm")
        _unique(action_ids, f"{where}.actions")
    _unique(ids, "catalog.widgets")
    return doc


def _check_list(body: dict, actions: set[str]) -> None:
    for gi, g in enumerate(_list(body["groups"], "data.list.groups", 0, 10)):
        gw = f"data.list.groups[{gi}]"
        _obj(g, gw, ("title", "items"))
        _str(g["title"], f"{gw}.title", empty=True)
        for ii, it in enumerate(_list(g["items"], f"{gw}.items", 0, 100)):
            iw = f"{gw}.items[{ii}]"
            _obj(it, iw, ("key", "title"), ("subtitle", "detail", "tone", "actions", "url"))
            _str(it["key"], f"{iw}.key")
            _str(it["title"], f"{iw}.title")
            for k in ("subtitle", "detail"):
                if k in it:
                    _str(it[k], f"{iw}.{k}")
            if "tone" in it:
                _enum(it["tone"], f"{iw}.tone", TONES)
            if "url" in it and not _str(it["url"], f"{iw}.url").startswith("https://"):
                raise ContractError(f"{iw}.url: not https")
            if "actions" in it:
                ids = _list(it["actions"], f"{iw}.actions", 1, None)
                for a in ids:
                    _pattern(a, f"{iw}.actions", ID_RE)
                    if a not in actions:
                        raise ContractError(f"{iw}.actions: an action the catalog does not list")
                _unique(ids, f"{iw}.actions")


def check_data(doc, entry: dict) -> dict:
    """A payload for the catalog entry `entry` (already checked)."""
    _obj(doc, "data", ("id", "title", "as_of"), ("tone",) + VIEWS)
    if doc["id"] != entry["id"]:
        raise ContractError("data.id: not the widget asked for")
    _str(doc["title"], "data.title")
    _as_of(doc["as_of"], "data.as_of")
    if "tone" in doc:
        _enum(doc["tone"], "data.tone", TONES)
    actions = {a["id"] for a in entry["actions"]}
    for view in VIEWS:
        if view not in doc:
            continue
        if view not in entry["views"]:
            raise ContractError(f"data.{view}: a view the catalog does not list")
        required, optional = _VIEW_KEYS[view]
        body = _obj(doc[view], f"data.{view}", required, optional)
        if view == "stat":
            _str(body["value"], "data.stat.value")
            _str(body["label"], "data.stat.label")
            if "delta" in body:
                _str(body["delta"], "data.stat.delta")
            if "tone" in body:
                _enum(body["tone"], "data.stat.tone", TONES)
        elif view == "list":
            _check_list(body, actions)
        elif view == "spark":
            _str(body["label"], "data.spark.label")
            for p in _list(body["points"], "data.spark.points", 2, 500):
                if not _finite(p):
                    raise ContractError("data.spark.points: not a finite number")
            if "unit" in body:
                _str(body["unit"], "data.spark.unit")
        else:
            _str(body["text"], "data.alert.text")
            _enum(body["tone"], "data.alert.tone", TONES)
    return doc


def check_action_request(doc) -> dict:
    _obj(doc, "request", ("key", "request_id"))
    _str(doc["key"], "request.key")
    _pattern(doc["request_id"], "request.request_id", UUID_RE)
    return doc


def check_action_response(doc) -> dict:
    _obj(doc, "result", ("ok", "message", "refresh"))
    if not isinstance(doc["ok"], bool):
        raise ContractError("result.ok: not a boolean")
    _str(doc["message"], "result.message", empty=True)
    if not isinstance(doc["refresh"], bool):
        raise ContractError("result.refresh: not a boolean")
    return doc
