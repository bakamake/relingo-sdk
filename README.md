# Relingo C SDK

C client for the Relingo HTTP API. Single translation unit, no globals, no
extra dependencies beyond libcurl and cJSON.

## Dependencies

- libcurl (>= 7.x)
- cJSON (>= 1.7.x)

Debian / Ubuntu:

    sudo apt install libcurl4-openssl-dev libcjson-dev

macOS:

    brew install curl cjson

## Build

    make

Produces `librelingo.a` (static library) and `example` (sample binary).

## Linking against the library

    cc myapp.c librelingo.a -lcurl -lcjson -o myapp

If your distro ships a `libcjson.pc`, `pkg-config --cflags --libs libcjson`
gives the correct flags.

## Usage

```c
#include "relingo.h"

relingo_client_t *c = relingo_client_new("en");

relingo_authorization(c, "user@example.com");

relingo_login_t login;
relingo_login_by_code(c, "user@example.com", "123456", &login);
relingo_client_set_token(c, login.token);
relingo_login_free(&login);

relingo_config_t cfg;
relingo_get_user_config(c, &cfg);
/* cfg.strange_book, cfg.mastered_book, cfg.custom_books[] */
relingo_config_free(&cfg);

relingo_word_t w;
if (relingo_lookup_dict2(c, "zh-CN", "hello", &w) == RELINGO_OK) {
    printf("%s [%s]\n", w.word, w.phonetic ? w.phonetic : "");
    for (size_t i = 0; i < w.n_translations; i++)
        printf("  - %s\n", w.translations[i]);
    relingo_word_free(&w);
}

relingo_client_free(c);
```

See `example.c` for a runnable end-to-end sample.

## Status codes

Every API function returns one of:

| Code | Meaning |
| --- | --- |
| `RELINGO_OK` | success |
| `RELINGO_ERR_INVALID` | bad arguments (NULL pointer, empty string) |
| `RELINGO_ERR_NOMEM` | allocation failure |
| `RELINGO_ERR_NETWORK` | libcurl / DNS / connect failure |
| `RELINGO_ERR_HTTP` | non-2xx HTTP status |
| `RELINGO_ERR_PARSE` | response body was not valid JSON, or the envelope was malformed |
| `RELINGO_ERR_API` | server returned a non-zero `code` |
| `RELINGO_ERR_NOT_FOUND` | word is not in the dictionary |

`relingo_client_last_error(c)` returns a human-readable description of the
most recent failure on the client.

## Memory ownership

The caller owns everything returned by an API function:

- Strings and string arrays returned via out-parameters.
- Fields of `relingo_word_t`, `relingo_config_t`, `relingo_login_t`.

Use the corresponding `_free` function on each struct, and `free()` on bare
strings (`out_token`, `out_translated`).

## Thread safety

`relingo_client_t` is **not** internally synchronized. Use one client per
thread, or wrap access in your own mutex. libcurl global initialization
(`curl_global_init`) is not required; the SDK creates and tears down a fresh
easy handle per request.

## Endpoints

All requests go to `https://api.relingo.net` via `POST`. The SDK sends the
same headers as the original Bob plugin:

- `Content-Type: application/json`
- `User-Agent: <Chrome 110 on macOS>`
- `x-relingo-token: <token>` (when set on the client)
- `x-relingo-lang: <lang>`

| C function | Endpoint |
| --- | --- |
| `relingo_authorization` | `/api/authorization` |
| `relingo_login_by_code` | `/api/loginByCode` |
| `relingo_get_user_info` | `/api/getUserInfo` |
| `relingo_get_user_config` | `/api/getUserConfig` |
| `relingo_parse_content3` | `/api/parseContent3` |
| `relingo_lookup_dict2` | `/api/lookupDict2` |
| `relingo_submit_vocabulary` | `/api/submitVocabulary` |
| `relingo_remove_vocabulary_words` | `/api/removeVocabularyWords` |
| `relingo_translate_paragraph` | `/api/translateParagraph` |
