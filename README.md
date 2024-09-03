# Bluish

The CI/CD/automation tool I use for my personal projects.

Why use a rock-solid tool when you can code your own crappy _Make on steroids_ alternative?

## Features

- YAML-based declarative approach (not that I love YAML, but...)
- Githubactions-esque philosphy, but way simpler. In fact, Bluish is nearer to Make than to GA.
- Simple as fuck. I only add new actions whenever I need them.

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

Note that the similarity with other tools like Github Actions is very superficial. Please, refer to the [project docs](https://github.com/luismedel/bluish/wiki) for more details about the _huge_ differences.
