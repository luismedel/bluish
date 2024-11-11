# Bluish

> ##  Note to readers: This documentation is still in its early stages and may be (in fact, it is) incomplete.

Bluish automates software development and deployment tasks, similar to GitHub Actions, but for local execution or within Docker environments. This allows you to define, organize, and execute complex workflows in your own environment without relying on external services.

## Features

Bluish offers the following features to streamline your development workflows:

- **Make-like Ergonomics**: Bluish provides a command-line experience similar to `make`, thanks to its `blu` command. This allows you to quickly execute common tasks with commands like `blu build`, providing a familiar and efficient workflow for developers used to `make`.

- **Local Automation**: Execute complex tasks without the need for cloud services. Everything happens in your local environment, ensuring greater control over the process.

- **Container Integration**: Bluish can integrate with Docker, making it easy to run workflows inside containers, ensuring a controlled and replicable environment.

- **Easy to Configure**: Uses YAML files to define workflows, similar to GitHub Actions. This allows you to define steps in a clear and organized manner.

- **Extensible**: Thanks to its modular approach, you can easily customize and extend Bluish to suit your specific needs.

- **CI/CD Integration**: Bluish can be integrated with GitHub Actions, GitLab CI/CD, and other CI/CD runners. This allows you to have unified workflows that can be executed both locally and in different CI/CD environments, without needing to adapt to the specific characteristics of each platform. The same workflow you run locally can also be executed in other CI/CD systems.

## Installation

To install Bluish, you need to have Python (version 3.8 or higher) and Docker (version 20.10 or higher) installed on your machine.

```bash
pip install bluish
```

## Usage

_Please, refer to the project [wiki](https://github.com/luismedel/bluish/wiki) for a more in depth documentation._

Bluish uses a YAML configuration file (`bluish.yml`) to define workflows. Each workflow consists of multiple steps, which are executed in sequence. Below is a basic example of a configuration file:

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

Each workflow is defined by a series of steps, each with a name and a command that will be executed in your local environment or in a Docker container.

To run a workflow, simply use the command:

```bash
blu <workflow>
```

This command will look for the `bluish.yml` file in the current directory or in the `.bluish/` directory and execute the defined steps. If both files exist, `bluish.yml` in the current directory will take precedence.

## Examples

Here are some common examples of how Bluish can facilitate your daily workflow:

- **Local Continuous Integration**: Automate the process of building and testing your project without relying on a cloud CI platform.
- **Reproducible Environments with Docker**: Run and test your code in containers to ensure it behaves the same way regardless of where it is deployed.
- **Repetitive Scripts**: Automate repetitive development tasks, such as running tests, cleaning up artifacts, or generating builds in a simple way.

## Comparison with GitHub Actions

Bluish offers a similar experience to GitHub Actions, but with the advantage of being able to run locally or in your own containers. Below is a summary of the key differences:

| Feature               | GitHub Actions                | Bluish                                         |
| --------------------- | ----------------------------- | ---------------------------------------------- |
| Execution Environment | Cloud                         | Local / Docker Containers                      |
| Privacy               | Data hosted on GitHub servers | Fully local, no data exposure                  |
| Flexibility           | Tied to GitHub's CI/CD model  | Agnostic, adaptable to different CI/CD systems |
| Internet Requirement  | Yes                           | No                                             |

This makes Bluish ideal for developers who need:

- **Privacy**: Run workflows without exposing data to third-party platforms.
- **Flexibility and Control**: Define and modify environments and dependencies without limitations imposed by an external service.
- **Offline Development**: Use automated workflows without an internet connection.
- **Unified CI/CD Workflows**: Execute the same workflows both locally and in CI/CD environments like GitHub Actions, GitLab CI/CD, and others, making it easier to maintain consistency across different stages of development and deployment.

## Comparison with nektos/act

While the superb [nektos/act](https://github.com/nektos/act) allows you to run GitHub Actions locally, it is tied to the GitHub Actions specification, which can limit flexibility. For example, `nektos/act` strictly adheres to the GitHub Actions syntax and conventions, which means that workflows must follow GitHub's specific rules and may require adaptation if used elsewhere.

Bluish, on the other hand, is more agnostic and allows you to define and execute workflows without being restricted to the GitHub Actions structure. This makes Bluish a more versatile choice if you are looking to create workflows that can be used across multiple CI/CD systems or if you prefer not to be bound by a specific CI/CD provider's conventions.

## Contributing

Contributions are welcome! If you want to improve Bluish, feel free to open an issue or send a pull request. Check the [contribution guidelines](https://github.com/luismedel/bluish/blob/main/CONTRIBUTING.md) in the repository for more details.

## License

This project is licensed under the MIT License. See the `LICENSE` file for more information.

## Contact

For any questions or suggestions, feel free to open an issue in the repository or contact me directly through my GitHub profile: [luismedel](https://github.com/luismedel).
