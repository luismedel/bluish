
import tempfile
from test.utils import create_pipe

import pytest
from bluish.app import dispatch_job
from bluish.core import (
    RequiredAttributeError,
    RequiredInputError,
    init_commands,
)
from bluish.process import run


@pytest.fixture(scope="session", autouse=True)
def initialize_commands():
    init_commands()


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


def test_depends_on() -> None:
    pipe = create_pipe("""
jobs:
    job1:
        name: "Job 1"
        steps:
            - run: echo 'This is Job 1'
    job2:
        name: "Job 2"
        depends_on:
            - job1
        steps:
            - run: echo 'This is Job 2, step 1'
            - run: echo 'This is Job 2, step 2'
""")
    dispatch_job(pipe, "job2", False)
    assert pipe.jobs["job1"].output == "This is Job 1"
    assert pipe.jobs["job2"].output == "This is Job 2, step 2"


def test_depends_on_ignored() -> None:
    pipe = create_pipe("""
jobs:
    job1:
        name: "Job 1"
        steps:
            - run: echo 'This is Job 1'
    job2:
        name: "Job 2"
        depends_on:
            - job1
        steps:
            - run: echo 'This is Job 2, step 1'
            - run: echo 'This is Job 2, step 2'
""")
    dispatch_job(pipe, "job2", True)
    assert pipe.jobs["job1"].output == ""
    assert pipe.jobs["job2"].output == "This is Job 2, step 2"


def test_conditions() -> None:
    pipe = create_pipe("""
jobs:
    # check == false at the job level
    job1:
        name: "Job 1"
        if: "false && echo 1"
        steps:
            - run: echo 'This will not be printed'

    # check == true at the job level
    job2:
        name: "Job 2"
        if: "true && echo 1"
        steps:
            - run: echo 'This is Job 2'

    # no check (default == true)
    job3:
        name: "Job 3"
        steps:
            - run: echo 'This is Job 3'

    # check == true at the step level
    job4:
        name: "Job 4"
        steps:
            - if: "true && echo 1"
              shell: python
              run: |
                print("This is Job 4")

    # check == false at the step level
    job5:
        name: "Job 5"
        steps:
            - if: "false && echo 1"
              shell: python
              run: |
                print("This will not be printed")
""")
    pipe.dispatch()
    assert pipe.jobs["job1"].output == ""
    assert pipe.jobs["job2"].output == "This is Job 2"
    assert pipe.jobs["job3"].output == "This is Job 3"
    assert pipe.jobs["job4"].output == "This is Job 4"
    assert pipe.jobs["job5"].output == ""


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


def test_default_run() -> None:
    pipe = create_pipe("""
jobs:
    hello_run:
        name: "Hello, World!"
        steps:
            - run: echo 'Hello, World!'
""")
    pipe.dispatch()
    assert pipe.jobs["hello_run"].output == "Hello, World!"


def test_shell_run_bash() -> None:
    pipe = create_pipe("""
jobs:
    hello_sh:
        name: "Hello, World!"
        shell: bash
        steps:
            - run: echo 'Hello, World!'
""")
    pipe.dispatch()
    assert pipe.jobs["hello_sh"].output == "Hello, World!"


def test_shell_run_python() -> None:
    pipe = create_pipe("""
jobs:
    hello_python:
        name: "Hello, World!"
        steps:
            - shell: python
              run: |
                v = "World"
                print(f'Hello, {v}!')
""")
    pipe.dispatch()
    assert pipe.jobs["hello_python"].output == "Hello, World!"


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
            - uses: core/expand-template
              with:
                input: "Hello, ${{{{ env.WORLD }}}}"
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
            - id: step-1
              run: echo 'VALUE == ${{ env.VALUE }}'
              set:
                jobs.values.var.VALUE: 99  # Will be overridden by the next line
                job.var.VALUE: 1
""")
    pipe.dispatch()
    assert pipe.get_value("VALUE") == "1"
    assert pipe.get_value("env.VALUE") == "1"
    assert pipe.get_value("var.VALUE") is None

    assert pipe.jobs["values"].output == "VALUE == 1"
    assert pipe.get_value("jobs.values.output") == "VALUE == 1"

    assert pipe.get_value("jobs.values.var.VALUE") == "1"
    assert pipe.jobs["values"].get_value("var.VALUE") == "1"
    assert pipe.jobs["values"].var["VALUE"] == "1"
    assert pipe.jobs["values"].steps["step-1"].get_value("VALUE") == "1"
    assert pipe.jobs["values"].steps["step-1"].get_value("job.var.VALUE") == "1"


def test_set() -> None:
    pipe = create_pipe("""
env:
    VALUE: 1

jobs:
    set:
        name: Test set
        steps:
            - id: echo-step
              run: |
                echo 'VALUE == ${{ env.VALUE }}'
              env:
                  VALUE: 2
              set:
                  job.var.TEMP: 42
                  var.STEP_SCOPE: 1
                  pipe.var.PIPE_SCOPE: 1
                  job.var.TEST_OUTPUT: ${{ output }}
""")
    pipe.dispatch()
    assert pipe.jobs["set"].steps["echo-step"].output == "VALUE == 2"
    assert pipe.jobs["set"].var["TEST_OUTPUT"] == "VALUE == 2"
    assert pipe.get_value("VALUE") == "1"
    assert pipe.get_value("jobs.set.var.TEMP") == "42"
    assert pipe.get_value("STEP_SCOPE") is None
    assert pipe.get_value("PIPE_SCOPE") == "1"
    assert pipe.get_value("PIPE_SCOPE") == "1"


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
            - uses: core/expand-template
              with:
                  hide_output: true
                  input: "Hello, ${{{{ WORLD }}}}"
                  output_file: {temp_file.name}
    """)
        pipe.dispatch()
        assert pipe.jobs["expand_template"].output == "Hello, World!"
        assert run(f"cat {temp_file.name}").stdout.strip() == "Hello, World!"


def test_pass_env() -> None:
    pipe = create_pipe("""
env:
    WORLD: "World!"

jobs:
    pass_env:
        steps:
            - run: |
                  echo "Hello, $WORLD"
""")
    pipe.dispatch()
    assert pipe.jobs["pass_env"].output == "Hello, World!"


def test_pass_env_to_docker() -> None:
    pipe = create_pipe("""
env:
    WORLD: "World!"

jobs:
    pass_env:
        runs_on: docker://alpine:latest
        steps:
            - run: |
                  echo "Hello, $WORLD"
""")
    pipe.dispatch()
    assert pipe.jobs["pass_env"].output == "Hello, World!"


def test_docker_run() -> None:
    pipe = create_pipe("""
jobs:
    docker_run:
        runs_on: docker://alpine:latest
        steps:
            - run: |
                  echo 'Hello, World!'
    """)
    pipe.dispatch()
    assert pipe.jobs["docker_run"].output == "Hello, World!"


def test_file_upload() -> None:
    with tempfile.NamedTemporaryFile() as temp_file:
        temp_file.write(b"Hello, World!")
        temp_file.flush()
        pipe = create_pipe(f"""
jobs:
    file_upload:
        runs_on: docker://alpine:latest
        steps:
            - uses: core/upload-file
              with:
                  source_file: {temp_file.name}
                  destination_file: /tmp/hello.txt
            - run: cat /tmp/hello.txt
    """)
        pipe.dispatch()
    assert pipe.jobs["file_upload"].output.strip() == "Hello, World!"


def test_file_download() -> None:
    with tempfile.NamedTemporaryFile() as temp_file:
        temp_file.write(b"Hello, World!")
        temp_file.flush()

        pipe = create_pipe(f"""
jobs:
    file_download:
        runs_on: docker://alpine:latest
        steps:
            - run: |
                  echo 'Hello, World!' > /tmp/hello.txt
            - uses: core/download-file
              with:
                  source_file: /tmp/hello.txt
                  destination_file: {temp_file.name}
    """)
        pipe.dispatch()

        with open(temp_file.name, "r") as f:
            assert f.read().strip() == "Hello, World!"
