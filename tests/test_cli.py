import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "structured_object_audit.py"
EMPTY = {"type": "object", "additionalProperties": False, "required": []}


def run_cli(*args):
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), *args],
        capture_output=True, encoding="utf-8", timeout=10,
    )


class AuditTests(unittest.TestCase):
    def assert_report(self, result, exit_code, report):
        self.assertEqual(result.returncode, exit_code, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(json.loads(result.stdout), report)

    def audit_bytes(self, content):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / "raw schema.json"
            fixture.write_bytes(content)
            return run_cli(str(fixture))

    def audit(self, schema):
        return self.audit_bytes(json.dumps(schema).encode("utf-8"))

    def assert_findings(self, result, *findings):
        self.assert_report(result, 1, {
            "status": "findings",
            "findings": [{"code": code, "pointer": pointer} for code, pointer in findings],
        })

    def assert_error(self, result, code, pointer=None):
        error = {"code": code}
        if pointer is not None:
            error["pointer"] = pointer
        self.assert_report(result, 2, {"status": "error", "error": error})

    def test_empty_object_without_properties_passes(self):
        self.assert_report(self.audit(EMPTY), 0, {"status": "pass", "findings": []})

    def test_fields_are_matched_as_sets_and_nullable_nested_object_passes(self):
        schema = {**EMPTY, "required": ["b", "a"], "properties": {
            "a": {**EMPTY, "type": ["null", "object"]}, "b": {"type": "string"},
        }}
        self.assert_report(self.audit(schema), 0, {"status": "pass", "findings": []})

    def test_root_must_have_exact_object_type(self):
        for root_type in (None, "array", ["object", "null"], ["object"]):
            with self.subTest(root_type=root_type):
                schema = dict(EMPTY)
                schema.pop("type")
                if root_type is not None:
                    schema["type"] = root_type
                self.assert_findings(self.audit(schema), ("root_type", "/type"))

    def test_root_anyof_is_prohibited_and_branches_are_still_checked(self):
        schema = {**EMPTY, "anyOf": [{"type": "object", "required": []}]}
        self.assert_findings(self.audit(schema), ("root_any_of", "/anyOf"),
                             ("additional_properties", "/anyOf/0/additionalProperties"))

    def test_nonliteral_false_is_a_finding(self):
        for bad in (None, True, 0, "false", {}):
            with self.subTest(bad=bad):
                self.assert_findings(self.audit({**EMPTY, "additionalProperties": bad}),
                                     ("additional_properties", "/additionalProperties"))

    def test_required_must_be_present_and_an_array(self):
        for schema in ({"type": "object", "additionalProperties": False},
                       {**EMPTY, "required": "field"}):
            with self.subTest(schema=schema):
                self.assert_findings(self.audit(schema), ("required_type", "/required"))

    def test_required_reports_missing_duplicate_extra_and_nonstring(self):
        result = self.audit({**EMPTY, "properties": {"a/~": {}, "b": {}},
                             "required": ["b", "b", "private-value", False]})
        self.assert_findings(result, ("required_missing", "/properties/a~1~0"),
                             ("required_duplicate", "/required/1"),
                             ("required_undeclared", "/required/2"),
                             ("required_item_type", "/required/3"))
        self.assertNotIn("private-value", result.stdout)

    def test_structural_locations_and_order_are_stable(self):
        z = {"type": "array", "items": {"anyOf": [
            {"type": "string"}, {"type": ["object", "null"], "required": []},
        ]}}
        a = {"properties": {}}
        base = {**EMPTY, "required": ["z", "a"]}
        first = self.audit({**base, "properties": {"z": z, "a": a}})
        second = self.audit({**base, "properties": {"a": a, "z": z}})
        self.assert_findings(first, ("additional_properties", "/properties/a/additionalProperties"),
                             ("required_type", "/properties/a/required"),
                             ("additional_properties", "/properties/z/items/anyOf/1/additionalProperties"))
        self.assertEqual(first.stdout, second.stdout)

    def test_definitions_are_checked_once_even_if_referenced_twice(self):
        schema = {**EMPTY, "required": ["a", "b"], "properties": {
            "a": {"$ref": "#/$defs/~0~1"}, "b": {"$ref": "https://example.invalid/remote"},
        }, "$defs": {"~/": {"type": "object", "properties": {
            "child": {"$ref": "#/$defs/~0~1"},
        }, "required": ["child"]}}}
        schema["properties"]["b"] = {"anyOf": [schema["properties"]["a"], schema["properties"]["b"]]}
        self.assert_findings(self.audit(schema), ("additional_properties", "/$defs/~0~1/additionalProperties"))

    def test_object_markers_without_type_trigger_checks(self):
        schema = {**EMPTY, "required": ["a"], "properties": {"a": {"minProperties": 1}}}
        self.assert_findings(self.audit(schema), ("additional_properties", "/properties/a/additionalProperties"),
                             ("required_type", "/properties/a/required"))

    def test_examples_and_defaults_are_not_schema_locations(self):
        bad = {"type": "object", "properties": {}, "additionalProperties": True}
        schema = {**EMPTY, "examples": [bad], "default": bad}
        self.assert_report(self.audit(schema), 0, {"status": "pass", "findings": []})

    def test_malformed_traversal_locations_are_input_errors(self):
        for shape, pointer in (({"properties": []}, "/properties"),
                               ({"properties": {"a/": 42}}, "/properties/a~1"),
                               ({"$defs": False}, "/$defs"),
                               ({"$defs": {"": None}}, "/$defs/"),
                               ({"items": [{"type": "object"}]}, "/items"),
                               ({"anyOf": {}}, "/anyOf"),
                               ({"anyOf": [True]}, "/anyOf/0")):
            with self.subTest(shape=shape):
                self.assert_error(self.audit({**EMPTY, **shape}), "unsupported_structure", pointer)

    def test_nonobject_schema_is_an_input_error(self):
        for document in (True, [], None, "type", 12):
            with self.subTest(document=document):
                self.assert_error(self.audit(document), "unsupported_structure", "")

    def test_duplicate_keys_are_rejected_even_in_annotations(self):
        result = self.audit_bytes(br'{"default":{"private":"x","\u0070rivate":"y"}}')
        self.assert_error(result, "duplicate_key")
        self.assertNotIn("private", result.stdout)

    def test_rejects_invalid_json_encoding_constants_and_surrogates(self):
        invalid = ((b'{"default": "\xff"}', "invalid_utf8"),
                   (b'\xef\xbb\xbf{}', "invalid_json"),
                   (b'{} {}', "invalid_json"),
                   (b'{"default": NaN}', "nonstandard_constant"),
                   (b'{"default": Infinity}', "nonstandard_constant"),
                   (b'{"default": -Infinity}', "nonstandard_constant"),
                   (br'{"\ud800": 0}', "unpaired_surrogate"),
                   (br'{"default": ["\udc00"]}', "unpaired_surrogate"))
        for content, code in invalid:
            with self.subTest(content=content):
                self.assert_error(self.audit_bytes(content), code)

    def test_valid_escaped_surrogate_pair_and_large_json_number(self):
        base = br'{"type":"object","additionalProperties":false,"required":["\ud83d\ude00"],'
        content = base + '"properties":{"😀":{}},"default":'.encode()
        content += b"9" * 5000 + b"}"
        self.assert_report(self.audit_bytes(content), 0, {"status": "pass", "findings": []})

    def test_file_byte_limit_is_inclusive(self):
        data = json.dumps(EMPTY).encode().ljust(256 * 1024, b" ")
        self.assert_report(self.audit_bytes(data), 0, {"status": "pass", "findings": []})
        self.assert_error(self.audit_bytes(data + b" "), "file_too_large")

    def test_pointer_limit_prevents_amplification_from_long_common_prefix(self):
        name = "a" * 2000
        schema = {**EMPTY, "required": [name], "properties": {
            name: {"anyOf": [{"type": "object"}] * 32},
        }}
        self.assert_error(self.audit(schema), "audit_limit")

    def test_pointer_limit_counts_escaped_code_points_and_is_inclusive(self):
        name = "~" * 506  # /properties/ plus 506 escaped tokens occupies 1024 code points.
        schema = {**EMPTY, "required": [name], "properties": {name: {}}}
        self.assert_report(self.audit(schema), 0, {"status": "pass", "findings": []})
        self.assert_error(self.audit({**schema, "required": [name + "a"],
                                     "properties": {name + "a": {}}}), "audit_limit")
        schema["properties"][name] = {"type": "object"}
        self.assert_error(self.audit(schema), "audit_limit")

    def test_findings_limit_is_inclusive(self):
        schema = {**EMPTY, "required": ["a"] * 1025, "properties": {"a": {}}}
        result = self.audit(schema)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "findings")
        self.assertEqual(len(report["findings"]), 1024)
        self.assert_error(self.audit({**schema, "required": ["a"] * 1026}), "audit_limit")

    def test_decoder_nesting_error_is_structured(self):
        self.assert_error(self.audit_bytes(b"[" * 3000 + b"0" + b"]" * 3000), "json_too_deep")

    def test_nonregular_files_and_unsafe_spellings_are_rejected(self):
        for path in ("-", "https://example.invalid/schema", "//server/schema", r"\/?\NUL",
                     "/temp/../Device/NamedPipe/schema", "C:schema", "NUL.json", "schema.json."):
            with self.subTest(path=path):
                self.assert_error(run_cli("--", path), "unsupported_path")
        with tempfile.TemporaryDirectory() as directory:
            self.assert_error(run_cli(directory), "not_regular_file")
            self.assert_error(run_cli(str(Path(directory) / "absent.json")), "file_unreadable")
            if hasattr(os, "mkfifo"):
                fifo = Path(directory) / "schema.pipe"
                os.mkfifo(fifo)
                self.assert_error(run_cli(str(fifo)), "not_regular_file")

    def test_arity_errors_use_exit_two_and_help_exits_zero(self):
        for args in ((), ("one", "two"), ("--extra",)):
            with self.subTest(args=args):
                self.assert_error(run_cli(*args), "usage")
        result = run_cli("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SCHEMA", result.stdout)


if __name__ == "__main__":
    unittest.main()
