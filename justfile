# One definition of what "passing" means, so the pre-commit hook, the
# pre-push hook and CI cannot drift apart. `just check` is what CI runs.

default: check

# Everything, in the order that fails cheapest first.
check: lint lock test

# Fast enough to sit in a pre-commit hook.
lint:
    uv run ruff check .

lint-fix:
    uv run ruff check . --fix

test:
    uv run pytest -q

# The lockfile drifted behind pyproject once and nothing noticed until a
# dependency was missing on a machine that installed from it.
lock:
    uv lock --check

# Regenerate the measured tables in the README. The constraints table is
# offline; the forms table reads a live page and needs a browser.
measure url="https://theangrygm.com/ask-angry-journey-home/":
    uv run scripts/measure.py constraints --write README.md
    uv run scripts/measure.py forms {{url}} --write README.md
