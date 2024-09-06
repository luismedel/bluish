import pytest
from pytest import Config, Parser


def pytest_addoption(parser: Parser) -> None:
    parser.addoption(
        "--run-docker", action="store_true", default=False, help="run Docker tests"
    )


def pytest_configure(config: Config) -> None:
    config.addinivalue_line("markers", "docker: mark test is dependant of Docker (so, slow to run)")


def pytest_collection_modifyitems(config: Config, items: list) -> None:
    if config.getoption("--run-docker"):
        return

    skip_docker = pytest.mark.skip(reason="need --run-docker option to run")
    for item in items:
        if "docker" in item.keywords:
            item.add_marker(skip_docker)
