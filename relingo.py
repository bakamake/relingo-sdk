"""
relingo.py - Python SDK for the Relingo API.

Pure translation of the C SDK (relingo.c / relingo.h). Public symbols
(function names, struct field names, status code values) are kept
identical to the C version so the two ports can be read side by side.
The only meaningful shape change is that callers own the result objects
(dataclasses) directly instead of receiving heap-allocated structs; the
``*_free`` helpers are still provided as a no-op safety net.

HTTP via pycurl. JSON via the stdlib.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional, Sequence

import pycurl


# --- Constants ---------------------------------------------------------------

RELINGO_BASE_URL = "https://api.relingo.net"
RELINGO_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"
)


# --- Status codes ------------------------------------------------------------

class RelingoStatus(IntEnum):
    """Status codes returned by every API function. Values match the C enum."""
    RELINGO_OK            =  0   # success
    RELINGO_ERR_INVALID   = -1   # invalid arguments
    RELINGO_ERR_NOMEM     = -2   # allocation failed
    RELINGO_ERR_NETWORK   = -3   # pycurl / DNS / connect failure
    RELINGO_ERR_HTTP      = -4   # non-2xx HTTP status
    RELINGO_ERR_PARSE     = -5   # JSON parse failure
    RELINGO_ERR_API       = -6   # server returned non-zero code
    RELINGO_ERR_NOT_FOUND = -7   # word not in dictionary


# Aliases matching the C ``typedef enum { ... } relingo_status`` spelling.
RELINGO_OK            = RelingoStatus.RELINGO_OK
RELINGO_ERR_INVALID   = RelingoStatus.RELINGO_ERR_INVALID
RELINGO_ERR_NOMEM     = RelingoStatus.RELINGO_ERR_NOMEM
RELINGO_ERR_NETWORK   = RelingoStatus.RELINGO_ERR_NETWORK
RELINGO_ERR_HTTP      = RelingoStatus.RELINGO_ERR_HTTP
RELINGO_ERR_PARSE     = RelingoStatus.RELINGO_ERR_PARSE
RELINGO_ERR_API       = RelingoStatus.RELINGO_ERR_API
RELINGO_ERR_NOT_FOUND = RelingoStatus.RELINGO_ERR_NOT_FOUND


_STATUS_STR = {
    RelingoStatus.RELINGO_OK:            "ok",
    RelingoStatus.RELINGO_ERR_INVALID:   "invalid arguments",
    RelingoStatus.RELINGO_ERR_NOMEM:     "out of memory",
    RelingoStatus.RELINGO_ERR_NETWORK:   "network error",
    RelingoStatus.RELINGO_ERR_HTTP:      "http error",
    RelingoStatus.RELINGO_ERR_PARSE:     "json parse error",
    RelingoStatus.RELINGO_ERR_API:       "api error",
    RelingoStatus.RELINGO_ERR_NOT_FOUND: "not found",
}


def relingo_status_str(s):
    """Static description of a status code (mirror of the C function)."""
    try:
        return _STATUS_STR[RelingoStatus(s)]
    except (ValueError, KeyError):
        return "unknown"


# --- Result types ------------------------------------------------------------

@dataclass
class RelingoWord:
    """A single dictionary entry. Mirrors ``relingo_word_t``."""
    word: Optional[str] = None
    phonetic: Optional[str] = None
    translations: list = field(default_factory=list)
    n_translations: int = 0


def relingo_word_free(w):
    """Release resources held by a ``RelingoWord`` (no-op for the Python port)."""
    if w is None:
        return
    w.word = None
    w.phonetic = None
    w.translations = []
    w.n_translations = 0


@dataclass
class RelingoConfig:
    """User wordbook IDs. Mirrors ``relingo_config_t``."""
    strange_book: Optional[str] = None
    mastered_book: Optional[str] = None
    active_books: list = field(default_factory=list)
    n_active_books: int = 0


def relingo_config_free(cfg):
    if cfg is None:
        return
    cfg.strange_book = None
    cfg.mastered_book = None
    cfg.active_books = []
    cfg.n_active_books = 0


@dataclass
class RelingoLogin:
    """Login result. Mirrors ``relingo_login_t``."""
    name: Optional[str] = None
    token: Optional[str] = None
    expired_at: int = 0  # Unix milliseconds


def relingo_login_free(r):
    if r is None:
        return
    r.name = None
    r.token = None
    r.expired_at = 0


# --- Client ------------------------------------------------------------------

class RelingoClient:
    """Opaque client handle. One per thread; not internally synchronized."""

    __slots__ = ("lang", "_token", "_last_error")

    def __init__(self, lang):
        self.lang = lang if lang else "en"
        self._token = None
        self._last_error = relingo_status_str(RELINGO_OK)


def relingo_client_new(lang):
    """Create a client. ``lang`` is the UI language (e.g. "en", "zh-CN")."""
    try:
        return RelingoClient(lang)
    except Exception:
        return None


def relingo_client_free(c):
    """Release all resources held by the client."""
    if c is None:
        return
    c._token = None
    c._last_error = ""
    c.lang = ""


def relingo_client_set_token(c, token):
    """Set the access token obtained from ``relingo_login_by_code``."""
    if c is None:
        return
    c._token = token


def relingo_client_last_error(c):
    """Human-readable description of the last error on this client."""
    if c is not None and c._last_error:
        return c._last_error
    return relingo_status_str(RELINGO_OK)


# --- HTTP transport ----------------------------------------------------------

class _DynBuf:
    __slots__ = ("data",)

    def __init__(self):
        self.data = bytearray()

    def write(self, chunk):
        self.data.extend(chunk)
        return len(chunk)


def _set_error(c, msg):
    if c is None:
        return
    c._last_error = msg


def _http_post(c, path, body):
    """POST a JSON body. On ``RELINGO_OK`` the second element is the response body."""
    url = RELINGO_BASE_URL + path
    buf = _DynBuf()

    curl = pycurl.Curl()
    try:
        curl.setopt(pycurl.URL, url)
        curl.setopt(pycurl.POST, 1)
        curl.setopt(pycurl.POSTFIELDS, body)
        curl.setopt(pycurl.POSTFIELDSIZE, len(body.encode("utf-8")))
        curl.setopt(pycurl.WRITEFUNCTION, buf.write)
        curl.setopt(pycurl.TIMEOUT, 30)
        curl.setopt(pycurl.CONNECTTIMEOUT, 10)
        curl.setopt(pycurl.NOSIGNAL, 1)

        headers = [
            "Content-Type: application/json",
            f"User-Agent: {RELINGO_USER_AGENT}",
        ]
        if c is not None and c._token:
            headers.append(f"x-relingo-token: {c._token}")
        if c is not None and c.lang:
            headers.append(f"x-relingo-lang: {c.lang}")
        curl.setopt(pycurl.HTTPHEADER, headers)

        try:
            curl.perform()
        except pycurl.error as exc:
            err = exc.args[1] if len(exc.args) > 1 else exc.args[0]
            _set_error(c, f"curl: {err}")
            return RELINGO_ERR_NETWORK, ""

        status = curl.getinfo(pycurl.RESPONSE_CODE)
    finally:
        curl.close()

    if status < 200 or status >= 300:
        _set_error(c, f"http {status}")
        return RELINGO_ERR_HTTP, ""

    try:
        return RELINGO_OK, buf.data.decode("utf-8")
    except UnicodeDecodeError:
        _set_error(c, "response is not valid utf-8")
        return RELINGO_ERR_PARSE, ""


# --- JSON helpers ------------------------------------------------------------

def _parse_envelope(c, payload):
    """Parse ``{code, message, data}``.

    Returns ``(RELINGO_OK, data)`` on success, where ``data`` is the parsed
    ``data`` field (may be None, dict, list, ...). On failure ``data`` is
    ``None``.
    """
    try:
        root = json.loads(payload)
    except (ValueError, TypeError):
        _set_error(c, "json parse failed")
        return RELINGO_ERR_PARSE, None

    if not isinstance(root, dict):
        _set_error(c, "envelope: root is not an object")
        return RELINGO_ERR_PARSE, None

    code = root.get("code")
    message = root.get("message")
    data = root.get("data")

    if isinstance(code, bool):
        cv = -1
    elif isinstance(code, (int, float)):
        cv = int(code)
    else:
        cv = -1

    if cv != 0:
        msg = message if isinstance(message, str) else "(no message)"
        _set_error(c, f"api error {cv}: {msg}")

    if cv == 0:
        return RELINGO_OK, data
    if cv > 0:
        return RELINGO_ERR_API, data
    return RELINGO_ERR_PARSE, data


def _jstr_or_null(value):
    return value if isinstance(value, str) else None


def _jstr_field(obj, primary, fallback):
    """Read a string field from a dict, falling back to an alternate name."""
    if not isinstance(obj, dict):
        return None
    v = obj.get(primary)
    if not isinstance(v, str):
        v = obj.get(fallback)
    return v if isinstance(v, str) else None


def _extract_word(w, out):
    out.word = _jstr_field(w, "word", "text")
    if isinstance(w, dict):
        out.phonetic = _jstr_or_null(w.get("phonetic"))
    else:
        out.phonetic = None
    out.translations = []
    out.n_translations = 0

    if not isinstance(w, dict):
        return RELINGO_OK
    trs = w.get("translations")
    if not isinstance(trs, list):
        return RELINGO_OK
    for t in trs:
        s = None
        if isinstance(t, str):
            s = t
        elif isinstance(t, dict):
            v = t.get("translation")
            if isinstance(v, str):
                s = v
            else:
                v = t.get("text")
                if isinstance(v, str):
                    s = v
                else:
                    v = t.get("meaning")
                    if isinstance(v, str):
                        s = v
        if s is None:
            continue
        out.translations.append(s)
    out.n_translations = len(out.translations)
    return RELINGO_OK


# --- Authentication ----------------------------------------------------------

def relingo_authorization(c, email):
    """Send a verification code to the given email."""
    if c is None or not email:
        return RELINGO_ERR_INVALID

    body = json.dumps({"email": email})
    rc, _ = _http_post(c, "/api/authorization", body)
    return rc


def relingo_login_by_code(c, email, code, out):
    """Log in with email and verification code."""
    if c is None or not email or not code or out is None:
        return RELINGO_ERR_INVALID
    relingo_login_free(out)

    body = json.dumps({"email": email, "code": code})
    rc, resp = _http_post(c, "/api/loginByCode", body)
    if rc != RELINGO_OK:
        return rc

    rc, data = _parse_envelope(c, resp)
    if rc != RELINGO_OK:
        return rc
    if not isinstance(data, dict):
        _set_error(c, "login: data is not an object")
        return RELINGO_ERR_PARSE

    out.name = _jstr_or_null(data.get("name"))
    out.token = _jstr_or_null(data.get("token"))
    ea = data.get("expiredAt")
    if isinstance(ea, bool):
        out.expired_at = 0
    elif isinstance(ea, (int, float)):
        out.expired_at = int(ea)
    else:
        out.expired_at = 0

    if not out.token:
        relingo_login_free(out)
        return RELINGO_ERR_PARSE
    return RELINGO_OK


# --- User --------------------------------------------------------------------

def relingo_get_user_info(c, out_token):
    """Refresh and return the new access token.

    ``out_token`` is a single-element list used as an out-pointer: the new
    token is written to ``out_token[0]`` on success.
    """
    if c is None or out_token is None:
        return RELINGO_ERR_INVALID
    out_token.clear()
    out_token.append(None)

    rc, resp = _http_post(c, "/api/getUserInfo", "{}")
    if rc != RELINGO_OK:
        return rc

    rc, data = _parse_envelope(c, resp)
    if rc != RELINGO_OK:
        return rc
    if not isinstance(data, dict):
        _set_error(c, "getUserInfo: data is not an object")
        return RELINGO_ERR_PARSE

    token = _jstr_or_null(data.get("token"))
    if not token:
        return RELINGO_ERR_PARSE
    out_token[0] = token
    return RELINGO_OK


def relingo_get_user_config(c, out):
    """Fetch the user's wordbook IDs."""
    if c is None or out is None:
        return RELINGO_ERR_INVALID
    relingo_config_free(out)

    rc, resp = _http_post(c, "/api/getUserConfig", "{}")
    if rc != RELINGO_OK:
        return rc

    rc, data = _parse_envelope(c, resp)
    if rc != RELINGO_OK:
        return rc
    if not isinstance(data, dict):
        _set_error(c, "getUserConfig: data is not an object")
        return RELINGO_ERR_PARSE

    cfg = data.get("config")
    current_books = cfg.get("currentBooks") if isinstance(cfg, dict) else None
    if not isinstance(current_books, list):
        _set_error(c, "config: currentBooks.en not found")
        return RELINGO_ERR_PARSE

    active_ids: list[str] = []
    for book in current_books:
        if not isinstance(book, dict):
            continue
        name = book.get("name")
        if not isinstance(name, str):
            continue
        cid = _jstr_field(book, "_id", "id")
        if name == "strange":
            # TODO: persist strange_book id across sessions so callers don't
            # have to refetch /api/getUserConfig on every lookup.
            if cid is not None and out.strange_book is None:
                out.strange_book = cid
            continue
        if name == "mastered":
            if cid is not None and out.mastered_book is None:
                out.mastered_book = cid
            continue
        if book.get("active") is True and cid is not None:
            active_ids.append(cid)

    out.active_books = active_ids
    out.n_active_books = len(active_ids)
    return RELINGO_OK


# --- Word lookup -------------------------------------------------------------

def relingo_parse_content3(c, to, vocab_ids, n_vocab, word, out):
    """Look up ``word`` in the user's wordbooks (strange + active)."""
    if c is None or not to or not word or out is None:
        return RELINGO_ERR_INVALID
    relingo_word_free(out)

    vocab_list = list(vocab_ids) if vocab_ids is not None else []
    # Truncate to n_vocab to mirror the C size_t contract.
    if n_vocab >= 0 and n_vocab < len(vocab_list):
        vocab_list = vocab_list[:n_vocab]
    vocab_list = [v for v in vocab_list if v]

    req = {
        "to": to,
        "words": [word],
        "vocabulary": vocab_list,
        "definition": False,
    }
    body = json.dumps(req)

    rc, resp = _http_post(c, "/api/parseContent3", body)
    if rc != RELINGO_OK:
        return rc

    rc, data = _parse_envelope(c, resp)
    if rc != RELINGO_OK:
        return rc
    if not isinstance(data, dict):
        _set_error(c, "parseContent3: data is not an object")
        return RELINGO_ERR_PARSE
    arr = data.get("words")
    if not isinstance(arr, list) or len(arr) == 0:
        _set_error(c, "word not in vocabulary")
        return RELINGO_ERR_NOT_FOUND

    return _extract_word(arr[0], out)


def relingo_lookup_dict2(c, to, word, out):
    """Look up ``word`` in Relingo's official dictionary."""
    if c is None or not to or not word or out is None:
        return RELINGO_ERR_INVALID
    relingo_word_free(out)

    body = json.dumps({"to": to, "words": [word]})
    rc, resp = _http_post(c, "/api/lookupDict2", body)
    if rc != RELINGO_OK:
        return rc

    rc, data = _parse_envelope(c, resp)
    if rc != RELINGO_OK:
        return rc
    if not isinstance(data, list) or len(data) == 0:
        _set_error(c, "word not in dictionary")
        return RELINGO_ERR_NOT_FOUND

    return _extract_word(data[0], out)


# --- Vocabulary operations ---------------------------------------------------

def _vocabulary_op(c, endpoint, mastered_book_id, type_, word):
    if c is None or not mastered_book_id or not type_ or not word:
        return RELINGO_ERR_INVALID

    body = json.dumps(
        {
            "id": mastered_book_id,
            "type": type_,
            "words": [word],
        }
    )
    rc, resp = _http_post(c, endpoint, body)
    if rc != RELINGO_OK:
        return rc
    rc, _ = _parse_envelope(c, resp)
    return rc


def relingo_mark_mastered(c, mastered_book_id, word):
    """Mark ``word`` as mastered (write to mastered_book)."""
    return _vocabulary_op(c, "/api/submitVocabulary", mastered_book_id, "mastered", word)


def relingo_mark_forgotten(c, mastered_book_id, word):
    """Mark ``word`` as forgotten (move from mastered back to strange)."""
    return _vocabulary_op(c, "/api/removeVocabularyWords", mastered_book_id, "strange", word)


# --- Translation -------------------------------------------------------------

def relingo_translate_paragraph(c, text, to, provider_id, out):
    """Translate a paragraph with the given provider.

    ``out`` is a single-element list used as an out-pointer: the translated
    text is written to ``out[0]`` on success. The result may contain
    embedded newlines; split as needed.
    """
    if c is None or not text or not to or not provider_id or out is None:
        return RELINGO_ERR_INVALID
    out.clear()
    out.append(None)

    body = json.dumps({"text": text, "to": to, "providerId": provider_id})
    rc, resp = _http_post(c, "/api/translateParagraph", body)
    if rc != RELINGO_OK:
        return rc

    # TODO: verify actual response shape via curl before parsing. (Kept
    # identical to the C SDK's behaviour: hand back the raw body.)
    out[0] = resp
    return RELINGO_OK
