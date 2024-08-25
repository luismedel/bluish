
import yaml
from bluish.core import Connection, PipeContext, RequiredParamError


def get_pipe(yaml_definition: str) -> PipeContext:
    conn = Connection()
    conn.echo_commands = False
    conn.echo_output = False
    definition = yaml.safe_load(yaml_definition)
    return PipeContext(Connection(), definition)


def test_generic_run() -> None:
    pipe = get_pipe("""
jobs:
  hello:
    - name: "Hello, World!"
      steps:
        - run: echo 'Hello, World!'
""")
    pipe.dispatch()
    assert pipe.vars["jobs.hello.output"] == "Hello, World!"


def test_mandatory_proerties() -> None:
    pipe = get_pipe("""
jobs:
  mandatory:
    - name: "Hello, World!"
      steps:
        - name: 'This step lacks a run property'
""")
    try:
        pipe.dispatch()
        assert False
    except RequiredParamError:
        assert True


def test_cwd() -> None:
    pipe = get_pipe("""
working_dir: /tmp

jobs:
  cwd:
    - steps:
        - run: pwd
""")
    pipe.dispatch()
    assert pipe.vars["jobs.cwd.output"] == "/tmp"


def test_expansion() -> None:
    pipe = get_pipe("""

vars:
  - HELLO: "Hello"
  - WORLD: "World!"
  - SMILEY: ":-)"

jobs:
  expansion:
    - name: Test expansion
      steps:
        - run: echo '${{ pipe.HELLO }} ${{ WORLD }} ${{ SMILEY }}'
""")
    pipe.dispatch()
    assert pipe.vars["jobs.expansion.output"] == "Hello World! :-)"


def test_variable_overriding() -> None:
    pipe = get_pipe("""
vars:
  - HELLO: "Hello"
  - WORLD: "World!"
  - SMILEY: ":-("

jobs:
  override:
    - name: Test expansion
      steps:
        - run: echo '${{ pipe.HELLO }} ${{ WORLD }} ${{ SMILEY }}'
      vars:
        - SMILEY: ":-DDDD"
""")
    pipe.dispatch()
    assert pipe.vars["jobs.override.output"] == "Hello World! :-DDDD"
