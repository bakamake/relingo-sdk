/*
 * relingo.c - implementation
 *
 * HTTP via libcurl, JSON via cJSON. No other dependencies.
 */

#define _GNU_SOURCE
#include "relingo.h"

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <curl/curl.h>
#include <cjson/cJSON.h>

#define RELINGO_BASE_URL  "https://api.relingo.net"
#define RELINGO_USER_AGENT "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) " \
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36"

/* --- Client --- */

struct relingo_client {
    char *lang;
    char *token;
    char *last_error;
};

/* --- Status / error --- */

const char *relingo_status_str(relingo_status s)
{
    switch (s) {
    case RELINGO_OK:            return "ok";
    case RELINGO_ERR_INVALID:   return "invalid arguments";
    case RELINGO_ERR_NOMEM:     return "out of memory";
    case RELINGO_ERR_NETWORK:   return "network error";
    case RELINGO_ERR_HTTP:      return "http error";
    case RELINGO_ERR_PARSE:     return "json parse error";
    case RELINGO_ERR_API:       return "api error";
    case RELINGO_ERR_NOT_FOUND: return "not found";
    }
    return "unknown";
}

static void set_error(relingo_client_t *c, const char *fmt, ...)
{
    if (!c) return;
    free(c->last_error);
    c->last_error = NULL;
    va_list ap;
    va_start(ap, fmt);
    int n = vasprintf(&c->last_error, fmt, ap);
    va_end(ap);
    (void)n;
}

const char *relingo_client_last_error(const relingo_client_t *c)
{
    return (c && c->last_error) ? c->last_error : relingo_status_str(RELINGO_OK);
}

/* --- Client lifecycle --- */

relingo_client_t *relingo_client_new(const char *lang)
{
    relingo_client_t *c = calloc(1, sizeof(*c));
    if (!c) return NULL;
    c->lang = strdup(lang ? lang : "en");
    if (!c->lang) { free(c); return NULL; }
    return c;
}

void relingo_client_free(relingo_client_t *c)
{
    if (!c) return;
    free(c->lang);
    free(c->token);
    free(c->last_error);
    free(c);
}

void relingo_client_set_token(relingo_client_t *c, const char *token)
{
    if (!c) return;
    free(c->token);
    c->token = token ? strdup(token) : NULL;
}

/* --- HTTP transport --- */

typedef struct {
    char  *data;
    size_t size;
    size_t cap;
} dynbuf;

static size_t write_cb(void *ptr, size_t size, size_t nmemb, void *userp)
{
    size_t n = size * nmemb;
    dynbuf *b = userp;
    if (b->size + n + 1 > b->cap) {
        size_t nc = b->cap ? b->cap : 1024;
        while (nc < b->size + n + 1) nc *= 2;
        char *p = realloc(b->data, nc);
        if (!p) return 0;
        b->data = p;
        b->cap = nc;
    }
    memcpy(b->data + b->size, ptr, n);
    b->size += n;
    b->data[b->size] = '\0';
    return n;
}

/* POST a JSON body. On RELINGO_OK, *resp holds the response body (caller frees). */
static relingo_status http_post(relingo_client_t *c, const char *path,
                                const char *body, char **resp)
{
    *resp = NULL;
    CURL *curl = curl_easy_init();
    if (!curl) { set_error(c, "curl_easy_init failed"); return RELINGO_ERR_NETWORK; }

    char url[512];
    snprintf(url, sizeof(url), "%s%s", RELINGO_BASE_URL, path);

    dynbuf buf = {0};
    struct curl_slist *hdrs = NULL;
    hdrs = curl_slist_append(hdrs, "Content-Type: application/json");

    char ua[300];
    snprintf(ua, sizeof(ua), "User-Agent: %s", RELINGO_USER_AGENT);
    hdrs = curl_slist_append(hdrs, ua);

    if (c->token) {
        char h[1024];
        snprintf(h, sizeof(h), "x-relingo-token: %s", c->token);
        hdrs = curl_slist_append(hdrs, h);
    }
    if (c->lang) {
        char h[128];
        snprintf(h, sizeof(h), "x-relingo-lang: %s", c->lang);
        hdrs = curl_slist_append(hdrs, h);
    }

    curl_easy_setopt(curl, CURLOPT_URL, url);
    curl_easy_setopt(curl, CURLOPT_POST, 1L);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDS, body);
    curl_easy_setopt(curl, CURLOPT_POSTFIELDSIZE, (long)strlen(body));
    curl_easy_setopt(curl, CURLOPT_HTTPHEADER, hdrs);
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, write_cb);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &buf);
    curl_easy_setopt(curl, CURLOPT_TIMEOUT, 30L);
    curl_easy_setopt(curl, CURLOPT_CONNECTTIMEOUT, 10L);
    curl_easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);

    CURLcode rc = curl_easy_perform(curl);
    long status = 0;
    curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status);
    curl_slist_free_all(hdrs);
    curl_easy_cleanup(curl);

    if (rc != CURLE_OK) {
        free(buf.data);
        set_error(c, "curl: %s", curl_easy_strerror(rc));
        return RELINGO_ERR_NETWORK;
    }
    if (status < 200 || status >= 300) {
        free(buf.data);
        set_error(c, "http %ld", status);
        return RELINGO_ERR_HTTP;
    }
    *resp = buf.data;
    return RELINGO_OK;
}

/* --- JSON helpers --- */

/* Parse {code, message, data}. On RELINGO_OK semantics: returns RELINGO_OK
 * (code == 0) and writes *out_data (a duplicated cJSON node, caller deletes).
 * On RELINGO_ERR_PARSE: returns that and sets last_error.
 * On RELINGO_ERR_API: returns that, sets last_error to the server message,
 *   *out_data is NULL. */
static relingo_status parse_envelope(relingo_client_t *c,
                                     const char *json,
                                     cJSON **out_data)
{
    *out_data = NULL;
    cJSON *root = cJSON_Parse(json);
    if (!root) {
        set_error(c, "json parse failed");
        return RELINGO_ERR_PARSE;
    }
    cJSON *code = cJSON_GetObjectItemCaseSensitive(root, "code");
    cJSON *msg  = cJSON_GetObjectItemCaseSensitive(root, "message");
    cJSON *data = cJSON_GetObjectItemCaseSensitive(root, "data");

    int cv = cJSON_IsNumber(code) ? (int)code->valuedouble : -1;
    if (cv != 0) {
        set_error(c, "api error %d: %s", cv,
                  cJSON_IsString(msg) ? msg->valuestring : "(no message)");
    }
    *out_data = data ? cJSON_Duplicate(data, 1) : NULL;
    cJSON_Delete(root);

    if (cv == 0) return RELINGO_OK;
    if (cv > 0)  return RELINGO_ERR_API;
    return RELINGO_ERR_PARSE;
}

static char *jstr_or_null(cJSON *o)
{
    return (o && cJSON_IsString(o)) ? strdup(o->valuestring) : NULL;
}

/* Read a string field from a cJSON object, falling back to alt names. */
static char *jstr_field(cJSON *obj, const char *primary, const char *fallback)
{
    cJSON *v = cJSON_GetObjectItemCaseSensitive(obj, primary);
    if (!v || !cJSON_IsString(v)) v = cJSON_GetObjectItemCaseSensitive(obj, fallback);
    return (v && cJSON_IsString(v)) ? strdup(v->valuestring) : NULL;
}

/* Extract a single word entry into `out`. */
static relingo_status extract_word(cJSON *w, relingo_word_t *out)
{
    out->word = jstr_field(w, "word", "text");
    out->phonetic = jstr_or_null(cJSON_GetObjectItemCaseSensitive(w, "phonetic"));
    out->translations = NULL;
    out->n_translations = 0;

    cJSON *trs = cJSON_GetObjectItemCaseSensitive(w, "translations");
    if (!cJSON_IsArray(trs)) return RELINGO_OK;

    int n = cJSON_GetArraySize(trs);
    if (n <= 0) return RELINGO_OK;

    out->translations = calloc((size_t)n, sizeof(char *));
    if (!out->translations) return RELINGO_ERR_NOMEM;
    out->n_translations = 0;

    for (int i = 0; i < n; i++) {
        cJSON *t = cJSON_GetArrayItem(trs, i);
        const char *s = NULL;
        if (cJSON_IsString(t)) {
            s = t->valuestring;
        } else if (cJSON_IsObject(t)) {
            cJSON *v;
            if ((v = cJSON_GetObjectItemCaseSensitive(t, "translation")) && cJSON_IsString(v))
                s = v->valuestring;
            else if ((v = cJSON_GetObjectItemCaseSensitive(t, "text")) && cJSON_IsString(v))
                s = v->valuestring;
            else if ((v = cJSON_GetObjectItemCaseSensitive(t, "meaning")) && cJSON_IsString(v))
                s = v->valuestring;
        }
        if (!s) continue;
        out->translations[out->n_translations] = strdup(s);
        if (!out->translations[out->n_translations]) return RELINGO_ERR_NOMEM;
        out->n_translations++;
    }
    return RELINGO_OK;
}

/* --- Free helpers --- */

void relingo_word_free(relingo_word_t *w)
{
    if (!w) return;
    free(w->word);
    free(w->phonetic);
    if (w->translations) {
        for (size_t i = 0; i < w->n_translations; i++) free(w->translations[i]);
        free(w->translations);
    }
    w->word = w->phonetic = NULL;
    w->translations = NULL;
    w->n_translations = 0;
}

void relingo_config_free(relingo_config_t *cfg)
{
    if (!cfg) return;
    free(cfg->strange_book);
    free(cfg->mastered_book);
    if (cfg->custom_books) {
        for (size_t i = 0; i < cfg->n_custom_books; i++) free(cfg->custom_books[i]);
        free(cfg->custom_books);
    }
    memset(cfg, 0, sizeof(*cfg));
}

void relingo_login_free(relingo_login_t *r)
{
    if (!r) return;
    free(r->name);
    free(r->token);
    memset(r, 0, sizeof(*r));
}

/* --- Authentication --- */

relingo_status relingo_authorization(relingo_client_t *c, const char *email)
{
    if (!c || !email) return RELINGO_ERR_INVALID;

    cJSON *req = cJSON_CreateObject();
    cJSON_AddStringToObject(req, "email", email);
    char *body = cJSON_PrintUnformatted(req);
    cJSON_Delete(req);
    if (!body) return RELINGO_ERR_NOMEM;

    char *resp = NULL;
    relingo_status rc = http_post(c, "/api/authorization", body, &resp);
    free(body);
    if (rc != RELINGO_OK) return rc;

    cJSON *data = NULL;
    rc = parse_envelope(c, resp, &data);
    free(resp);
    cJSON_Delete(data);
    return rc;
}

relingo_status relingo_login_by_code(relingo_client_t *c,
    const char *email, const char *code, relingo_login_t *out)
{
    if (!c || !email || !code || !out) return RELINGO_ERR_INVALID;
    memset(out, 0, sizeof(*out));

    cJSON *req = cJSON_CreateObject();
    cJSON_AddStringToObject(req, "email", email);
    cJSON_AddStringToObject(req, "code", code);
    char *body = cJSON_PrintUnformatted(req);
    cJSON_Delete(req);
    if (!body) return RELINGO_ERR_NOMEM;

    char *resp = NULL;
    relingo_status rc = http_post(c, "/api/loginByCode", body, &resp);
    free(body);
    if (rc != RELINGO_OK) return rc;

    cJSON *data = NULL;
    rc = parse_envelope(c, resp, &data);
    free(resp);
    if (rc != RELINGO_OK) { cJSON_Delete(data); return rc; }

    out->name      = jstr_or_null(cJSON_GetObjectItemCaseSensitive(data, "name"));
    out->token     = jstr_or_null(cJSON_GetObjectItemCaseSensitive(data, "token"));
    cJSON *ea      = cJSON_GetObjectItemCaseSensitive(data, "expiredAt");
    out->expired_at = cJSON_IsNumber(ea) ? (long long)ea->valuedouble : 0;
    cJSON_Delete(data);

    if (!out->token) {
        relingo_login_free(out);
        return RELINGO_ERR_PARSE;
    }
    return RELINGO_OK;
}

/* --- User --- */

relingo_status relingo_get_user_info(relingo_client_t *c, char **out_token)
{
    if (!c || !out_token) return RELINGO_ERR_INVALID;
    *out_token = NULL;

    char *resp = NULL;
    relingo_status rc = http_post(c, "/api/getUserInfo", "{}", &resp);
    if (rc != RELINGO_OK) return rc;

    cJSON *data = NULL;
    rc = parse_envelope(c, resp, &data);
    free(resp);
    if (rc != RELINGO_OK) { cJSON_Delete(data); return rc; }

    *out_token = jstr_or_null(cJSON_GetObjectItemCaseSensitive(data, "token"));
    cJSON_Delete(data);
    if (!*out_token) return RELINGO_ERR_PARSE;
    return RELINGO_OK;
}

relingo_status relingo_get_user_config(relingo_client_t *c, relingo_config_t *out)
{
    if (!c || !out) return RELINGO_ERR_INVALID;
    memset(out, 0, sizeof(*out));

    char *resp = NULL;
    relingo_status rc = http_post(c, "/api/getUserConfig", "{}", &resp);
    if (rc != RELINGO_OK) return rc;

    cJSON *data = NULL;
    rc = parse_envelope(c, resp, &data);
    free(resp);
    if (rc != RELINGO_OK) { cJSON_Delete(data); return rc; }

    cJSON *cfg        = cJSON_GetObjectItemCaseSensitive(data, "config");
    cJSON *lang_books = cfg ? cJSON_GetObjectItemCaseSensitive(cfg, "langBooks") : NULL;
    cJSON *en         = lang_books ? cJSON_GetObjectItemCaseSensitive(lang_books, "en") : NULL;
    if (!cJSON_IsArray(en)) {
        cJSON_Delete(data);
        set_error(c, "config: langBooks.en not found");
        return RELINGO_ERR_PARSE;
    }

    int n = cJSON_GetArraySize(en);

    /* Count custom (active, non-strange, non-mastered) books first. */
    int custom_count = 0;
    for (int i = 0; i < n; i++) {
        cJSON *book  = cJSON_GetArrayItem(en, i);
        cJSON *name  = cJSON_GetObjectItemCaseSensitive(book, "name");
        cJSON *active = cJSON_GetObjectItemCaseSensitive(book, "active");
        if (!cJSON_IsString(name)) continue;
        if (!strcmp(name->valuestring, "strange")) continue;
        if (!strcmp(name->valuestring, "mastered")) continue;
        if (cJSON_IsTrue(active)) custom_count++;
    }

    if (custom_count > 0) {
        out->custom_books = calloc((size_t)custom_count, sizeof(char *));
        if (!out->custom_books) { cJSON_Delete(data); return RELINGO_ERR_NOMEM; }
        int k = 0;
        for (int i = 0; i < n && k < custom_count; i++) {
            cJSON *book   = cJSON_GetArrayItem(en, i);
            cJSON *name   = cJSON_GetObjectItemCaseSensitive(book, "name");
            cJSON *active = cJSON_GetObjectItemCaseSensitive(book, "active");
            if (!cJSON_IsString(name)) continue;
            if (!strcmp(name->valuestring, "strange")) continue;
            if (!strcmp(name->valuestring, "mastered")) continue;
            if (!cJSON_IsTrue(active)) continue;
            char *id = jstr_field(book, "_id", "id");
            if (id) out->custom_books[k++] = id;
        }
        out->n_custom_books = (size_t)k;
    }

    /* Pick up strange and mastered. */
    for (int i = 0; i < n; i++) {
        cJSON *book = cJSON_GetArrayItem(en, i);
        cJSON *name = cJSON_GetObjectItemCaseSensitive(book, "name");
        if (!cJSON_IsString(name)) continue;
        char *id = jstr_field(book, "_id", "id");
        if (!id) continue;
        if (!strcmp(name->valuestring, "strange") && !out->strange_book) {
            out->strange_book = id;
        } else if (!strcmp(name->valuestring, "mastered") && !out->mastered_book) {
            out->mastered_book = id;
        } else {
            free(id);
        }
    }

    cJSON_Delete(data);
    return RELINGO_OK;
}

/* --- Word lookup --- */

relingo_status relingo_parse_content3(relingo_client_t *c,
    const char *to,
    const char *const *vocab_ids, size_t n_vocab,
    const char *word,
    relingo_word_t *out)
{
    if (!c || !to || !word || !out) return RELINGO_ERR_INVALID;
    memset(out, 0, sizeof(*out));

    cJSON *req = cJSON_CreateObject();
    cJSON_AddStringToObject(req, "to", to);

    cJSON *words = cJSON_AddArrayToObject(req, "words");
    cJSON_AddItemToArray(words, cJSON_CreateString(word));

    cJSON *vocab = cJSON_AddArrayToObject(req, "vocabulary");
    for (size_t i = 0; i < n_vocab; i++) {
        if (vocab_ids && vocab_ids[i])
            cJSON_AddItemToArray(vocab, cJSON_CreateString(vocab_ids[i]));
    }
    cJSON_AddBoolToObject(req, "definition", 0);

    char *body = cJSON_PrintUnformatted(req);
    cJSON_Delete(req);
    if (!body) return RELINGO_ERR_NOMEM;

    char *resp = NULL;
    relingo_status rc = http_post(c, "/api/parseContent3", body, &resp);
    free(body);
    if (rc != RELINGO_OK) return rc;

    cJSON *data = NULL;
    rc = parse_envelope(c, resp, &data);
    free(resp);
    if (rc != RELINGO_OK) { cJSON_Delete(data); return rc; }

    cJSON *arr = cJSON_GetObjectItemCaseSensitive(data, "words");
    if (!cJSON_IsArray(arr) || cJSON_GetArraySize(arr) == 0) {
        cJSON_Delete(data);
        set_error(c, "word not in vocabulary");
        return RELINGO_ERR_NOT_FOUND;
    }

    rc = extract_word(cJSON_GetArrayItem(arr, 0), out);
    cJSON_Delete(data);
    return rc;
}

relingo_status relingo_lookup_dict2(relingo_client_t *c,
    const char *to,
    const char *word,
    relingo_word_t *out)
{
    if (!c || !to || !word || !out) return RELINGO_ERR_INVALID;
    memset(out, 0, sizeof(*out));

    cJSON *req = cJSON_CreateObject();
    cJSON_AddStringToObject(req, "to", to);

    cJSON *words = cJSON_AddArrayToObject(req, "words");
    cJSON_AddItemToArray(words, cJSON_CreateString(word));

    char *body = cJSON_PrintUnformatted(req);
    cJSON_Delete(req);
    if (!body) return RELINGO_ERR_NOMEM;

    char *resp = NULL;
    relingo_status rc = http_post(c, "/api/lookupDict2", body, &resp);
    free(body);
    if (rc != RELINGO_OK) return rc;

    cJSON *data = NULL;
    rc = parse_envelope(c, resp, &data);
    free(resp);
    if (rc != RELINGO_OK) { cJSON_Delete(data); return rc; }

    if (!cJSON_IsArray(data) || cJSON_GetArraySize(data) == 0) {
        cJSON_Delete(data);
        set_error(c, "word not in dictionary");
        return RELINGO_ERR_NOT_FOUND;
    }

    rc = extract_word(cJSON_GetArrayItem(data, 0), out);
    cJSON_Delete(data);
    return rc;
}

/* --- Vocabulary operations --- */

static relingo_status vocabulary_op(relingo_client_t *c,
    const char *endpoint,
    const char *mastered_book_id,
    const char *type,
    const char *word)
{
    if (!c || !mastered_book_id || !type || !word) return RELINGO_ERR_INVALID;

    cJSON *req = cJSON_CreateObject();
    cJSON_AddStringToObject(req, "id", mastered_book_id);
    cJSON_AddStringToObject(req, "type", type);
    cJSON *words = cJSON_AddArrayToObject(req, "words");
    cJSON_AddItemToArray(words, cJSON_CreateString(word));

    char *body = cJSON_PrintUnformatted(req);
    cJSON_Delete(req);
    if (!body) return RELINGO_ERR_NOMEM;

    char *resp = NULL;
    relingo_status rc = http_post(c, endpoint, body, &resp);
    free(body);
    if (rc != RELINGO_OK) return rc;

    cJSON *data = NULL;
    rc = parse_envelope(c, resp, &data);
    free(resp);
    cJSON_Delete(data);
    return rc;
}

relingo_status relingo_submit_vocabulary(relingo_client_t *c,
    const char *mastered_book_id, const char *word)
{
    return vocabulary_op(c, "/api/submitVocabulary",
                         mastered_book_id, "mastered", word);
}

relingo_status relingo_remove_vocabulary_words(relingo_client_t *c,
    const char *mastered_book_id, const char *word)
{
    return vocabulary_op(c, "/api/removeVocabularyWords",
                         mastered_book_id, "strange", word);
}

/* --- Translation --- */

relingo_status relingo_translate_paragraph(relingo_client_t *c,
    const char *text, const char *to, const char *provider_id,
    char **out)
{
    if (!c || !text || !to || !provider_id || !out) return RELINGO_ERR_INVALID;
    *out = NULL;

    cJSON *req = cJSON_CreateObject();
    cJSON_AddStringToObject(req, "text", text);
    cJSON_AddStringToObject(req, "to", to);
    cJSON_AddStringToObject(req, "providerId", provider_id);
    char *body = cJSON_PrintUnformatted(req);
    cJSON_Delete(req);
    if (!body) return RELINGO_ERR_NOMEM;

    char *resp = NULL;
    relingo_status rc = http_post(c, "/api/translateParagraph", body, &resp);
    free(body);
    if (rc != RELINGO_OK) return rc;

    /* TODO: verify actual response shape via curl before parsing. */
    *out = resp;
    return RELINGO_OK;
}
