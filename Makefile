.PHONY: init check format test run tree

init:
\tpython3 --version

check:
\t@echo "TODO: add lint/type/test/config checks"

format:
\t@echo "TODO: add formatter"

test:
\t@echo "TODO: add tests"

run:
\t@echo "TODO: add app runner"

tree:
\tfind . -maxdepth 3 | sort
