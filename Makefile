

lint:
	ruff version
	ruff check src/
	@echo ""
	mypy --version
	mypy --ignore-missing-imports --python-version=3.11 src/

lint-fix:
	ruff version
	ruff check --select I --fix src/
	ruff format src/
	@echo ""
