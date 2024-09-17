
import logging
import tempfile
from test.utils import create_workflow

import pytest
from bluish.action import RequiredAttributeError, RequiredInputError
from bluish.context import CircularDependencyError
from bluish.core import (
    ExecutionStatus,
    init_commands,
)
from bluish.process import run


@pytest.fixture(scope="session", autouse=True)
def initialize_commands():
    init_commands()


def test_multiple_jobs() -> None:
    wf = create_workflow("""
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
    _ = wf.dispatch()

    assert wf.jobs["job1"].result.stdout == "This is Job 1"
    assert wf.jobs["job2"].result.stdout == "This is Job 2, step 2"


def test_multiple_jobs_failed() -> None:
    wf = create_workflow("""
jobs:
    job1:
        name: "Job 1"
        steps:
            - run: |
                  echo 'This is Job 1'
                  false
    job2:
        name: "Job 2"
        steps:
            - run: echo 'This is Job 2, step 1'
""")
    _ = wf.dispatch()

    assert wf.jobs["job1"].result.stdout == "This is Job 1"
    assert wf.jobs["job2"].result.stdout == ""


def test_matrix() -> None:
    with tempfile.NamedTemporaryFile() as temp_file:
        wf = create_workflow(f"""
jobs:
    test_job:
        name: "Job 1"
        matrix:
            os: [ubuntu, macos]
            version: ["18.04", "20.04"]
            color: [red, blue]
        steps:
            - run: |
                echo ${{{{ matrix.os }}}}-${{{{ matrix.version }}}}-${{{{ matrix.color }}}} >> {temp_file.name}
""")
        _ = wf.dispatch()
        output = temp_file.read().decode()
        assert output == """ubuntu-18.04-red
ubuntu-18.04-blue
ubuntu-20.04-red
ubuntu-20.04-blue
macos-18.04-red
macos-18.04-blue
macos-20.04-red
macos-20.04-blue
"""


def test_depends_on() -> None:
    wf = create_workflow("""
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
    _ = wf.dispatch_job(wf.jobs["job2"], False)
    assert wf.jobs["job1"].result.stdout == "This is Job 1"
    assert wf.jobs["job2"].result.stdout == "This is Job 2, step 2"


def test_depends_on_circular() -> None:
    wf = create_workflow("""
jobs:
    job1:
        name: "Job 1"
        depends_on:
            - job2
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
    try:
        _ = wf.dispatch_job(wf.jobs["job2"], False)
        raise AssertionError("Circular dependency not detected")
    except CircularDependencyError:
        pass


def test_depends_on_failed() -> None:
    wf = create_workflow("""
jobs:
    job1:
        name: "Job 1"
        steps:
            - run: |
                  echo 'This is Job 1'
                  false
    job2:
        name: "Job 2"
        depends_on:
            - job1
        steps:
            - run: echo 'This is Job 2, step 1'
            - run: echo 'This is Job 2, step 2'
""")
    _ = wf.dispatch_job(wf.jobs["job2"], False)
    assert wf.jobs["job1"].status == ExecutionStatus.FINISHED
    assert wf.jobs["job1"].result.failed
    assert wf.jobs["job2"].status == ExecutionStatus.PENDING
    assert wf.jobs["job2"].result.stdout == ""


def test_depends_on_ignored() -> None:
    wf = create_workflow("""
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
    _ = wf.dispatch_job(wf.jobs["job2"], True)
    assert wf.jobs["job1"].result.stdout == ""
    assert wf.jobs["job2"].result.stdout == "This is Job 2, step 2"


def test_conditions() -> None:
    wf = create_workflow("""
jobs:
    # check == false at the job level
    job1:
        name: "Job 1"
        if: ${{ false }}
        steps:
            - run: echo 'This will not be printed'

    # check == true at the job level
    job2:
        name: "Job 2"
        if: ${{ true }}
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
            - if: ${{ true }}
              shell: python
              run: |
                print("This is Job 4")

    # check == false at the step level
    job5:
        name: "Job 5"
        steps:
            - if: ${{ false }}
              shell: python
              run: |
                print("This will not be printed")
""")
    _ = wf.dispatch()

    assert wf.jobs["job1"].result.stdout == ""
    assert wf.jobs["job2"].result.stdout == "This is Job 2"
    assert wf.jobs["job3"].result.stdout == "This is Job 3"
    assert wf.jobs["job4"].result.stdout == "This is Job 4"
    assert wf.jobs["job5"].result.stdout == ""


def test_working_directory() -> None:
    wf = create_workflow("""

working_directory: /tmp

jobs:
    test_job:
        name: "Working Directory"
        steps:
            - run: pwd
""")
    _ = wf.dispatch()

    assert wf.jobs["test_job"].result.stdout == "/tmp"


def test_working_directory_override() -> None:
    wf = create_workflow("""

working_directory: /tmp

jobs:
    test_job:
        name: "Working Directory"
        working_directory: /home
        steps:
            - run: pwd
""")
    _ = wf.dispatch()

    assert wf.jobs["test_job"].result.stdout == "/home"


def test_default_run() -> None:
    wf = create_workflow("""
jobs:
    hello_run:
        name: "Hello, World!"
        steps:
            - run: echo 'Hello, World!'
""")
    _ = wf.dispatch()

    assert wf.jobs["hello_run"].result.stdout == "Hello, World!"


def test_shell_run_bash() -> None:
    wf = create_workflow("""
jobs:
    hello_sh:
        name: "Hello, World!"
        shell: bash
        steps:
            - run: echo 'Hello, World!'
""")
    _ = wf.dispatch()

    assert wf.jobs["hello_sh"].result.stdout == "Hello, World!"


def test_shell_run_python() -> None:
    wf = create_workflow("""
jobs:
    hello_python:
        name: "Hello, World!"
        steps:
            - shell: python
              run: |
                v = "World"
                print(f'Hello, {v}!')
""")
    _ = wf.dispatch()

    assert wf.jobs["hello_python"].result.stdout == "Hello, World!"


def test_shell_override() -> None:
    wf = create_workflow("""
shell: sh

jobs:
    hello_python:
        name: "Hello, World!"
        shell: node  # Overridde at job level

        steps:
            - shell: python  # Effective value
              run: |
                v = "World"
                print(f'Hello, {v}!')
""")
    _ = wf.dispatch()

    assert wf.jobs["hello_python"].result.stdout == "Hello, World!"


def test_mandatory_attributes() -> None:
    wf = create_workflow("""
jobs:
    mandatory_attributes:
        steps:
            - name: 'This step lacks a run property'
""")
    try:
        _ = wf.dispatch()
        raise AssertionError("Mandatory attribute not detected")
    except RequiredAttributeError:
        pass


def test_mandatory_inputs() -> None:
    wf = create_workflow("""
var:
    WORLD: "World!"

jobs:
    mandatory_inputs:
        steps:
            - uses: core/expand-template
              with:
                input: "Hello, ${{{{ var.WORLD }}}}"
""")
    try:
        _ = wf.dispatch()
        raise AssertionError("Mandatory input not detected")
    except RequiredInputError:
        pass


def test_cwd() -> None:
    wf = create_workflow("""
working_directory: /tmp

jobs:
    cwd:
        steps:
            - run: pwd
""")
    _ = wf.dispatch()

    assert wf.jobs["cwd"].result.stdout == "/tmp"


def test_expansion() -> None:
    wf = create_workflow("""
var:
    HELLO: "Hello"
    WORLD: "World!"
    SMILEY: ":-)"

jobs:
    expansion:
        name: Test expansion
        steps:
            - run: echo '${{ var.HELLO }} ${{ var.WORLD }} ${{ var.SMILEY }}'
""")
    _ = wf.dispatch()

    assert wf.jobs["expansion"].result.stdout == "Hello World! :-)"


def test_expansion_with_ambiguity() -> None:
    wf = create_workflow("""
var:
    test_result:
    result: "No"

jobs:
    expansion:
        name: Test expansion
        steps:
            - run: echo 'Yes!'
              set:
                workflow.var.test_result: ${{ result }}
""")
    try:
        _ = wf.dispatch()
        raise AssertionError("Ambiguity not detected")
    except ValueError as ex:
        assert str(ex) == "Ambiguous value reference: result"


def test_expansion_with_no_ambiguity() -> None:
    wf = create_workflow("""
var:
    test_result:
    result: "No"

jobs:
    expansion:
        name: Test expansion
        steps:
            - run: echo 'Yes!'
              set:
                workflow.var.test_result: ${{ .result }}
""")
    _ = wf.dispatch()
    assert wf.get_value("test_result") == "Yes!"
    assert wf.get_value("var.test_result") == "Yes!"


def test_working_dir_expansion() -> None:
    wf = create_workflow("""
var:
    PATH: "/tmp"

jobs:
    test_job:
        name: Test expansion
        var:
            DIRECTORY: ${{ var.PATH }}
        steps:
            - run: echo '${{ var.DIRECTORY }}'
""")
    _ = wf.dispatch()

    assert wf.jobs["test_job"].result.stdout == "/tmp"


def test_values() -> None:
    wf = create_workflow("""
var:
    VALUE: 1

jobs:
    test_job:
        name: Test values
        steps:
            - id: step-1
              run: echo 'VALUE == ${{ var.VALUE }}'
              set:
                  jobs.test_job.var.VALUE: 99  # Will be overridden by the next line
                  job.var.VALUE: 2
""")
    _ = wf.dispatch()

    assert wf.get_value("var.VALUE") == 1
    assert wf.get_value("workflow.var.VALUE") == 1
    assert wf.get_value("workflow.jobs.test_job.var.VALUE") == 2
    assert wf.jobs["test_job"].get_value("var.VALUE") == 2
    assert wf.jobs["test_job"].steps["step-1"].get_value("var.VALUE") == 2
    assert wf.jobs["test_job"].steps["step-1"].get_value("job.var.VALUE") == 2
    assert wf.jobs["test_job"].get_value("var.VALUE") == 2
    assert wf.jobs["test_job"].get_value("job.var.VALUE") == 2


def test_secrets_are_redacted_in_log(caplog) -> None:
    caplog.set_level(logging.DEBUG)
    
    wf = create_workflow("""
secrets:
    my_secret: "hello"

var:
    my_var: "world"

jobs:
    test_job:
        name: Test values
        steps:
            - run: |
                  echo "secret is = ${{ secrets.my_secret }}"
                  echo "var is = ${{ var.my_var }}"
""")
    _ = wf.dispatch()

    assert wf.get_value("jobs.test_job.steps.step_1.result") == "secret is = hello\nvar is = world"
    assert "secret is = ***" in caplog.text
    assert "var is = world" in caplog.text


def test_set() -> None:
    wf = create_workflow("""
var:
    VALUE: 42

jobs:
    test_job:
        name: Test set
        steps:
            - id: step-1
              run: |
                echo 'VALUE == ${{ var.VALUE }}'
              set:
                  workflow.var.VALUE: 2
                  job.var.COOL_YEAR: 1980
                  jobs.test_job.var.VOUTPUT: ${{ .result }}
""")
    _ = wf.dispatch()

    assert wf.get_value("var.VALUE") == 2
    assert wf.get_value("jobs.test_job.var.COOL_YEAR") == 1980
    assert wf.jobs["test_job"].steps["step-1"].result.stdout == "VALUE == 42"
    assert wf.jobs["test_job"].var["VOUTPUT"] == "VALUE == 42"


def test_env_overriding() -> None:
    wf = create_workflow("""
var:
    HELLO: "Hello"
    WORLD: "World!"
    SMILEY: ":-("

jobs:
    test_job:
        var:
            SMILEY: "xD"
        name: Test expansion
        steps:
            - id: step-1
              run: echo '${{ var.HELLO }} ${{ var.WORLD }} ${{ var.SMILEY }}'
              var:
                  SMILEY: ":-DDDD"
            - id: step-2
              run: echo '${{ var.HELLO }} ${{ var.WORLD }} ${{ var.SMILEY }}'

    test_job_2:
        name: Test expansion
        steps:
            - id: step-1
              run: echo '${{ var.HELLO }} ${{ var.WORLD }} ${{ var.SMILEY }}'
""")
    _ = wf.dispatch()

    assert wf.jobs["test_job"].steps["step-1"].result.stdout == "Hello World! :-DDDD"
    assert wf.jobs["test_job"].steps["step-2"].result.stdout == "Hello World! xD"
    assert wf.jobs["test_job_2"].steps["step-1"].result.stdout == "Hello World! :-("


def test_expand_template() -> None:
    with tempfile.NamedTemporaryFile() as temp_file:
        wf = create_workflow(f"""
var:
    hero: "Don Quijote"

jobs:
    expand_template:
        steps:
            - uses: core/expand-template
              with:
                  hide_output: true
                  input: |
                      En un lugar de la Mancha, de cuyo nombre no quiero acordarme, no ha mucho
                      tiempo que vivía un hidalgo de los de lanza en astillero, adarga antigua,
                      rocín flaco y galgo corredor. Una olla de algo más vaca que carnero,
                      salpicón las más noches, duelos y quebrantos los sábados, lantejas los
                      viernes, algún palomino de añadidura los domingos, consumían las tres
                      partes de su hacienda. El resto della concluían sayo de velarte, calzas de
                      velludo para las fiestas, con sus pantuflos de lo mesmo, y los días de
                      entresemana se honraba con su vellorí de lo más fino. Tenía en su casa una
                      ama que pasaba de los cuarenta, y una sobrina que no llegaba a los veinte,
                      y un mozo de campo y plaza, que así ensillaba el rocín como tomaba la
                      podadera. Frisaba la edad de nuestro hidalgo con los cincuenta años; era de
                      complexión recia, seco de carnes, enjuto de rostro, gran madrugador y amigo
                      de la caza. Quieren decir que tenía el sobrenombre de Quijada, o Quesada,
                      que en esto hay alguna diferencia en los autores que deste caso escriben;
                      aunque, por conjeturas verosímiles, se deja entender que se llamaba
                      Quejana. Pero esto importa poco a nuestro cuento; basta que en la narración
                      dél no se salga un punto de la verdad.
                      Hello, ${{{{ hero }}}}!
                  output_file: {temp_file.name}
    """)
        _ = wf.dispatch()

        assert wf.jobs["expand_template"].result.stdout.endswith("Hello, Don Quijote!\n")
        assert run(f"tail -n1 {temp_file.name}").stdout == "Hello, Don Quijote!"


def test_capture() -> None:
    wf = create_workflow("""
jobs:
    test_job:
        steps:
            - id: step_1
              run: |
                  echo "OUT=value 1" >> "$BLUISH_OUTPUT"
            - id: step_2
              run: |
                  echo "OUT=value 2" >> "$BLUISH_OUTPUT"
              set:
                  workflow.var.OUT: ${{ outputs.OUT }}
""")
    _ = wf.dispatch()

    assert wf.get_value("jobs.test_job.steps.step_1.outputs.OUT") == "value 1"
    assert wf.get_value("jobs.test_job.steps.step_2.outputs.OUT") == "value 2"
    assert wf.get_value("var.OUT") == "value 2"


def test_pass_env() -> None:
    wf = create_workflow("""
env:
    WORLD: "World!"

jobs:
    pass_env:
        steps:
            - run: |
                  echo "Hello, $WORLD"
""")
    _ = wf.dispatch()

    assert wf.jobs["pass_env"].result.stdout == "Hello, World!"


@pytest.mark.docker
def test_docker_pass_env() -> None:
    wf = create_workflow("""
env:
    WORLD: "World!"

jobs:
    pass_env:
        runs_on: docker://alpine:latest
        steps:
            - run: |
                  echo "Hello, $WORLD"
""")
    _ = wf.dispatch()

    assert wf.jobs["pass_env"].result.stdout == "Hello, World!"


@pytest.mark.docker
def test_docker_run() -> None:
    wf = create_workflow("""
jobs:
    docker_run:
        runs_on: docker://alpine:latest
        steps:
            - run: |
                  echo 'Hello, World!'
    """)
    _ = wf.dispatch()

    assert wf.jobs["docker_run"].result.stdout == "Hello, World!"


@pytest.mark.docker
def test_docker_file_upload() -> None:
    with tempfile.NamedTemporaryFile() as temp_file:
        temp_file.write(b"Hello, World!")
        temp_file.flush()
        wf = create_workflow(f"""
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
        _ = wf.dispatch()
    assert wf.jobs["file_upload"].result.stdout == "Hello, World!"


@pytest.mark.docker
def test_docker_file_download() -> None:
    with tempfile.NamedTemporaryFile() as temp_file:
        temp_file.write(b"Hello, World!")
        temp_file.flush()

        wf = create_workflow(f"""
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
        _ = wf.dispatch()

        with open(temp_file.name, "r") as f:
            assert f.read().strip() == "Hello, World!"


@pytest.mark.docker
def test_docker_file_download_failed() -> None:
    with tempfile.NamedTemporaryFile() as temp_file:
        temp_file.write(b"Hello, World!")
        temp_file.flush()

        wf = create_workflow(f"""
jobs:
    test_job:
        runs_on: docker://alpine:latest
        steps:
            - uses: core/download-file
              with:
                  source_file: /tmp/hello.txt
                  destination_file: {temp_file.name}
            - run: |
                  echo 'Hello, World!'
    """)
        _ = wf.dispatch()

        assert wf.jobs["test_job"].failed
        assert wf.jobs["test_job"].steps["step_1"].failed
        assert wf.get_value("jobs.test_job.steps.step_2.result") == ""
