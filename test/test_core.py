
import tempfile

import pytest
import yaml
from bluish.core import Connection, PipeContext, RequiredParamError, init_commands


@pytest.fixture(scope="session", autouse=True)
def initialize_commands():
    init_commands()


def create_pipe(yaml_definition: str) -> PipeContext:
    conn = Connection()
    conn.echo_commands = False
    conn.echo_output = False
    definition = yaml.safe_load(yaml_definition)
    return PipeContext(Connection(), definition)


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
    assert pipe.vars["jobs.job1.output"] == "This is Job 1"
    assert pipe.vars["jobs.job2.output"] == "This is Job 2, step 2"


def test_working_directory() -> None:
    pipe = create_pipe("""
working_dir: /tmp

jobs:
    working_directory:
        name: "Working Directory"
        steps:
            - run: pwd
""")
    pipe.dispatch()
    assert pipe.vars["jobs.working_directory.output"] == "/tmp"


def test_generic_run() -> None:
    pipe = create_pipe("""
jobs:
    hello:
        name: "Hello, World!"
        steps:
            - run: echo 'Hello, World!'
""")
    pipe.dispatch()
    assert pipe.vars["jobs.hello.output"] == "Hello, World!"


def test_mandatory_proerties() -> None:
    pipe = create_pipe("""
jobs:
    mandatory:
        name: "Hello, World!"
        steps:
            - name: 'This step lacks a run property'
""")
    try:
        pipe.dispatch()
        assert False
    except RequiredParamError:
        assert True


def test_cwd() -> None:
    pipe = create_pipe("""
working_dir: /tmp

jobs:
    cwd:
        steps:
            - run: pwd
""")
    pipe.dispatch()
    assert pipe.vars["jobs.cwd.output"] == "/tmp"


def test_expansion() -> None:
    pipe = create_pipe("""
var:
    - HELLO: "Hello"
    - WORLD: "World!"
    - SMILEY: ":-)"

jobs:
    expansion:
        name: Test expansion
        steps:
            - run: echo '${{ pipe.HELLO }} ${{ WORLD }} ${{ SMILEY }}'
""")
    pipe.dispatch()
    assert pipe.vars["jobs.expansion.output"] == "Hello World! :-)"


def test_variable_overriding() -> None:
    pipe = create_pipe("""
var:
    - HELLO: "Hello"
    - WORLD: "World!"
    - SMILEY: ":-("

jobs:
    override:
        name: Test expansion
        steps:
            - run: echo '${{ pipe.HELLO }} ${{ WORLD }} ${{ SMILEY }}'
        var:
            - SMILEY: ":-DDDD"
""")
    pipe.dispatch()
    assert pipe.vars["jobs.override.output"] == "Hello World! :-DDDD"


def test_expand_template() -> None:
    with tempfile.NamedTemporaryFile() as temp_file:
        print(temp_file)
        pipe = create_pipe(f"""
var:
    - WORLD: "World!"

jobs:
    expand_template:
        steps:
            - uses: expand-template
              with:
                  input: "Hello, ${{{{ pipe.WORLD }}}}"
                  output_file: {temp_file.name}
    """)
        pipe.dispatch()
        assert pipe.vars["jobs.expand_template.output"] == "Hello, World!"
        assert pipe.conn.run(f"cat {temp_file.name}").stdout.strip() == "Hello, World!"
