"""Global shared constants for the PR review harness."""

from __future__ import annotations

__all__ = ["DEFAULT_NOISE_PATTERNS"]

# Paths that rarely need human review. Patterns use fnmatch semantics.
DEFAULT_NOISE_PATTERNS: tuple[str, ...] = (
    # Lockfiles
    "*.lock",
    "uv.lock",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "pnpm-lock.yaml",
    "Pipfile.lock",
    # Generated / build output
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.generated.*",
    "*_pb2.py",
    "*_pb2_grpc.py",
    "migrations/*",
    "*/migrations/*",
    "dist/*",
    "*/dist/*",
    "build/*",
    "*/build/*",
    # Vendored / third-party
    "vendor/*",
    "*/vendor/*",
    "vendored/*",
    "*/vendored/*",
    "node_modules/*",
    "*/node_modules/*",
    "third_party/*",
    "*/third_party/*",
    # Images and binary artefacts
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.svg",
    "*.ico",
    "*.webp",
    "*.pdf",
    "*.zip",
    "*.gz",
    "*.tar",
    "*.whl",
    "*.so",
    "*.dll",
    "*.exe",
    "*.pyc",
)
