# Testing

Run from the repository root with Python 3.11 or later.

```sh
python -I -m unittest discover -s tests -v
python -I examples/run_examples.py
```

The tests run the standalone script against synthetic files. They cover root and nested object checks, declaration matching, pointer escaping and ordering, definitions and references, annotation values, malformed schema locations, duplicate JSON keys, UTF-8 and surrogate handling, nonstandard constants, local file handling, and the file size, pointer length, and finding count limits.

`checks.json` records the arguments, expected exit status, and JSON report for each documented fixture. `examples/run_examples.py` checks the full output line and empty stderr. GitHub Actions runs both commands on Ubuntu and Windows with Python 3.11.
