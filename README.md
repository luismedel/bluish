# Bluish

A CI/CD/automation tool that runs everywhere and have `make` ergonomics.

## Features

- YAML-based declarative approach (not that I love YAML, but...)
- Githubactions-esque philosphy, but way simpler. In fact, Bluish is nearer to Make than to GA.
- Runs _everywhere_, not tied to any vendor. Fire Bluish workflows from Github Actions, from a Gitlab workflow or from a cron-invoked a shell script.  
- Simple as hell. I only add new actions whenever I need them.

## Documentation

Please, refer to the [project wiki](https://github.com/luismedel/bluish/wiki).

## How do Bluish workflows look?

If you know other CI/CD tools, the following yaml will look more than familiar to you and you probably don't need an explanation.

```yaml
var:
  PYTHON_VERSION: "3.11"
  PYTEST_RUNNERS: 2

jobs:
  lint:
    name: Runs ruff and mypy
    steps:
      - run: |
          ruff version
          ruff check src/ test/
          echo ""
          mypy --version
          mypy --ignore-missing-imports --python-version=${{ var.PYTHON_VERSION }} src/ test/

  fix:
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
          pytest -n ${{ var.PYTEST_RUNNERS }}
```
