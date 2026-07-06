"""
Self-contained smoke test for relingo.py.

Mocks pycurl (using the real pycurl module's integer option sentinels) so no
network access happens, then exercises every public function and the major
error paths.
"""

import json
import sys

import relingo

# Reach into the real pycurl for option sentinels (URL, POSTFIELDS, ...).
# Our mock objects accept any opt value; we just need the real integers to
# match what the SDK passes in.
try:
    import pycurl as _REAL_PYCURL
except Exception:  # pragma: no cover
    _REAL_PYCURL = None


# --- pycurl mock ------------------------------------------------------------

_RESPONSES = []  # queue of (status, body, raise) tuples
_REQUESTS = []   # list of dicts with the captured request details


def _is(opt, name):
    """Return True if ``opt`` matches the (real or fake) constant for ``name``."""
    if opt == getattr(_FakePycurl, name, None):
        return True
    real = getattr(_REAL_PYCURL, name, None)
    if real is not None and opt == real:
        return True
    return False


class _FakeCurl:
    def __init__(self):
        self._opts = {}
        self._status = 0
        self._body = None

    def setopt(self, opt, value):
        if _is(opt, "POSTFIELDS"):
            self._body = value
        self._opts[opt] = value

    def getinfo(self, opt):
        if _is(opt, "RESPONSE_CODE"):
            return self._status
        return None

    def perform(self):
        # Look up the URL, WRITEFUNCTION, and HTTPHEADER by their real/fake
        # sentinel values rather than hard-coding the mock's strings.
        url = None
        write = None
        headers = []
        for k, v in self._opts.items():
            if url is None and _is(k, "URL"):
                url = v
            elif write is None and _is(k, "WRITEFUNCTION"):
                write = v
            elif _is(k, "HTTPHEADER"):
                headers = v
        _REQUESTS.append({"url": url, "body": self._body, "headers": headers})

        if not _RESPONSES:
            raise RuntimeError("no queued response for " + str(url))
        status, resp_body, raise_ = _RESPONSES.pop(0)
        if raise_:
            raise raise_
        self._status = status
        if isinstance(resp_body, str):
            resp_body = resp_body.encode("utf-8")
        write(resp_body)

    def close(self):
        pass


class _FakePycurl:
    # These class attributes exist only so _is() has a fallback when
    # real pycurl is unavailable. Real pycurl integer constants take
    # precedence at lookup time.
    URL = "URL"
    POST = "POST"
    POSTFIELDS = "POSTFIELDS"
    POSTFIELDSIZE = "POSTFIELDSIZE"
    WRITEFUNCTION = "WRITEFUNCTION"
    HTTPHEADER = "HTTPHEADER"
    TIMEOUT = "TIMEOUT"
    CONNECTTIMEOUT = "CONNECTTIMEOUT"
    NOSIGNAL = "NOSIGNAL"
    RESPONSE_CODE = "RESPONSE_CODE"

    Curl = _FakeCurl

    class error(Exception):
        pass


# Swap the SDK's reference to the pycurl module.
relingo.pycurl = _FakePycurl()


# --- helpers ----------------------------------------------------------------

def queue(status, body):
    _RESPONSES.append((status, body, None))


def queue_raise(exc):
    _RESPONSES.append((0, b"", exc))


def last_request():
    return _REQUESTS[-1]


def assert_eq(a, b, msg=""):
    if a != b:
        raise AssertionError(f"{msg}: {a!r} != {b!r}")


def assert_in(needle, hay, msg=""):
    if needle not in hay:
        raise AssertionError(f"{msg}: {needle!r} not in {hay!r}")


def assert_true(cond, msg=""):
    if not cond:
        raise AssertionError(msg)


# --- tests ------------------------------------------------------------------

def test_status_constants():
    assert relingo.RELINGO_OK == 0
    assert relingo.RELINGO_ERR_INVALID == -1
    assert relingo.RELINGO_ERR_NOT_FOUND == -7
    assert relingo.relingo_status_str(relingo.RELINGO_OK) == "ok"
    assert relingo.relingo_status_str(relingo.RELINGO_ERR_NOT_FOUND) == "not found"


def test_client_lifecycle():
    c = relingo.relingo_client_new(None)
    assert_eq(c.lang, "en", "default lang")
    assert_eq(relingo.relingo_client_last_error(c), "ok", "default last_error")

    relingo.relingo_client_set_token(c, "abc")
    relingo.relingo_client_free(c)
    relingo.relingo_client_free(None)

    c2 = relingo.relingo_client_new("zh-CN")
    assert_eq(c2.lang, "zh-CN", "explicit lang")
    relingo.relingo_client_free(c2)


def test_authorization_happy():
    _REQUESTS.clear(); _RESPONSES.clear()
    c = relingo.relingo_client_new("en")
    queue(200, json.dumps({"code": 0, "message": "ok", "data": {}}))
    rc = relingo.relingo_authorization(c, "user@example.com")
    assert_eq(rc, relingo.RELINGO_OK, "authorization rc")
    req = last_request()
    assert_eq(req["url"], "https://api.relingo.net/api/authorization", "url")
    assert_eq(json.loads(req["body"]), {"email": "user@example.com"}, "body")
    assert_in("Content-Type: application/json", req["headers"], "content-type header")
    assert_in("x-relingo-lang: en", req["headers"], "lang header")
    relingo.relingo_client_free(c)


def test_authorization_invalid():
    c = relingo.relingo_client_new("en")
    assert_eq(relingo.relingo_authorization(c, ""), relingo.RELINGO_ERR_INVALID, "empty email")
    assert_eq(relingo.relingo_authorization(None, "x@x"), relingo.RELINGO_ERR_INVALID, "null client")
    relingo.relingo_client_free(c)


def test_login_by_code_happy():
    _REQUESTS.clear(); _RESPONSES.clear()
    c = relingo.relingo_client_new("en")
    queue(200, json.dumps({
        "code": 0,
        "message": "ok",
        "data": {"name": "alice", "token": "T-1", "expiredAt": 1700000000000},
    }))
    out = relingo.RelingoLogin()
    rc = relingo.relingo_login_by_code(c, "u@x", "1234", out)
    assert_eq(rc, relingo.RELINGO_OK, "login rc")
    assert_eq(out.name, "alice", "name")
    assert_eq(out.token, "T-1", "token")
    assert_eq(out.expired_at, 1700000000000, "expired_at")
    req = last_request()
    assert_eq(json.loads(req["body"]), {"email": "u@x", "code": "1234"}, "login body")
    relingo.relingo_client_free(c)


def test_login_by_code_no_token():
    _REQUESTS.clear(); _RESPONSES.clear()
    c = relingo.relingo_client_new("en")
    queue(200, json.dumps({"code": 0, "message": "ok", "data": {"name": "x"}}))
    out = relingo.RelingoLogin()
    rc = relingo.relingo_login_by_code(c, "u@x", "1", out)
    assert_eq(rc, relingo.RELINGO_ERR_PARSE, "missing token rc")
    relingo.relingo_client_free(c)


def test_login_by_code_api_error():
    _REQUESTS.clear(); _RESPONSES.clear()
    c = relingo.relingo_client_new("en")
    queue(200, json.dumps({"code": 401, "message": "bad code", "data": None}))
    out = relingo.RelingoLogin()
    rc = relingo.relingo_login_by_code(c, "u@x", "1", out)
    assert_eq(rc, relingo.RELINGO_ERR_API, "api error rc")
    assert_in("bad code", relingo.relingo_client_last_error(c), "last error message")
    relingo.relingo_client_free(c)


def test_login_by_code_garbage_envelope():
    _REQUESTS.clear(); _RESPONSES.clear()
    c = relingo.relingo_client_new("en")
    queue(200, "not json at all")
    out = relingo.RelingoLogin()
    rc = relingo.relingo_login_by_code(c, "u@x", "1", out)
    assert_eq(rc, relingo.RELINGO_ERR_PARSE, "garbage envelope rc")
    relingo.relingo_client_free(c)


def test_get_user_info():
    _REQUESTS.clear(); _RESPONSES.clear()
    c = relingo.relingo_client_new("en")
    relingo.relingo_client_set_token(c, "T")
    queue(200, json.dumps({"code": 0, "message": "ok", "data": {"token": "T-new"}}))
    out = [None]
    rc = relingo.relingo_get_user_info(c, out)
    assert_eq(rc, relingo.RELINGO_OK, "get_user_info rc")
    assert_eq(out[0], "T-new", "new token")
    req = last_request()
    assert_in("x-relingo-token: T", req["headers"], "auth header sent")
    relingo.relingo_client_free(c)


def test_get_user_config():
    _REQUESTS.clear(); _RESPONSES.clear()
    c = relingo.relingo_client_new("en")
    books = [
        {"name": "strange",  "_id": "s1"},
        {"name": "mastered", "_id": "m1"},
        {"name": "CET4",     "_id": "c1", "active": True},
        {"name": "TOEFL",    "id":   "c2", "active": True},
        {"name": "Hidden",   "_id": "h1", "active": False},
    ]
    queue(200, json.dumps({
        "code": 0, "message": "ok",
        "data": {"config": {"langBooks": {"en": books}}},
    }))
    out = relingo.RelingoConfig()
    rc = relingo.relingo_get_user_config(c, out)
    assert_eq(rc, relingo.RELINGO_OK, "get_user_config rc")
    assert_eq(out.strange_book, "s1", "strange book")
    assert_eq(out.mastered_book, "m1", "mastered book")
    assert_eq(sorted(out.custom_books), ["c1", "c2"], "custom books")
    assert_eq(out.n_custom_books, 2, "n custom")
    relingo.relingo_client_free(c)


def test_parse_content3_happy():
    _REQUESTS.clear(); _RESPONSES.clear()
    c = relingo.relingo_client_new("en")
    queue(200, json.dumps({
        "code": 0, "message": "ok",
        "data": {"words": [{
            "word": "hello",
            "phonetic": "h\u0259\u02C8lo\u028A",
            "translations": [{"translation": "\u4F60\u597D"}, "\u54C8\u5570"],
        }]},
    }))
    out = relingo.RelingoWord()
    rc = relingo.relingo_parse_content3(c, "zh-CN", ["v1", "v2"], 2, "hello", out)
    assert_eq(rc, relingo.RELINGO_OK, "parse_content3 rc")
    assert_eq(out.word, "hello", "word")
    assert_eq(out.phonetic, "h\u0259\u02C8lo\u028A", "phonetic")
    assert_eq(out.translations, ["\u4F60\u597D", "\u54C8\u5570"], "translations")
    assert_eq(out.n_translations, 2, "n translations")
    req = last_request()
    assert_eq(req["url"], "https://api.relingo.net/api/parseContent3", "url")
    body = json.loads(req["body"])
    assert_eq(body["words"], ["hello"], "words in body")
    assert_eq(body["vocabulary"], ["v1", "v2"], "vocab in body")
    assert_eq(body["definition"], False, "definition flag")
    relingo.relingo_client_free(c)


def test_parse_content3_n_vocab_truncates():
    _REQUESTS.clear(); _RESPONSES.clear()
    c = relingo.relingo_client_new("en")
    queue(200, json.dumps({"code": 0, "message": "ok", "data": {"words": [{"word": "x", "translations": []}]}}))
    out = relingo.RelingoWord()
    relingo.relingo_parse_content3(c, "zh-CN", ["a", "b", "c"], 1, "x", out)
    body = json.loads(last_request()["body"])
    assert_eq(body["vocabulary"], ["a"], "n_vocab truncates the list")
    relingo.relingo_client_free(c)


def test_parse_content3_not_found():
    _REQUESTS.clear(); _RESPONSES.clear()
    c = relingo.relingo_client_new("en")
    queue(200, json.dumps({"code": 0, "message": "ok", "data": {"words": []}}))
    out = relingo.RelingoWord()
    rc = relingo.relingo_parse_content3(c, "zh-CN", [], 0, "missing", out)
    assert_eq(rc, relingo.RELINGO_ERR_NOT_FOUND, "not found rc")
    relingo.relingo_client_free(c)


def test_lookup_dict2_happy():
    _REQUESTS.clear(); _RESPONSES.clear()
    c = relingo.relingo_client_new("en")
    queue(200, json.dumps({"code": 0, "message": "ok", "data": [
        {"text": "world", "phonetic": "w\u025C\u02B0ld", "translations": [{"text": "\u4E16\u754C"}]}
    ]}))
    out = relingo.RelingoWord()
    rc = relingo.relingo_lookup_dict2(c, "zh-CN", "world", out)
    assert_eq(rc, relingo.RELINGO_OK, "lookup rc")
    assert_eq(out.word, "world", "fallback text->word")
    assert_eq(out.translations, ["\u4E16\u754C"], "fallback text->translation")
    relingo.relingo_client_free(c)


def test_lookup_dict2_not_found():
    _REQUESTS.clear(); _RESPONSES.clear()
    c = relingo.relingo_client_new("en")
    queue(200, json.dumps({"code": 0, "message": "ok", "data": []}))
    out = relingo.RelingoWord()
    rc = relingo.relingo_lookup_dict2(c, "zh-CN", "x", out)
    assert_eq(rc, relingo.RELINGO_ERR_NOT_FOUND, "not found rc")
    relingo.relingo_client_free(c)


def test_submit_vocabulary():
    _REQUESTS.clear(); _RESPONSES.clear()
    c = relingo.relingo_client_new("en")
    queue(200, json.dumps({"code": 0, "message": "ok", "data": {}}))
    rc = relingo.relingo_submit_vocabulary(c, "m1", "hello")
    assert_eq(rc, relingo.RELINGO_OK, "submit rc")
    body = json.loads(last_request()["body"])
    assert_eq(body, {"id": "m1", "type": "mastered", "words": ["hello"]}, "submit body")
    assert_true(last_request()["url"].endswith("/api/submitVocabulary"), "submit endpoint")
    relingo.relingo_client_free(c)


def test_remove_vocabulary_words():
    _REQUESTS.clear(); _RESPONSES.clear()
    c = relingo.relingo_client_new("en")
    queue(200, json.dumps({"code": 0, "message": "ok", "data": {}}))
    rc = relingo.relingo_remove_vocabulary_words(c, "m1", "hello")
    assert_eq(rc, relingo.RELINGO_OK, "remove rc")
    body = json.loads(last_request()["body"])
    assert_eq(body, {"id": "m1", "type": "strange", "words": ["hello"]}, "remove body")
    relingo.relingo_client_free(c)


def test_translate_paragraph():
    _REQUESTS.clear(); _RESPONSES.clear()
    c = relingo.relingo_client_new("en")
    queue(200, "\u4F60\u597D\uFF0C\u4E16\u754C\u3002")
    out = [None]
    rc = relingo.relingo_translate_paragraph(c, "Hello, world.", "zh-CN", "1", out)
    assert_eq(rc, relingo.RELINGO_OK, "translate rc")
    assert_eq(out[0], "\u4F60\u597D\uFF0C\u4E16\u754C\u3002", "translated text")
    body = json.loads(last_request()["body"])
    assert_eq(body, {"text": "Hello, world.", "to": "zh-CN", "providerId": "1"}, "translate body")
    relingo.relingo_client_free(c)


def test_network_error():
    _REQUESTS.clear(); _RESPONSES.clear()
    c = relingo.relingo_client_new("en")
    queue_raise(_FakePycurl.error(7, "couldn't connect"))
    out = relingo.RelingoWord()
    rc = relingo.relingo_lookup_dict2(c, "zh-CN", "x", out)
    assert_eq(rc, relingo.RELINGO_ERR_NETWORK, "network rc")
    assert_in("couldn't connect", relingo.relingo_client_last_error(c), "network message")
    relingo.relingo_client_free(c)


def test_http_error():
    _REQUESTS.clear(); _RESPONSES.clear()
    c = relingo.relingo_client_new("en")
    queue(500, "boom")
    out = relingo.RelingoWord()
    rc = relingo.relingo_lookup_dict2(c, "zh-CN", "x", out)
    assert_eq(rc, relingo.RELINGO_ERR_HTTP, "http rc")
    assert_eq(relingo.relingo_client_last_error(c), "http 500", "http error message")
    relingo.relingo_client_free(c)


def test_invalid_args():
    out = relingo.RelingoWord()
    assert_eq(relingo.relingo_lookup_dict2(None, "zh-CN", "x", out), relingo.RELINGO_ERR_INVALID, "null client")
    c = relingo.relingo_client_new("en")
    assert_eq(relingo.relingo_lookup_dict2(c, "", "x", out), relingo.RELINGO_ERR_INVALID, "empty to")
    assert_eq(relingo.relingo_lookup_dict2(c, "zh-CN", "", out), relingo.RELINGO_ERR_INVALID, "empty word")
    assert_eq(relingo.relingo_lookup_dict2(c, "zh-CN", "x", None), relingo.RELINGO_ERR_INVALID, "null out")
    relingo.relingo_client_free(c)


def main():
    tests = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  ok   {t.__name__}")
        except Exception as exc:
            failed += 1
            print(f"  FAIL {t.__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
