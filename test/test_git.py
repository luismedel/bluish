
from test.utils import create_workflow

import pytest
from bluish.core import init_commands


@pytest.fixture(scope="session", autouse=True)
def initialize_commands():
    init_commands()


def test_docker_public_checkout() -> None:
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
    assert wf.jobs["checkout"].result.stdout == "[![justforfunnoreally.dev badge](https://img.shields.io/badge/justforfunnoreally-dev-9ff)](https://justforfunnoreally.dev)"

