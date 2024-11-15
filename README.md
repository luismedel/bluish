[![justforfunnoreally.dev badge](https://img.shields.io/badge/justforfunnoreally-dev-9ff)](https://justforfunnoreally.dev)
# Bluish

Bluish automates software development and deployment tasks, similar to GitHub Actions, but for local execution or within Docker. It allows you to define, organize, and execute workflows in your own environment without relying on external services.

## Features

- **Command-Line Interface**: Bluish offers a `make`-like experience via the `blu` command for easy task execution (e.g., `blu build`).
- **Local and Remote Automation**: Execute tasks locally, without needing cloud services, or remotely via SSH.
- **Docker Integration**: Run workflows in Docker containers for a controlled environment.
- **Simple Configuration**: Define workflows in YAML files, following a familiar structure for defining steps.
- **CI/CD Integration**: Integrate with GitHub Actions, GitLab CI/CD, and other CI/CD tools for unified local and remote workflows.

## Installation

```bash
pip install bluish
```

## Usage

Refer to the project [wiki](https://github.com/luismedel/bluish/wiki) for more detailed documentation. Please note that the documentation is still in progress and may be incomplete or not fully reliable.

Define workflows in a YAML file (`bluish.yml`). Each workflow contains steps executed in sequence. Example:

```yaml
name: My Local Workflow

steps:
  - name: Clone repository
    uses: git/checkout
    with:
      repository: https://github.com/myuser/myproject.git

  - name: Build Docker image
    run: docker build -t myproject .

  - name: Run tests
    run: docker run --rm myproject pytest

  - name: Cleanup
    run: docker rmi myproject
```

To run a workflow:

```bash
blu <workflow>
```

The command looks for `bluish.yml` in the current or `.bluish/` directory.

## Examples

- **Local CI**: Build and test your project without a cloud CI platform.
- **Reproducible Environments**: Run code in Docker containers for consistency.
- **Task Automation**: Automate repetitive development tasks.

## Comparison with GitHub Actions

| Feature               | GitHub Actions                | Bluish                                         |
| --------------------- | ----------------------------- | ---------------------------------------------- |
| Execution Environment | Cloud                         | Local / Remote / Docker Containers             |
| Privacy               | Data hosted on GitHub servers | No data exposure, or exposure that is tightly controlled                               |
| Flexibility           | Tied to GitHub's CI/CD model  | Agnostic, adaptable to different CI/CD systems |
| Internet Requirement  | Yes                           | No                                             |

Bluish is ideal for:

- **Privacy**: No data exposed to third-party platforms.
- **Control**: Define and modify environments without external limitations.
- **Offline Development**: Use workflows without internet.
- **Unified Workflows**: Consistent local and CI/CD workflows.

## Comparison with nektos/act

[nektos/act](https://github.com/nektos/act) runs GitHub Actions locally but is tied to GitHub's syntax. Bluish offers more flexibility and is not restricted by GitHub-specific rules, making it more versatile across different CI/CD systems.

## Contributing

Contributions are welcome! Open an issue or send a pull request. See the [contribution guidelines](https://github.com/luismedel/bluish/blob/main/CONTRIBUTING.md) for more details.

## License

Licensed under the MIT License. See the `LICENSE` file for details.

## Contact

For questions or suggestions, open an issue in the repository or contact me on GitHub: [luismedel](https://github.com/luismedel).
