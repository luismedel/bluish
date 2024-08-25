from typing import Never


def _log(decorator: str, msg: str) -> None:
    print(f"{decorator} {msg}")


def info(msg: str) -> None:
    _log("[i]", msg)


def error(msg: str) -> None:
    _log("[!]", msg)


def success(msg: str) -> None:
    _log("[+]", msg)


def warn(msg: str) -> None:
    _log("[w]", msg)


def fatal(msg: str) -> Never:
    error(msg)
    exit(1)
