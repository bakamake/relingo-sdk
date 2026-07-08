# Relingo Python SDK

Python client for the Relingo HTTP API, plus a small CLI (`example.py`).
A straight port of the original C SDK — function names, struct (dataclass)
fields, and status codes are kept identical so both can be read side by side.

## Dependencies

- Python >= 3.9
- [pycurl](https://pypi.org/project/pycurl/) (HTTP transport; JSON uses the stdlib)

Debian / Ubuntu:

    sudo apt install python3-pycurl
    # or: pip install pycurl

macOS:

    brew install curl
    pip install pycurl

## CLI

`example.py` is a ready-to-use CLI built on the SDK. Log in once; the token is
saved to `~/.config/relingo/credentials.json` (mode 0600) and reused.

    python3 example.py login <email>          # send code, prompt for it, persist token
    python3 example.py logout                  # remove the saved token
    python3 example.py whoami                  # show account / token status
    python3 example.py config                  # show wordbook ids (alias: list)
    python3 example.py lookup <word>           # look up a word (user books, then dict)
    python3 example.py mark mastered <word>    # mark a word as mastered
    python3 example.py mark forgotten <word>   # move a word back to strange
    python3 example.py translate <text...>     # translate a paragraph

`translate` defaults to the `deepseek` provider and target `zh-CN`; override
the engine with `--provider`:

    python3 example.py translate release                 # -> 发布
    python3 example.py translate --provider gpt-4o hello

## SDK usage

```python
import relingo

c = relingo.relingo_client_new("en")

relingo.relingo_authorization(c, "user@example.com")

login = relingo.RelingoLogin()
relingo.relingo_login_by_code(c, "user@example.com", "123456", login)
relingo.relingo_client_set_token(c, login.token)

cfg = relingo.RelingoConfig()
relingo.relingo_get_user_config(c, cfg)
# cfg.strange_book, cfg.mastered_book, cfg.active_books[]

w = relingo.RelingoWord()
if relingo.relingo_lookup_dict2(c, "zh-CN", "hello", w) == relingo.RELINGO_OK:
    print(w.word, w.phonetic or "")
    for t in w.translations:
        print("  -", t)

out = [None]
if relingo.relingo_translate_paragraph(c, "Hello, world.", "zh-CN", "deepseek", out) == relingo.RELINGO_OK:
    print(out[0])

relingo.relingo_client_free(c)
```

Out-parameters that return a single string (`relingo_get_user_info`,
`relingo_translate_paragraph`) use a single-element list as an out-pointer:
the result is written to `out[0]`.

## Status codes

Every API function returns one of:

| Code | Meaning |
| --- | --- |
| `RELINGO_OK` | success |
| `RELINGO_ERR_INVALID` | bad arguments (None, empty string) |
| `RELINGO_ERR_NOMEM` | allocation failure |
| `RELINGO_ERR_NETWORK` | pycurl / DNS / connect failure |
| `RELINGO_ERR_HTTP` | non-2xx HTTP status |
| `RELINGO_ERR_PARSE` | response body was not valid JSON, or the envelope was malformed |
| `RELINGO_ERR_API` | server returned a non-zero `code` |
| `RELINGO_ERR_NOT_FOUND` | word is not in the dictionary |

`relingo_client_last_error(c)` returns a human-readable description of the
most recent failure on the client.

## Thread safety

`RelingoClient` is **not** internally synchronized. Use one client per thread,
or wrap access in your own lock. A fresh pycurl easy handle is created and torn
down per request.

## Endpoints

All requests go to `https://api.relingo.net` via `POST`, with headers:

- `Content-Type: application/json`
- `User-Agent: <Chrome 110 on macOS>`
- `x-relingo-token: <token>` (when set on the client)
- `x-relingo-lang: <lang>`

| Function | Endpoint |
| --- | --- |
| `relingo_authorization` | `/api/authorization` |
| `relingo_login_by_code` | `/api/loginByCode` |
| `relingo_get_user_info` | `/api/getUserInfo` |
| `relingo_get_user_config` | `/api/getUserConfig` |
| `relingo_parse_content3` | `/api/parseContent3` |
| `relingo_lookup_dict2` | `/api/lookupDict2` |
| `relingo_mark_mastered` | `/api/submitVocabulary` |
| `relingo_mark_forgotten` | `/api/removeVocabularyWords` |
| `relingo_translate_paragraph` | `/api/translateParagraph` |
