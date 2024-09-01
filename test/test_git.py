
from test.utils import create_pipe

import pytest
from bluish.core import init_commands


@pytest.fixture(scope="session", autouse=True)
def initialize_commands():
    init_commands()


def test_docker_checkout() -> None:
    pipe = create_pipe("""
jobs:
  checkout:
    runs_on: docker://ubuntu:latest
    steps:
      - uses: git/checkout
        with:
          repository: https://github.com/luismedel/bluish.git
      - run: |
          head -n1 README.md
""")
    pipe.dispatch()
    assert pipe.jobs["checkout"].output == "# Bluish"


def test_docker_checkout_alpine() -> None:
    pipe = create_pipe("""
jobs:
  checkout:
    runs_on: docker://alpine:latest
    steps:
      - uses: git/checkout
        with:
          repository: https://github.com/luismedel/bluish.git
      - run: |
          head -n1 README.md
""")
    pipe.dispatch()
    assert pipe.jobs["checkout"].output == "# Bluish"
