
import tempfile

import pytest
import yaml
from bluish.core import (
    Connection,
    PipeContext,
    RequiredAttributeError,
    RequiredInputError,
    init_commands,
)


@pytest.fixture(scope="session", autouse=True)
def initialize_commands():
    init_commands()


def create_pipe(yaml_definition: str) -> PipeContext:
    definition = yaml.safe_load(yaml_definition)
    return PipeContext(definition, Connection())


def test_multiple_jobs() -> None:
    pipe = create_pipe("""
jobs:
    job1:
        name: "Job 1"
        steps:
            - run: echo 'This is Job 1'
    job2:
        name: "Job 2"
        steps:
            - run: echo 'This is Job 2, step 1'
            - run: echo 'This is Job 2, step 2'
""")
    pipe.dispatch()
    assert pipe.jobs["job1"].output == "This is Job 1"
    assert pipe.jobs["job2"].output == "This is Job 2, step 2"


def test_working_directory() -> None:
    pipe = create_pipe("""
env:
    WORKING_DIR: /tmp

jobs:
    working_directory:
        name: "Working Directory"
        steps:
            - run: pwd
""")
    pipe.dispatch()
    assert pipe.jobs["working_directory"].output == "/tmp"


def test_generic_run() -> None:
    pipe = create_pipe("""
jobs:
    hello:
        name: "Hello, World!"
        steps:
            - run: echo 'Hello, World!'
""")
    pipe.dispatch()
    assert pipe.jobs["hello"].output == "Hello, World!"


def test_mandatory_attributes() -> None:
    pipe = create_pipe("""
jobs:
    mandatory_attributes:
        steps:
            - name: 'This step lacks a run property'
""")
    try:
        pipe.dispatch()
        assert False
    except RequiredAttributeError:
        assert True


def test_mandatory_inputs() -> None:
    pipe = create_pipe("""
env:
    WORLD: "World!"

jobs:
    mandatory_inputs:
        steps:
            - uses: expand-template
              with:
                  - input: "Hello, ${{{{ pipe.WORLD }}}}"
""")
    try:
        pipe.dispatch()
        assert False
    except RequiredInputError:
        assert True


def test_cwd() -> None:
    pipe = create_pipe("""
env:
    WORKING_DIR: /tmp

jobs:
    cwd:
        steps:
            - run: pwd
""")
    pipe.dispatch()
    assert pipe.jobs["cwd"].output == "/tmp"


def test_expansion() -> None:
    pipe = create_pipe("""
env:
    HELLO: "Hello"
    WORLD: "World!"
    SMILEY: ":-)"

jobs:
    expansion:
        name: Test expansion
        steps:
            - run: echo '${{ env.HELLO }} ${{ WORLD }} ${{ SMILEY }}'
""")
    pipe.dispatch()
    assert pipe.jobs["expansion"].output == "Hello World! :-)"


def test_values() -> None:
    pipe = create_pipe("""
env:
    VALUE: 1

jobs:
    values:
        name: Test values
        steps:
            - run: echo 'VALUE == ${{ env.VALUE }}'
""")
    pipe.dispatch()
    assert pipe.get_value("VALUE") == "1"
    assert pipe.get_value("env.VALUE") == "1"
    assert pipe.jobs["values"].output == "VALUE == 1"
    assert pipe.get_value("jobs.values.output") == "VALUE == 1"


def test_env_overriding() -> None:
    pipe = create_pipe("""
env:
    HELLO: "Hello"
    WORLD: "World!"
    SMILEY: ":-("

jobs:
    override_test:
        name: Test expansion
        steps:
            - run: echo '${{ env.HELLO }} ${{ WORLD }} ${{ SMILEY }}'
        env:
            SMILEY: ":-DDDD"
""")
    pipe.dispatch()
    assert pipe.jobs["override_test"].output == "Hello World! :-DDDD"


def test_expand_template() -> None:
    with tempfile.NamedTemporaryFile() as temp_file:
        pipe = create_pipe(f"""
env:
    WORLD: "World!"

jobs:
    expand_template:
        steps:
            - uses: expand-template
              with:
                  hide_output: true
                  input: "Hello, ${{{{ WORLD }}}}"
                  output_file: {temp_file.name}
    """)
        pipe.dispatch()
        assert pipe.jobs["expand_template"].output == "Hello, World!"
        assert pipe.conn.run(f"cat {temp_file.name}", echo_output=False).stdout.strip() == "Hello, World!"
