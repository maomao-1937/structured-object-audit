"""Audit object requirements in a saved OpenAI Structured Outputs schema."""

import json
import os
import posixpath
import re
import stat
import sys


MAX_FILE = 256 * 1024
MAX_POINTER = 1024
MAX_FINDINGS = 1024
DEVICE = re.compile(r"CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|(?:COM|LPT)[0-9¹²³]")
NATIVE_ROOTS = {"??", "device", "dosdevices", "global??", "systemroot", "globalroot"}
OBJECT_KEYWORDS = {
    "properties", "required", "additionalProperties", "patternProperties", "propertyNames",
    "dependentSchemas", "dependentRequired", "dependencies", "unevaluatedProperties",
    "minProperties", "maxProperties",
}


class InputError(ValueError):
    def __init__(self, code, pointer=None):
        super().__init__(code)
        self.code = code
        self.pointer = pointer


def check_path(path):
    spelling = path.replace("\\", "/")
    if not spelling or spelling == "-" or spelling.startswith("//") or spelling.endswith("/"):
        raise InputError("unsupported_path")
    if any(ord(char) < 32 for char in spelling):
        raise InputError("unsupported_path")
    if spelling.startswith("/"):
        for form in (spelling, posixpath.normpath(spelling)):
            if form[1:].partition("/")[0].rstrip(" .").lower() in NATIVE_ROOTS:
                raise InputError("unsupported_path")
    tail = spelling[2:] if re.match(r"^[A-Za-z]:/", spelling) else spelling
    if ":" in tail:
        raise InputError("unsupported_path")
    for part in tail.split("/"):
        if part in {"", ".", ".."}:
            continue
        stem = part.partition(".")[0].rstrip(" ").upper()
        if part.endswith((" ", ".")) or DEVICE.fullmatch(stem):
            raise InputError("unsupported_path")


def check_file(info):
    if not stat.S_ISREG(info.st_mode):
        raise InputError("not_regular_file")
    if info.st_size > MAX_FILE:
        raise InputError("file_too_large")


def read_schema(path):
    check_path(path)
    check_file(os.stat(path))
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        check_file(os.fstat(descriptor))
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(MAX_FILE + 1)
    finally:
        os.close(descriptor)
    if len(data) > MAX_FILE:
        raise InputError("file_too_large")
    return data


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        key.encode("utf-8")
        if key in result:
            raise InputError("duplicate_key")
        result[key] = value
    return result


def reject_constant(_text):
    raise InputError("nonstandard_constant")


def ignore_number(_text):
    # Numbers cannot satisfy any of the audited keywords' value checks.
    return None


def parse_schema(data):
    try:
        document = json.loads(
            data.decode("utf-8"), object_pairs_hook=unique_object,
            parse_constant=reject_constant, parse_int=ignore_number, parse_float=ignore_number,
        )
        pending = [document]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
            elif isinstance(value, str):
                value.encode("utf-8")
    except UnicodeDecodeError:
        raise InputError("invalid_utf8") from None
    except UnicodeEncodeError:
        raise InputError("unpaired_surrogate") from None
    except json.JSONDecodeError:
        raise InputError("invalid_json") from None
    except RecursionError:
        raise InputError("json_too_deep") from None
    return document


def child_pointer(pointer, *tokens):
    for token in tokens:
        pointer += "/" + token.replace("~", "~0").replace("/", "~1")
        if len(pointer) > MAX_POINTER:
            raise InputError("audit_limit")
    return pointer


def object_findings(schema, pointer, properties):
    if schema.get("additionalProperties") is not False:
        yield child_pointer(pointer, "additionalProperties"), "additional_properties"
    required = schema.get("required")
    if not isinstance(required, list):
        yield child_pointer(pointer, "required"), "required_type"
        return
    seen = set()
    for index, name in enumerate(required):
        entry = child_pointer(pointer, "required", str(index))
        if not isinstance(name, str):
            yield entry, "required_item_type"
            continue
        if name in seen:
            yield entry, "required_duplicate"
        if name not in properties:
            yield entry, "required_undeclared"
        seen.add(name)
    for name in properties.keys() - seen:
        yield child_pointer(pointer, "properties", name), "required_missing"


def schema_nodes(schema, pointer=""):
    if not isinstance(schema, dict):
        raise InputError("unsupported_structure", pointer)
    properties = schema.get("properties", {})
    definitions = schema.get("$defs", {})
    variants = schema.get("anyOf", [])
    for keyword, mapping in (("properties", properties), ("$defs", definitions)):
        if not isinstance(mapping, dict):
            raise InputError("unsupported_structure", child_pointer(pointer, keyword))
    if not isinstance(variants, list):
        raise InputError("unsupported_structure", child_pointer(pointer, "anyOf"))

    yield pointer, schema, properties
    # Walk siblings one at a time so they do not hold copies of a shared path prefix.
    for keyword, mapping in (("properties", properties), ("$defs", definitions)):
        for name in sorted(mapping):
            yield from schema_nodes(mapping[name], child_pointer(pointer, keyword, name))
    if "items" in schema:
        yield from schema_nodes(schema["items"], child_pointer(pointer, "items"))
    for index, branch in enumerate(variants):
        yield from schema_nodes(branch, child_pointer(pointer, "anyOf", str(index)))


def audit(document):
    findings = []
    for pointer, schema, properties in schema_nodes(document):
        schema_type = schema.get("type")
        if pointer == "":
            if schema_type != "object":
                findings.append(("/type", "root_type"))
            if "anyOf" in schema:
                findings.append(("/anyOf", "root_any_of"))

        if (schema_type == "object"
                or (isinstance(schema_type, list) and "object" in schema_type)
                or not OBJECT_KEYWORDS.isdisjoint(schema)):
            for finding in object_findings(schema, pointer, properties):
                if len(findings) == MAX_FINDINGS:
                    raise InputError("audit_limit")
                findings.append(finding)

    return [{"code": code, "pointer": pointer} for pointer, code in sorted(findings)]


def emit(data, code):
    remaining = memoryview(data)
    try:
        while remaining:
            written = os.write(1, remaining)
            if written <= 0:
                return 2
            remaining = remaining[written:]
    except OSError:
        return 2
    return code


def main(args):
    if args in (["--help"], ["-h"]):
        return emit(b"Usage: python structured_object_audit.py [--] SCHEMA.json\n", 0)
    try:
        if args[:1] == ["--"]:
            args = args[1:]
        elif args and args[0].startswith("-") and args[0] != "-":
            raise InputError("usage")
        if len(args) != 1:
            raise InputError("usage")
        findings = audit(parse_schema(read_schema(args[0])))
        report = {"status": "findings" if findings else "pass", "findings": findings}
        code = int(bool(findings))
    except InputError as error:
        detail = {"code": error.code}
        if error.pointer is not None:
            detail["pointer"] = error.pointer
        report, code = {"status": "error", "error": detail}, 2
    except (OSError, UnicodeError):
        report, code = {"status": "error", "error": {"code": "file_unreadable"}}, 2
    return emit(json.dumps(report, separators=(",", ":")).encode("ascii") + b"\n", code)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
