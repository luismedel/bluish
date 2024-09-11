
from test.utils import create_workflow

import pytest
from bluish.core import init_commands


@pytest.fixture(scope="session", autouse=True)
def initialize_commands():
    init_commands()


@pytest.mark.docker
def test_docker_checkout() -> None:
    wf = create_workflow("""
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
    _ = wf.dispatch()
    assert wf.jobs["checkout"].result.stdout == "# Bluish"


@pytest.mark.docker
def test_docker_checkout_alpine() -> None:
    wf = create_workflow("""
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
    _ = wf.dispatch()
    assert wf.jobs["checkout"].result.stdout == "# Bluish"
