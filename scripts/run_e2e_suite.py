"""Thin wrapper to run the E2E suite."""

from e2e_eval.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["run", "--all"]))
