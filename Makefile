

lint:
	ruff version
	ruff check src/ test/
	@echo ""
	mypy --version
	mypy --ignore-missing-imports --python-version=3.11 src/ test/

lint-fix:
	ruff version
	ruff check --select I --fix src/ test/
	ruff format src/
	@echo ""
