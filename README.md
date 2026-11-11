# structured-object-audit

Find missing object closure and mismatched `required` fields in a saved OpenAI Structured Outputs schema before sending it. The CLI reads a single local file with Python 3.11+ and the standard library. [OpenAI Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs)

[中文](#中文)

## Run

Clone the repository and enter its directory, or unpack the source archive and open the `structured-object-audit` directory.

```sh
git clone https://github.com/maomao-1937/structured-object-audit.git
cd structured-object-audit
```

Save the raw schema object from `text.format.schema`, `response_format.json_schema.schema`, or a strict tool's `parameters` to a UTF-8 file. Run these commands from the repository root.

```sh
python -I structured_object_audit.py examples/route.json
python -I structured_object_audit.py examples/sensor-findings.json
python -I structured_object_audit.py examples/root-union.json
python -I structured_object_audit.py examples/duplicate-member.json
```

`route.json` exits `0`. Its root and referenced definition pass the checked rules.

```json
{"status":"pass","findings":[]}
```

`sensor-findings.json` exits `1`. The `sensor/reading~` definition has no `additionalProperties`, omits `value` from `required`, and lists an undeclared field at `required[1]`.

```json
{"status":"findings","findings":[{"code":"additional_properties","pointer":"/$defs/sensor~1reading~0/additionalProperties"},{"code":"required_missing","pointer":"/$defs/sensor~1reading~0/properties/value"},{"code":"required_undeclared","pointer":"/$defs/sensor~1reading~0/required/1"}]}
```

`root-union.json` exits `1` because root-level `anyOf` is disallowed.

```json
{"status":"findings","findings":[{"code":"root_any_of","pointer":"/anyOf"}]}
```

`duplicate-member.json` exits `2` because the JSON contains a duplicate key.

```json
{"status":"error","error":{"code":"duplicate_key"}}
```

## Rules

- The root must explicitly declare `"type": "object"`. A root `anyOf` always violates the rule, and a well-shaped `anyOf` still gets traversed for nested findings.
- A nested schema counts as object-shaped when `type` is `"object"`, a `type` array contains `"object"`, or the schema declares an object keyword. The object markers are `properties`, `required`, `additionalProperties`, `patternProperties`, `propertyNames`, `dependentSchemas`, `dependentRequired`, `dependencies`, `unevaluatedProperties`, `minProperties`, and `maxProperties`.
- Each object shape must set `additionalProperties` to the literal `false`. Its `required` array must contain exactly the declared `properties` keys as unique strings, in any order. An omitted `properties` means zero declared fields, so an empty object shape still needs `"required": []`. That choice follows the assertion behavior of omitted `properties` in JSON Schema. [JSON Schema 2020-12 §10.3.2.1](https://json-schema.org/draft/2020-12/draft-bhutton-json-schema-01#section-10.3.2.1)
- Traversal covers schema objects in `properties`, `$defs`, object-valued `items`, and array-valued `anyOf`. Each declared definition is inspected once at its location. `$ref` targets, `examples`, `default`, and other keywords are outside traversal. An unsupported shape at one of the traversed locations yields an input error with the first such pointer. `properties` and `$defs` must be maps of schema objects when present. `items` and each `anyOf` branch must be schema objects.

Exit `0` means these checks pass. Model-specific limits, other keywords, reference validity, and provider acceptance are outside the audit. The CLI performs read-only inspection and runs offline.

## Reports

Each audit writes one JSON line to stdout. Findings are sorted by pointer, then by code. Pointers use RFC 6901 escaping (`~` becomes `~0` and `/` becomes `~1`). The empty pointer denotes the root. A pointer for a missing keyword names its expected location. Reports omit source values and file paths. Pointers can include property and definition names, so review them before sharing logs. [RFC 6901](https://www.rfc-editor.org/rfc/rfc6901#section-3)

| Finding code | Meaning |
| --- | --- |
| `root_type` | The root lacks the exact type string `object`. |
| `root_any_of` | The root declares `anyOf`. |
| `additional_properties` | `additionalProperties` is missing or differs from literal `false`. |
| `required_type` | `required` is missing or has a value other than an array. |
| `required_item_type` | A `required` entry has a value other than a string. |
| `required_duplicate` | A string repeats an earlier `required` entry. |
| `required_undeclared` | A `required` string has no matching `properties` key. |
| `required_missing` | A declared property is absent from the `required` array. |

The input must be a regular file on a local filesystem, at most 256 KiB (262,144 bytes), and UTF-8 without a byte order mark. URLs, stdin, UNC paths, and Windows device or stream paths are unsupported. The same portable path checks apply on Windows and Unix. Ordinary filesystem links and mounts resolve through the OS, so use a path whose target is local. `--` allows a filename beginning with a dash. `--help` prints usage text.

The audit caps constructed pointers at 1,024 Unicode code points after RFC 6901 escaping and reports at most 1,024 findings. Exceeding either limit produces a single `audit_limit` error with no pointer or partial findings.

| Input error code | Meaning |
| --- | --- |
| `usage` | The command needs one file argument. |
| `unsupported_path` | The path spelling falls outside the local-file interface. |
| `not_regular_file` | The path identifies a directory or another non-regular file. |
| `file_unreadable` | The file is missing or the OS could not read it. |
| `file_too_large` | The input exceeds 256 KiB. |
| `invalid_utf8` | The input contains invalid UTF-8 bytes. |
| `invalid_json` | The text has invalid JSON syntax or starts with a byte order mark. |
| `duplicate_key` | A JSON object repeats a member name. |
| `nonstandard_constant` | The input uses `NaN`, `Infinity`, or `-Infinity`. |
| `unpaired_surrogate` | A JSON string contains an unpaired surrogate escape. |
| `json_too_deep` | The JSON nesting exceeds the decoder's capacity. |
| `unsupported_structure` | The root or a traversed location has an unsupported JSON shape. |
| `audit_limit` | The escaped pointer length or finding count exceeds the audit limit. |

When stdout cannot be written, the process exits `2` and the report may be unavailable.

## Test

```sh
python -I -m unittest discover -s tests -v
python -I examples/run_examples.py
```

Locally verified with Python 3.11.15 on Windows. The examples runner checks exact stdout, exit codes, and empty stderr. The fixtures are synthetic. See [TESTING.md](TESTING.md) and [RESEARCH.md](RESEARCH.md).

## 中文

克隆仓库后进入 `structured-object-audit` 目录，也可以解压源码包后进入同名目录。

```sh
git clone https://github.com/maomao-1937/structured-object-audit.git
cd structured-object-audit
```

把请求里的 `text.format.schema`、`response_format.json_schema.schema` 或严格工具调用的 `parameters` 单独保存为 UTF-8 JSON。工具用 Python 3.11+ 标准库读取单个本地文件，在请求发出前定位对象约束问题。 [OpenAI Structured Outputs 官方文档](https://developers.openai.com/api/docs/guides/structured-outputs)

```sh
python -I structured_object_audit.py examples/route.json
python -I structured_object_audit.py examples/sensor-findings.json
python -I structured_object_audit.py examples/root-union.json
python -I structured_object_audit.py examples/duplicate-member.json
```

上方英文示例给出了逐字 JSON 输出。`route.json` 返回 `0`，表示通过已列明的检查。`sensor-findings.json` 和 `root-union.json` 返回 `1`，分别定位定义里的字段约束和根级 `anyOf`。`duplicate-member.json` 返回 `2`，表示 JSON 对象内有重复键。

- 根节点须显式写为 `"type": "object"`，且无根级 `anyOf`。嵌套节点的 `type` 为 `object`、类型数组含 `object`，或声明对象关键字时，会检查对象约束。
- 对象必须设置 `"additionalProperties": false`。`required` 必须是无重复的字符串数组，元素集合与 `properties` 键集合一致。省略 `properties` 视为没有声明字段，这时仍须显式写 `"required": []`。
- 遍历 `properties`、`$defs`、对象形式的 `items` 和 `anyOf` 数组中的子模式。定义在声明处只检查一次。`$ref` 目标、`examples`、`default` 和其他关键字不进入遍历。遍历位置结构不符合要求时，返回 `unsupported_structure` 和位置指针。
- 输入为最大 256 KiB 的本地普通文件，使用无 BOM 的 UTF-8。普通文件系统链接和挂载由操作系统解析，请使用目标也位于本地的路径。重复键、`NaN`、`Infinity` 和未配对的代理字符转义会被拒绝。报告省略原始值与文件路径，指针可能含字段名和定义名，分享前请检查。
- 指针经 RFC 6901 转义后最长为 1,024 个 Unicode 码位，问题最多 1,024 条。超过任一上限会返回 `audit_limit`，退出码为 `2`，输出不含指针或部分检查结果。
- 工具在本地只读运行。通过结果只覆盖上述对象规则。引用有效性、其他 JSON Schema 关键字以及服务端能否接受模式超出检查范围。

```sh
python -I -m unittest discover -s tests -v
python -I examples/run_examples.py
```

已在 Windows 的 Python 3.11.15 上通过测试与示例核对。

## License

[MIT](LICENSE)
