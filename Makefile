deps:
	@poetry install

build: deps
	rm -fR dist/
	poetry build

docs: deps
	sphinx-build -M html docs/source/ docs/build/

test: deps
	pytest example/demo/tests example/transport_network/tests

lint: deps build
	pre-commit run -a

ci: lint test
