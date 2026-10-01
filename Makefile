.PHONY: setup test check start history clean

setup:
	uv sync

test:
	uv run pytest -v

check:
	uv run flights-watcher check

start:
	uv run flights-watcher start

history:
	uv run flights-watcher history

clean:
	rm -rf .pytest_cache __pycache__ *.db
