deps:
	@uv sync --extra dev

build: deps
	rm -fR dist/
	uv build

docs: deps
	uv run sphinx-build -M html docs/source/ docs/build/

test: deps
	uv run pytest example/demo/tests example/transport_network/tests

lint: deps
	uv run ruff check .
	uv run ruff format --check .

ci: lint test
