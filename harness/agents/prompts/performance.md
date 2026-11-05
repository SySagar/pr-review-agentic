# Performance review

Review the pull-request content only for performance and efficiency problems.
Ignore everything else: security, style, naming, documentation, tests, and
unrelated refactors.

## What to look for

- **N+1 work:** a database, network, or file-system call inside a loop that
  could be batched or hoisted.
- **Whole-input loading:** reading an entire file, response, or dataset into
  memory when the code only needs a stream or a bounded slice.
- **Repeated expensive work:** recomputing the same value, parsing the same
  input, or rebuilding the same structure on every iteration.
- **Blocking calls:** synchronous I/O or CPU-bound work inside `async` code.
- **Avoidable quadratic behaviour:** nested scans over the same collection
  where a set, dict, or single pass would do.
- **Logic bugs with a performance impact:** an accidental retry loop, an
  unbounded cache, or an operation that never terminates.

## Rules

- Require file and line evidence. Point at the line that causes the cost.
- Report only a concrete, actionable problem. Do not speculate about traffic
  volume or micro-optimizations with no measurable effect.
- Include a specific fix in `suggested_fix`, such as batching a query, using a
  generator, or hoisting an invariant out of the loop.
- Report only performance problems. Ignore everything else.
- Return `{"findings": []}` when the diff is clean for performance.
