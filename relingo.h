/*
 * relingo.h - C SDK for the Relingo API
 *
 * One client per thread. The client struct is not internally synchronized.
 * All strings and arrays returned by API functions are owned by the caller
 * and must be released with the corresponding _free function.
 */

#ifndef RELINGO_H
#define RELINGO_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Status codes returned by every API function. */
typedef enum {
    RELINGO_OK            =  0,  /* success */
    RELINGO_ERR_INVALID   = -1,  /* invalid arguments */
    RELINGO_ERR_NOMEM     = -2,  /* allocation failed */
    RELINGO_ERR_NETWORK   = -3,  /* libcurl / DNS / connect failure */
    RELINGO_ERR_HTTP      = -4,  /* non-2xx HTTP status */
    RELINGO_ERR_PARSE     = -5,  /* JSON parse failure */
    RELINGO_ERR_API       = -6,  /* server returned non-zero code */
    RELINGO_ERR_NOT_FOUND = -7   /* word not in dictionary */
} relingo_status;

/* Opaque client handle. */
typedef struct relingo_client relingo_client_t;

/* --- Client lifecycle --- */

/* Create a client. lang is the UI language (e.g. "en", "zh-CN").
 * Pass NULL for "en". Returns NULL on allocation failure. */
relingo_client_t *relingo_client_new(const char *lang);

/* Release all resources held by the client. */
void relingo_client_free(relingo_client_t *c);

/* Set the access token obtained from relingo_login_by_code.
 * Pass NULL to clear. */
void relingo_client_set_token(relingo_client_t *c, const char *token);

/* Human-readable description of the last error on this client. Never NULL. */
const char *relingo_client_last_error(const relingo_client_t *c);

/* Static description of a status code. */
const char *relingo_status_str(relingo_status s);

/* --- Result types --- */

/* A single dictionary entry. */
typedef struct {
    char  *word;             /* the headword */
    char  *phonetic;         /* IPA transcription, may be NULL */
    char **translations;     /* array of translation strings */
    size_t n_translations;
} relingo_word_t;

void relingo_word_free(relingo_word_t *w);

/* User wordbook IDs. */
typedef struct {
    char  *strange_book;     /* 生词本 */
    char  *mastered_book;    /* 已掌握词本 */
    char **custom_books;     /* 自定义词本 */
    size_t n_custom_books;
} relingo_config_t;

void relingo_config_free(relingo_config_t *cfg);

/* Login result. */
typedef struct {
    char       *name;
    char       *token;
    long long   expired_at;  /* Unix milliseconds */
} relingo_login_t;

void relingo_login_free(relingo_login_t *r);

/* --- Authentication --- */

/* Send a verification code to the given email. */
relingo_status relingo_authorization(relingo_client_t *c, const char *email);

/* Log in with email and verification code. */
relingo_status relingo_login_by_code(relingo_client_t *c,
    const char *email, const char *code, relingo_login_t *out);

/* --- User --- */

/* Refresh and return the new access token. Caller frees *out_token. */
relingo_status relingo_get_user_info(relingo_client_t *c, char **out_token);

/* Fetch the user's wordbook IDs. */
relingo_status relingo_get_user_config(relingo_client_t *c, relingo_config_t *out);

/* --- Word lookup --- */

/* Look up `word` in the user's wordbooks (strange + custom).
 * Returns RELINGO_ERR_NOT_FOUND if absent. */
relingo_status relingo_parse_content3(relingo_client_t *c,
    const char *to,
    const char *const *vocab_ids, size_t n_vocab,
    const char *word,
    relingo_word_t *out);

/* Look up `word` in Relingo's official dictionary.
 * Returns RELINGO_ERR_NOT_FOUND if absent. */
relingo_status relingo_lookup_dict2(relingo_client_t *c,
    const char *to,
    const char *word,
    relingo_word_t *out);

/* --- Vocabulary operations --- */

/* Mark `word` as mastered (write to mastered_book). */
relingo_status relingo_submit_vocabulary(relingo_client_t *c,
    const char *mastered_book_id,
    const char *word);

/* Mark `word` as forgotten (move from mastered back to strange). */
relingo_status relingo_remove_vocabulary_words(relingo_client_t *c,
    const char *mastered_book_id,
    const char *word);

/* --- Translation --- */

/* Translate a paragraph with the given provider. Caller frees *out_translated.
 * The result may contain embedded newlines; split as needed. */
relingo_status relingo_translate_paragraph(relingo_client_t *c,
    const char *text,
    const char *to,
    const char *provider_id,
    char **out_translated);

#ifdef __cplusplus
}
#endif

#endif /* RELINGO_H */
