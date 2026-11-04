"""AST checks for type hints and docstrings on newly added public functions."""

from __future__ import annotations

import ast
import logging
from collections.abc import Iterable, Iterator, Mapping

from harness.checks.rules import ValidationRule, get_rule
from harness.schemas import Finding

logger = logging.getLogger(__name__)

__all__ = ["check_ast", "run_ast_checks"]

_PUBLIC_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def run_ast_checks(
    sources: Mapping[str, str],
    changed_lines: Mapping[str, Iterable[int]],
    *,
    hint_rule: ValidationRule | None = None,
    docstring_rule: ValidationRule | None = None,
) -> list[Finding]:
    """Check new public functions in ``sources`` for hints and docstrings.

    Only functions whose ``def`` line is in ``changed_lines[path]`` are checked,
    so pre-existing gaps are left alone. Files that cannot be parsed are skipped
    with a log message rather than failing the whole run.
    """

    hint_rule = hint_rule or get_rule("type_hints")
    docstring_rule = docstring_rule or get_rule("docstrings")
    findings: list[Finding] = []

    for path, source in sources.items():
        if not path.endswith(".py"):
            continue
        lines = set(changed_lines.get(path, ()))
        if not lines:
            continue
        tree = _parse(source, path)
        if tree is None:
            continue
        for node in _public_functions(tree):
            if node.lineno not in lines:
                continue
            findings.extend(check_ast(path, node, hint_rule, docstring_rule))

    logger.info("AST checks produced %d finding(s)", len(findings))
    return findings


def check_ast(
    path: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    hint_rule: ValidationRule,
    docstring_rule: ValidationRule,
) -> list[Finding]:
    """Return the missing-hint and missing-docstring findings for one function."""

    findings: list[Finding] = []
    if not _has_type_hints(node):
        findings.append(
            Finding(
                file=path,
                line=node.lineno,
                severity=hint_rule.severity,
                confidence=1.0,
                issue=f"New public function `{node.name}` is missing type hints.",
                suggested_fix=f"Annotate the parameters and return type of `{node.name}`.",
            )
        )
    if not ast.get_docstring(node, clean=True):
        findings.append(
            Finding(
                file=path,
                line=node.lineno,
                severity=docstring_rule.severity,
                confidence=1.0,
                issue=f"New public function `{node.name}` has no docstring.",
                suggested_fix=f"Add a docstring to `{node.name}` describing its behaviour.",
            )
        )
    return findings


def _parse(source: str, path: str) -> ast.Module | None:
    """Parse ``source`` and log (instead of raising) on invalid Python."""

    try:
        return ast.parse(source, filename=path)
    except (SyntaxError, ValueError) as exc:
        logger.warning("skipping AST checks for %s: %s", path, exc)
        return None


def _public_functions(tree: ast.Module) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    """Yield module-level and class-level functions whose names are public."""

    for node in tree.body:
        if isinstance(node, _PUBLIC_FUNCTIONS) and not node.name.startswith("_"):
            yield node
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, _PUBLIC_FUNCTIONS) and not child.name.startswith("_"):
                    yield child


def _has_type_hints(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True when every non-self parameter and the return value is annotated."""

    arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    if node.args.vararg is not None:
        arguments.append(node.args.vararg)
    if node.args.kwarg is not None:
        arguments.append(node.args.kwarg)
    for argument in arguments:
        if argument.arg in {"self", "cls"}:
            continue
        if argument.annotation is None:
            return False
    return node.returns is not None
