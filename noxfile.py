import nox

nox.options.sessions = ["lint", "format", "typecheck", "tests"]


@nox.session
def lint(session: nox.Session) -> None:
    session.install("-e", ".[dev]")
    session.run("ruff", "check", "--fix", "src", "tests")
    # session.run("ruff", "format", "--check", "src", "tests")


@nox.session
def format(session: nox.Session) -> None:
    session.install("-e", ".[dev]")
    session.run("ruff", "format", "src", "tests")


@nox.session
def typecheck(session: nox.Session) -> None:
    session.install("-e", ".[dev]")
    session.run("mypy", "--install-types")
    session.run("mypy", "src", "tests")


@nox.session
def tests(session: nox.Session) -> None:
    session.install("-e", ".[dev]")
    session.run("pytest", "--cov=insider_scanner", "--cov-report=term-missing")
