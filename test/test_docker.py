
import tempfile
from test.utils import create_workflow

import pytest
from bluish.core import init_commands


@pytest.fixture(scope="session", autouse=True)
def initialize_commands():
    init_commands()


#@pytest.mark.docker
def test_docker_build() -> None:
    with tempfile.TemporaryFile() as temp_file:
        wf = create_workflow(f"""
jobs:
    create-docker:
        steps:
            - name: "Build Alpine Dockerfile"
              uses: core/expand-template
              with:
                  input: |
                      FROM alpine:latest
                      RUN apk add --no-cache python3 py-pip
                      RUN pip3 install bluish==0.0.30 --break-system-packages
                  output_file: {temp_file.name}
            - uses: docker/build
              with:
                  dockerfile: {temp_file.name}
                  context: .
                  tags:
                      - "bluish-test-alpine:0.0.30"
            - run: |
                  echo "id=$(docker image ls -f reference=bluish-test-alpine:0.0.30 -q)" >> "$BLUISH_OUTPUT"
              set:
                  workflow.var.docker-image-id: ${{{{ outputs.id }}}}
            - run: |
                  docker image rm $(docker image ls -f reference=bluish-test-alpine:0.0.30 -q)
""")
        _ = wf.dispatch()
        assert wf.get_value("docker-image-id")


def test_docker_build_with_matrix() -> None:
    with tempfile.TemporaryFile() as temp_file:
        wf = create_workflow(f"""
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
                  output_file: {temp_file.name}
            - uses: docker/build
              with:
                  dockerfile: {temp_file.name}
                  context: .
                  tags:
                      - "bluish-test-${{{{ matrix.os }}}}:0.0.30"
            - run: |
                  echo "id=$(docker image ls -f reference=bluish-test-${{{{ matrix.os }}}}:0.0.30 -q)" >> "$BLUISH_OUTPUT"
              set:
                  workflow.var.docker-image-${{{{ matrix.os }}}}-id: ${{{{ outputs.id }}}}
            - run: |
                  docker image rm $(docker image ls -f reference=bluish-test-${{{{ matrix.os }}}}:0.0.30 -q)
""")
        _ = wf.dispatch()
        assert wf.get_value("docker-image-alpine-id")
        assert wf.get_value("docker-image-ubuntu-id")
        assert wf.get_value("docker-image-alpine-id") != wf.get_value("docker-image-ubuntu-id")
