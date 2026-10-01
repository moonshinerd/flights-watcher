.PHONY: setup test check start history clean

setup:
	uv sync

test:
	uv run pytest -v

check:
	uv run flight-monitor check

start:
	uv run flight-monitor start

history:
	uv run flight-monitor history

clean:
	rm -rf .pytest_cache __pycache__ *.db
