/*
 * example.c - end-to-end usage:
 *   1. send verification code
 *   2. prompt for the code, log in
 *   3. fetch user wordbooks
 *   4. look up a word in the user's books (fallback to official dict)
 *   5. translate a paragraph
 *
 * Usage: example <email> [word]
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "relingo.h"

/* Read a line from stdin, trimming the trailing newline. */
static int read_line(char *buf, size_t cap, const char *prompt)
{
    if (prompt) { fputs(prompt, stdout); fflush(stdout); }
    if (!fgets(buf, (int)cap, stdin)) return 0;
    size_t n = strlen(buf);
    while (n > 0 && (buf[n-1] == '\n' || buf[n-1] == '\r')) buf[--n] = '\0';
    return n > 0;
}

static int lookup(relingo_client_t *c, relingo_config_t *cfg, const char *word)
{
    relingo_word_t w;
    relingo_status rc;

    /* Try user's own wordbooks first. */
    const char *vocab[16];
    size_t n = 0;
    if (cfg->strange_book) vocab[n++] = cfg->strange_book;
    for (size_t i = 0; i < cfg->n_custom_books && n < 16; i++)
        vocab[n++] = cfg->custom_books[i];

    rc = relingo_parse_content3(c, "zh-CN", vocab, n, word, &w);
    if (rc == RELINGO_ERR_NOT_FOUND) {
        rc = relingo_lookup_dict2(c, "zh-CN", word, &w);
    }
    if (rc != RELINGO_OK) {
        fprintf(stderr, "lookup '%s': %s\n", word, relingo_client_last_error(c));
        return 1;
    }

    printf("%s", w.word ? w.word : word);
    if (w.phonetic) printf(" [%s]", w.phonetic);
    printf("\n");
    for (size_t i = 0; i < w.n_translations; i++)
        printf("  - %s\n", w.translations[i]);
    relingo_word_free(&w);
    return 0;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        fprintf(stderr, "usage: %s <email> [word]\n", argv[0]);
        return 1;
    }
    const char *email = argv[1];
    const char *word  = argc >= 3 ? argv[2] : "hello";

    relingo_client_t *c = relingo_client_new("en");
    if (!c) { fprintf(stderr, "client init failed\n"); return 1; }

    relingo_status rc;

    rc = relingo_authorization(c, email);
    if (rc != RELINGO_OK) {
        fprintf(stderr, "authorization: %s\n", relingo_client_last_error(c));
        goto done;
    }
    printf("verification code sent to %s\n", email);

    char code[64];
    if (!read_line(code, sizeof(code), "enter code: ")) {
        fprintf(stderr, "no code entered\n");
        goto done;
    }

    relingo_login_t login;
    rc = relingo_login_by_code(c, email, code, &login);
    if (rc != RELINGO_OK) {
        fprintf(stderr, "login: %s\n", relingo_client_last_error(c));
        goto done;
    }
    printf("logged in as %s\n", login.name ? login.name : "(unknown)");

    relingo_client_set_token(c, login.token);
    relingo_login_free(&login);

    relingo_config_t cfg;
    rc = relingo_get_user_config(c, &cfg);
    if (rc != RELINGO_OK) {
        fprintf(stderr, "config: %s\n", relingo_client_last_error(c));
        goto done;
    }
    printf("strange_book  = %s\n", cfg.strange_book  ? cfg.strange_book  : "(none)");
    printf("mastered_book = %s\n", cfg.mastered_book ? cfg.mastered_book : "(none)");
    printf("custom_books  = %zu\n", cfg.n_custom_books);

    lookup(c, &cfg, word);

    char *translated = NULL;
    rc = relingo_translate_paragraph(c, "Hello, world.", "zh-CN", "1", &translated);
    if (rc == RELINGO_OK) {
        printf("translation: %s\n", translated);
        free(translated);
    } else {
        fprintf(stderr, "translate: %s\n", relingo_client_last_error(c));
    }

    relingo_config_free(&cfg);

done:
    relingo_client_free(c);
    return 0;
}
