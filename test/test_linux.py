
from test.utils import create_workflow

import pytest
from bluish.core import init_commands


@pytest.fixture(scope="session", autouse=True)
def initialize_commands():
    init_commands()


@pytest.mark.docker
def test_install_packages_ubuntu() -> None:
    wf = create_workflow("""
jobs:
  test_job:
    runs_on: docker://ubuntu:latest
    steps:
      - uses: linux/install-packages
        with:
          packages:
            - moreutils
            - jq
""")
    _ = wf.dispatch()
    assert wf.jobs["test_job"].result.failed is False


@pytest.mark.docker
def test_install_packages_alpine() -> None:
    wf = create_workflow("""
jobs:
  test_job:
    runs_on: docker://alpine:latest
    steps:
      - uses: linux/install-packages
        with:
          packages:
            - moreutils
            - jq
""")
    _ = wf.dispatch()
    assert wf.jobs["test_job"].result.failed is False


@pytest.mark.docker
def test_install_packages_failed() -> None:
    wf = create_workflow("""
jobs:
  test_job:
    runs_on: docker://alpine:latest
    steps:
      - uses: linux/install-packages
        with:
          packages:
              - thispackagedoesnotexist-1.0.0
""")
    _ = wf.dispatch()
    assert wf.jobs["test_job"].result.failed
