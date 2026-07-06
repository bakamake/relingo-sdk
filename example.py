#!/usr/bin/env python3
"""
example.py - Relingo CLI built on top of the relingo Python SDK.

Subcommands (all read a saved token from disk by default; run `login` once):

    login    <email>        send verification code, prompt for it, persist token
    logout                  remove the saved token from disk
    whoami                  show the current account / token status
    config                  show wordbook ids (strange / mastered / custom)
    list                    list wordbooks (alias of `config`)
    add     <word>          mark a word as mastered
    remove  <word>          mark a word as forgotten (move back to strange)
    lookup  <word>          look up a word in user books, fallback to dict
                            (with case-insensitive retry: "Alpine" -> "alpine")
    translate --provider ID <text...>
                            translate a paragraph

Legacy usage (still works, equivalent to a one-shot demo):

    python3 example.py <email> [word]
"""

import argparse
import json
import os
import sys
import tempfile
import time

import relingo


# --- Credentials (plaintext, file mode 0600) -------------------------------

CREDENTIALS_DIR_MODE = 0o700
CREDENTIALS_FILE_MODE = 0o600


def _credentials_path():
    """Return the path to the credentials file (XDG / platform-default)."""
    xdg = os.environ.get("RELINGO_CONFIG")
    if xdg:
        base = xdg
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        base = os.path.join(appdata, "Relingo") if appdata else os.path.expanduser("~/.relingo")
    else:
        xdg_config = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        base = os.path.join(xdg_config, "relingo")
    return os.path.join(base, "credentials.json")


def _credentials_load():
    """Load saved credentials, or return None if no file / unreadable."""
    path = _credentials_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"credentials: failed to read {path}: {exc}\n")
        return None
    if not isinstance(data, dict):
        return None
    token = data.get("token")
    if not isinstance(token, str) or not token:
        return None
    return data


def _credentials_save(email, login):
    """Persist login info atomically with 0600 file mode."""
    path = _credentials_path()
    parent = os.path.dirname(path)
    os.makedirs(parent, mode=CREDENTIALS_DIR_MODE, exist_ok=True)
    try:
        os.chmod(parent, CREDENTIALS_DIR_MODE)
    except OSError:
        pass

    payload = {
        "email": email,
        "token": login.token,
        "expired_at": int(login.expired_at),
        "saved_at": int(time.time() * 1000),
    }

    fd, tmp = tempfile.mkstemp(prefix=".credentials-", dir=parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.chmod(path, CREDENTIALS_FILE_MODE)
    return path


def _credentials_clear():
    path = _credentials_path()
    try:
        os.unlink(path)
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        sys.stderr.write(f"credentials: failed to remove {path}: {exc}\n")
        return False


def _mask_token(token):
    if not token:
        return "(none)"
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"


# --- Helpers ---------------------------------------------------------------

LANG = "en"
TRANSLATE_TARGET = "zh-CN"


def _read_line(prompt):
    if prompt:
        sys.stdout.write(prompt)
        sys.stdout.flush()
    line = sys.stdin.readline()
    if not line:
        return None
    return line.rstrip("\r\n")


def _new_client():
    c = relingo.relingo_client_new(LANG)
    if c is None:
        sys.stderr.write("client init failed\n")
        sys.exit(1)
    return c


def _client_from_credentials(require=True):
    """Build a client with the saved token. If `require` is False and no
    credentials exist, return a client without a token (useful for login)."""
    creds = _credentials_load()
    c = _new_client()
    if creds is None:
        if require:
            sys.stderr.write(
                f"not logged in. run '{_prog_name()} login <email>' first.\n"
            )
            relingo.relingo_client_free(c)
            sys.exit(2)
        return c
    relingo.relingo_client_set_token(c, creds["token"])
    return c


def _check_expiry(creds):
    """Return True if the local timestamp says the token has expired."""
    ea = creds.get("expired_at")
    if not isinstance(ea, int) or ea <= 0:
        return False
    return time.time() * 1000 >= ea


def _prog_name():
    return os.path.basename(sys.argv[0]) if sys.argv else "example.py"


# --- Subcommands -----------------------------------------------------------

def cmd_login(args):
    creds = _credentials_load()
    if creds is not None and creds.get("email") == args.email:
        sys.stderr.write(
            f"already logged in as {creds.get('email')} ({_mask_token(creds.get('token'))}).\n"
            f"use '{_prog_name()} logout' first if you want to switch accounts.\n"
        )
        return 0

    c = _new_client()
    try:
        rc = relingo.relingo_authorization(c, args.email)
        if rc != relingo.RELINGO_OK:
            sys.stderr.write(
                f"authorization: {relingo.relingo_client_last_error(c)}\n"
            )
            return 1
        print(f"verification code sent to {args.email}")

        code = _read_line("enter code: ")
        if not code:
            sys.stderr.write("no code entered\n")
            return 1

        login = relingo.RelingoLogin()
        try:
            rc = relingo.relingo_login_by_code(c, args.email, code, login)
            if rc != relingo.RELINGO_OK:
                sys.stderr.write(f"login: {relingo.relingo_client_last_error(c)}\n")
                return 1

            path = _credentials_save(args.email, login)
            print(f"logged in as {login.name or '(unknown)'}")
            print(f"credentials saved to {path}")
            return 0
        finally:
            relingo.relingo_login_free(login)
    finally:
        relingo.relingo_client_free(c)


def cmd_logout(args):
    if _credentials_clear():
        print("logged out")
    else:
        print("no saved credentials")
    return 0


def cmd_whoami(args):
    creds = _credentials_load()
    if creds is None:
        print("not logged in")
        return 0

    print(f"email     = {creds.get('email') or '(<unknown>)'}")
    print(f"token     = {_mask_token(creds.get('token'))}")
    ea = creds.get("expired_at")
    if isinstance(ea, int) and ea > 0:
        print(f"expired_at = {ea}")
        if _check_expiry(creds):
            print("status    = expired (local timestamp); please run `login` again")
        else:
            print("status    = ok (local timestamp)")
    else:
        print("expired_at = (unknown)")
    return 0


def _get_config(c):
    cfg = relingo.RelingoConfig()
    rc = relingo.relingo_get_user_config(c, cfg)
    if rc != relingo.RELINGO_OK:
        sys.stderr.write(f"config: {relingo.relingo_client_last_error(c)}\n")
        relingo.relingo_client_free(c)
        sys.exit(1)
    return cfg


def cmd_config(args):
    c = _client_from_credentials()
    try:
        cfg = _get_config(c)
        try:
            print(f"strange_book  = {cfg.strange_book or '(<none>)'}")
            print(f"mastered_book = {cfg.mastered_book or '(<none>)'}")
            print(f"custom_books  = {cfg.n_custom_books}")
            for i, bid in enumerate(cfg.custom_books):
                print(f"  [{i}] {bid}")
            return 0
        finally:
            relingo.relingo_config_free(cfg)
    finally:
        relingo.relingo_client_free(c)


def cmd_list(args):
    return cmd_config(args)


def _do_vocab_op(c, word, op_name, sdk_fn):
    cfg = _get_config(c)
    try:
        if not cfg.mastered_book:
            sys.stderr.write(
                f"{op_name}: no mastered_book configured for this account.\n"
            )
            return 1
        rc = sdk_fn(c, cfg.mastered_book, word)
        if rc != relingo.RELINGO_OK:
            sys.stderr.write(
                f"{op_name} '{word}': {relingo.relingo_client_last_error(c)}\n"
            )
            return 1
        print(f"{op_name} '{word}': ok")
        return 0
    finally:
        relingo.relingo_config_free(cfg)


def cmd_add(args):
    c = _client_from_credentials()
    try:
        return _do_vocab_op(c, args.word, "add", relingo.relingo_submit_vocabulary)
    finally:
        relingo.relingo_client_free(c)


def cmd_remove(args):
    c = _client_from_credentials()
    try:
        return _do_vocab_op(c, args.word, "remove", relingo.relingo_remove_vocabulary_words)
    finally:
        relingo.relingo_client_free(c)


def _lookup_word(c, vocab, n_vocab, word, out):
    """Try user wordbooks first, then official dict. Returns the rc."""
    r = relingo.relingo_parse_content3(
        c, TRANSLATE_TARGET, vocab, n_vocab, word, out
    )
    if r == relingo.RELINGO_ERR_NOT_FOUND:
        r = relingo.relingo_lookup_dict2(c, TRANSLATE_TARGET, word, out)
    return r


def cmd_lookup(args):
    c = _client_from_credentials()
    try:
        cfg = _get_config(c)
        try:
            w = relingo.RelingoWord()
            vocab = []
            if cfg.strange_book:
                vocab.append(cfg.strange_book)
            for cb in cfg.custom_books[: 16 - len(vocab)]:
                vocab.append(cb)
            n_vocab = len(vocab)

            # Case-insensitive fallback: try the user's input as-is first,
            # then lowercase if both stages miss. Most dictionaries only
            # index lowercase headwords, so this catches "Alpine" -> "alpine".
            matched_word = args.word
            rc = _lookup_word(c, vocab, n_vocab, args.word, w)
            if rc == relingo.RELINGO_ERR_NOT_FOUND and args.word != args.word.lower():
                rc = _lookup_word(c, vocab, n_vocab, args.word.lower(), w)
                if rc == relingo.RELINGO_OK:
                    matched_word = args.word.lower()
            if rc != relingo.RELINGO_OK:
                sys.stderr.write(
                    f"lookup '{args.word}': {relingo.relingo_client_last_error(c)}\n"
                )
                return 1

            sys.stdout.write(w.word if w.word else matched_word)
            if w.phonetic:
                sys.stdout.write(f" [{w.phonetic}]")
            if matched_word != args.word:
                sys.stdout.write(f"  (matched '{matched_word}')")
            sys.stdout.write("\n")
            for t in w.translations:
                sys.stdout.write(f"  - {t}\n")
            relingo.relingo_word_free(w)
            return 0
        finally:
            relingo.relingo_config_free(cfg)
    finally:
        relingo.relingo_client_free(c)


def cmd_translate(args):
    c = _client_from_credentials()
    try:
        text = " ".join(args.text) if args.text else ""
        if not text:
            sys.stderr.write("translate: empty text\n")
            return 1
        out = [None]
        rc = relingo.relingo_translate_paragraph(c, text, TRANSLATE_TARGET, args.provider, out)
        if rc != relingo.RELINGO_OK:
            sys.stderr.write(
                f"translate: {relingo.relingo_client_last_error(c)}\n"
            )
            return 1
        print(out[0] if out[0] is not None else "")
        return 0
    finally:
        relingo.relingo_client_free(c)


# --- Legacy one-shot usage -------------------------------------------------

def legacy_main(argv):
    if len(argv) < 2:
        sys.stderr.write(f"usage: {argv[0]} <email> [word]\n")
        return 1
    email = argv[1]
    word = argv[2] if len(argv) >= 3 else "hello"

    c = _new_client()
    try:
        rc = relingo.relingo_authorization(c, email)
        if rc != relingo.RELINGO_OK:
            sys.stderr.write(
                f"authorization: {relingo.relingo_client_last_error(c)}\n"
            )
            return 1
        print(f"verification code sent to {email}")

        code = _read_line("enter code: ")
        if not code:
            sys.stderr.write("no code entered\n")
            return 1

        login = relingo.RelingoLogin()
        rc = relingo.relingo_login_by_code(c, email, code, login)
        if rc != relingo.RELINGO_OK:
            sys.stderr.write(f"login: {relingo.relingo_client_last_error(c)}\n")
            return 1
        print(f"logged in as {login.name or '(unknown)'}")
        relingo.relingo_client_set_token(c, login.token)

        cfg = relingo.RelingoConfig()
        rc = relingo.relingo_get_user_config(c, cfg)
        if rc != relingo.RELINGO_OK:
            sys.stderr.write(f"config: {relingo.relingo_client_last_error(c)}\n")
            return 1
        print(f"strange_book  = {cfg.strange_book or '(none)'}")
        print(f"mastered_book = {cfg.mastered_book or '(none)'}")
        print(f"custom_books  = {cfg.n_custom_books}")

        w = relingo.RelingoWord()
        vocab = []
        if cfg.strange_book:
            vocab.append(cfg.strange_book)
        for cb in cfg.custom_books[: 16 - len(vocab)]:
            vocab.append(cb)
        n_vocab = len(vocab)
        rc = _lookup_word(c, vocab, n_vocab, word, w)
        if rc == relingo.RELINGO_OK:
            sys.stdout.write(w.word if w.word else word)
            if w.phonetic:
                sys.stdout.write(f" [{w.phonetic}]")
            sys.stdout.write("\n")
            for t in w.translations:
                sys.stdout.write(f"  - {t}\n")
            relingo.relingo_word_free(w)

        out = [None]
        rc = relingo.relingo_translate_paragraph(c, "Hello, world.", TRANSLATE_TARGET, "1", out)
        if rc == relingo.RELINGO_OK:
            print(f"translation: {out[0]}")

        relingo.relingo_config_free(cfg)
        return 0
    finally:
        relingo.relingo_client_free(c)


# --- Entry point -----------------------------------------------------------

def _build_parser():
    p = argparse.ArgumentParser(
        prog="relingo",
        description="Relingo CLI - login, manage words, translate.",
    )
    sub = p.add_subparsers(dest="cmd")

    p_login = sub.add_parser("login", help="log in with email + verification code")
    p_login.add_argument("email")
    p_login.set_defaults(func=cmd_login)

    p_logout = sub.add_parser("logout", help="remove the saved credentials")
    p_logout.set_defaults(func=cmd_logout)

    p_whoami = sub.add_parser("whoami", help="show current account / token status")
    p_whoami.set_defaults(func=cmd_whoami)

    p_config = sub.add_parser("config", help="show wordbook ids")
    p_config.set_defaults(func=cmd_config)

    p_list = sub.add_parser("list", help="list wordbooks (alias of `config`)")
    p_list.set_defaults(func=cmd_list)

    p_add = sub.add_parser("add", help="mark a word as mastered")
    p_add.add_argument("word")
    p_add.set_defaults(func=cmd_add)

    p_remove = sub.add_parser("remove", help="mark a word as forgotten")
    p_remove.add_argument("word")
    p_remove.set_defaults(func=cmd_remove)

    p_lookup = sub.add_parser("lookup", help="look up a word")
    p_lookup.add_argument("word")
    p_lookup.set_defaults(func=cmd_lookup)

    p_tr = sub.add_parser("translate", help="translate a paragraph")
    p_tr.add_argument("--provider", required=True, help="translation provider id")
    p_tr.add_argument("text", nargs=argparse.REMAINDER, help="text to translate")
    p_tr.set_defaults(func=cmd_translate)

    return p


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)

    # Legacy: `python3 example.py <email> [word]` (no subcommand)
    if len(argv) >= 2 and not argv[1].startswith("-") and argv[1] not in {
        "login", "logout", "whoami", "config", "list",
        "add", "remove", "lookup", "translate",
        "-h", "--help", "help",
    }:
        return legacy_main(argv)

    parser = _build_parser()
    args = parser.parse_args(argv[1:])
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
