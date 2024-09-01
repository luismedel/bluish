# Bluish

The CI/CD/automation tool I use for my personal projects.

Why use a rock-solid tool when you can code your own crappy Make alternative?

## Features

- YAML-based declarative approach (not that I love YAML, but...)
- Githubactions-esque philosphy, but way simpler. In fact, Bluish is nearer to Make than to GA.
- Simple as fuck. I only add new actions whenever I need them.

## Example

Here you have a basic CI pipeline for a Python-based project.

It consists of three jobs:

- `lint`: Detects linting errors
- `lint-fix`: Reformats code
- `test`: Runs the test suite

Observe we use the form `${{ PYTHON_VERSION }}` to expand the `PYTHON_VERSION` env variable.

Note that the similarity with other tools like Github Actions is very superficial.

```yaml
var:
  PYTHON_VERSION: "3.11"

jobs:
  lint:
    name: Runs ruff and mypy
    steps:
      - run: |
          ruff version
          ruff check src/ test/
          echo ""
          mypy --version
          mypy --ignore-missing-imports --python-version=${{ PYTHON_VERSION }} src/ test/

  lint-fix:
    name: Reformats the code using ruff
    depends_on:
      - lint
    steps:
      - run: |
          ruff version
          ruff check --select I --fix src/ test/
          ruff format src/
          echo ""

  test:
    name: Run tests
    steps:
      - run: |
          pytest
```

Having the previous config in `bluish.yaml` we can invoke any jobs this way:

```sh
$ bluish run lint-fix
```

Of with the shorthand command `blu`:

```sh
$ blu lint-fix
```

...which will run first `lint` (as stated in the `depends_on` attribute) and then `lint-fix`.

## How to use

Install:

```sh
$ pip install bluish
```

By default, Bluish expects in a file called `bluish.yaml` or `.bluish/bluish.yaml` inside the current directory.

You can list all available jobs with:

```sh
$ bluish list

List of available jobs:
ID               NAME
lint             Runs ruff and mypy
lint-fix         Reformats the code using ruff
test             Runs tests
```

Invoke any job with:

```sh
$ bluish run <job_id>
```

You can override the yaml file and pass an arbitrary file to Bluish using the `--file` option:

```sh
$ bluish --file file.yaml run test
```

It is very common to split your jobs into several files (for example to have separate CI and CD pipelines). To ease this, the shorthand command `blu` allows to run jobs using a more compact syntax.

```sh
$ blu <file>:<job>
```

Say you have your CI jobs defined in the file `bluish/ci.yaml` and there's a job called `test` to run your test suite. You can run it with:

```sh
$ blu ci:test
```

This is equivalent to:

```sh
$ bluish --file .bluish/ci.yaml run test
```

## Key concepts

Bluish operates with two elements: jobs and steps.

- A step is a simple command or action invocation. For example, copy a file, build a Docker image, restart a container and so on.
- A job is a list of steps to perform some task. For example, pass the CI or deploy a project.

At yaml level, they're organized this way:

```yaml
# yaml root
jobs:
  <job_id>:
    steps:
      - <step 1>
      - <step 2>
      - ...
      - <step N>
```

### Common attributes

Jobs and steps share some common attributes. Some of them are inheritable. This means that, if setted at the job level, they are shared among all its steps, unless overriden.

| Attribute | Type | Description |
|---|---|---|
| `if` | Expression | An expression to evaluate in order to decide if the job/step where it appears must be run. An exit code of `0` is trated as `true`. Anything else is `false`. The expression will be run on the default shell, which is `bash`. |
| `echo_commands` | boolean | Tells Bluish to echo the executed commands. Default is `true`. |
| `echo_output` | boolean | Tells Bluish to echo the actions output. Default is `true`. |
| `is_sensitive` | boolean | Indicates that the element is sensitive, so Bluish should not echo the commands nor the outputs. Disables both `echo_commands` and `echo_output`. The default is `false`. |

### Job attributes

| Attribute | Type | Description |
|---|---|---|
| `runs_on` | string | Where to run the commands. Valid values are `docker://<image>` to fire up a new container using `image` (the container will be removed on job finalization), `docker://<name or id>` to run the commands in an already-running container, `ssh://[user@]host` to connect run the commands in `host` via ssh, or leave it blank, to run the commands in the local host. |
| `if` | expression | An expression to evaluate in order to decide if the job must be run. An exit code of `0` is trated as `true`. Anything else is `false`. The expression will be run on the default shell, which is `bash`. |
| `echo_commands` | boolean | Tells Bluish to echo the executed commands. Default is `true`. |
| `echo_output` | boolean | Tells Bluish to echo the actions output. Default is `true`. |
| `is_sensitive` | boolean | Indicates that the element is sensitive, so Bluish should not echo the commands nor the outputs. Disables both `echo_commands` and `echo_output`. The default is `false`. |

### Step attributes

| Attribute | Type | Description |
|---|---|---|
| `if` | Expression | An expression to evaluate in order to decide if the step must be run. An exit code of `0` is trated as `true`. Anything else is `false`. The expression will be run on the default shell, which is `bash`. |
| `echo_commands` | boolean | Tells Bluish to echo the executed commands. Default is `true`. |
| `echo_output` | boolean | Tells Bluish to echo the actions output. Default is `true`. |
| `is_sensitive` | boolean | Indicates that the element is sensitive, so Bluish should not echo the commands nor the outputs. Disables both `echo_commands` and `echo_output`. The default is `false`. |
| `set` | dictionary | Indicates a list of bluish or environment variables to be set *after* this step ends executing. |

## Actions

As you probably imagine, you can use different actions to perform different tasks.

The list of available actions is pretty limited right now, as I'm only writing the ones I need when I find myself writing too much bash :-)

### Default action

If no `uses` attribute is set, Bluish uses the default action to run any command.

Inputs:

- `run` (required): command to run
- `shell`: interpreter to run the command on.Bluish provides a set of builtin shells:
  - "bash" (invokes `bash -euo pipefail`)
  - "sh" (invokes `sh -eu`)
  - "python": invokes `python3`
  
  ```yaml
  jobs:
    example-command:
      steps:
        - shell: python
          run: |
            a = 1;
            b = a + 2;
            print(b);
  ```

  Any other string will be treated as is. For example if you want to run the command against `node`:

  ```yaml
  jobs:
    example-command:
      steps:
        - shell: node
          run: |
            let a = 1;
            let b = a + 2;
            console.log(b);
  ```

### core/expand-template

Expands all the values in a template and outputs the resulting string.

Inputs:

- `input`: a string containing the template to expand.
- `input_file`: a file containing the template to expand.

Outputs:

- The resulting value after variable expansion.

#### Examples

Use a template file:

```yaml
jobs:
  update-nginx-config:
    name: Updates Nginx config
    steps:
      - uses: expand-template
        var:
          PROCESSES: 2
          USER: www-data
          SERVER: localhost
          ADDR: "127.0.0.1:80"
        with:
          input_file: ./templates/nginx.conf.template
          output_file: /usr/local/nginx/conf/nginx.conf
```

Use an input string:

```yaml
jobs:
  update-nginx-config:
    name: Updates Nginx config
    steps:
      - uses: expand-template
        var:
          PROCESSES: 2
          USER: www-data
          SERVER: localhost
          ADDR: "127.0.0.1:80"
        with:
          input: |
            worker_processes  ${{ PROCESSES }};
            user              ${{ USER }};

            http {
                server {
                    server_name   ${{ SERVER }};
                    listen        ${{ ADDR }};
                }
                # ... ommited for brevity
            }
          output_file: /usr/local/nginx/conf/nginx.conf
```

### docker/build

TBD

### docker/run

TBD

### docker/stop

TBD

### docker/get-pid

TBD

### docker/create-network

TBD

(to be finished)

## License

MIT License (see the LICENSE file).
