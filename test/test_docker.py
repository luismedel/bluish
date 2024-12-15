
from io import FileIO
from test.utils import create_workflow

import pytest
from bluish.core import init_commands, reset_commands


@pytest.fixture(scope="session", autouse=True)
def initialize_commands():
    init_commands()
    yield
    reset_commands()


#@pytest.mark.docker
def test_docker_build(temp_file: FileIO) -> None:
    filename = str(temp_file.name)

    wf = create_workflow(None, f"""
jobs:
    create-docker:
        steps:
            - name: "Build Alpine Dockerfile"
              uses: core/expand-template
              with:
                  input: |
                      FROM alpine:latest
                      RUN apk add --no-cache python3 py-pip
                      RUN pip3 install bluish==0.8.0 --break-system-packages
                  output_file: {filename}
            - uses: docker/build
              with:
                  dockerfile: {filename}
                  context: .
                  tags:
                      - "bluish-test-alpine:0.8.0"
            - run: |
                  echo "id=$(docker image ls -f reference=bluish-test-alpine:0.8.0 -q)" >> "$BLUISH_OUTPUT"
              set:
                  workflow.var.docker-image-id: ${{{{ outputs.id }}}}
            - run: |
                  docker image rm $(docker image ls -f reference=bluish-test-alpine:0.8.0 -q)
""")
    _ = wf.dispatch()

    assert wf.get_value("docker-image-id")


def test_docker_build_with_matrix(temp_file: FileIO) -> None:
    filename = str(temp_file.name)

    wf = create_workflow(None, f"""
jobs:
    create-docker:
        matrix:
            os: [alpine, ubuntu]

        steps:
            - name: "Build ${{{{ matrix.os }}}} Dockerfile"
              uses: core/expand-template
              with:
                  input: |
                      FROM ${{{{ matrix.os }}}}:latest
                      RUN echo "Building for ${{{{ matrix.os }}}}"
                  output_file: {filename}
            - uses: docker/build
              with:
                  dockerfile: {filename}
                  context: .
                  tags:
                      - "bluish-test-${{{{ matrix.os }}}}:test"
            - run: |
                  echo "id=$(docker image ls -f reference=bluish-test-${{{{ matrix.os }}}}:test -q)" >> "$BLUISH_OUTPUT"
              set:
                  workflow.var.docker-image-${{{{ matrix.os }}}}-id: ${{{{ outputs.id }}}}
            - run: |
                  docker image rm $(docker image ls -f reference=bluish-test-${{{{ matrix.os }}}}:test -q)
""")
    _ = wf.dispatch()

    assert wf.get_value("var.docker-image-alpine-id")
    assert wf.get_value("var.docker-image-ubuntu-id")
    assert wf.get_value("var.docker-image-alpine-id") != wf.get_value("var.docker-image-ubuntu-id")
