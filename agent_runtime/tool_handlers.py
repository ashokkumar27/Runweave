"""Installed version-one toolkit handlers; all invoked in activities."""

import difflib
import json

from fastmcp import Client

from .artifacts import archive
from .config import settings
from .sandbox import run_python
from .tool_registry import ToolRegistry

CSV_CODE = """import csv,io,json
from decimal import Decimal
with open('/input/data',newline='') as f:
    reader=csv.DictReader(f)
    if reader.fieldnames != ['invoice_id','amount']: raise ValueError('columns')
    rows=list(reader)
seen=set(); clean=[]; total=Decimal(0); refunds=0
for row in rows:
    if row['invoice_id'] in seen: continue
    seen.add(row['invoice_id']); amount=Decimal(row['amount'])
    if not amount.is_finite(): raise ValueError('amount')
    total+=amount; refunds+=int(amount<0); clean.append(row)
with open('/output/result','w',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=['invoice_id','amount'],lineterminator='\\n')
    writer.writeheader(); writer.writerows(clean)
print(json.dumps(dict(rows=len(rows),unique=len(clean),duplicates=len(rows)-len(clean),refunds=refunds,net=str(total))))
"""


def excerpt(ref, text, start=1, count=40, path=None):
    lines = text.splitlines()
    if start > len(lines) and lines:
        raise ValueError("line_range_invalid")
    selected = lines[start - 1 : start - 1 + count]
    if len("\n".join(selected).encode()) > 8192:
        raise ValueError("context_limit")
    evidence = []
    if selected:
        evidence = [
            {
                "artifact_id": ref.id,
                "sha256": ref.sha256,
                "path": path,
                "start_line": start,
                "end_line": start + len(selected) - 1,
                "quote": "\n".join(selected)[:512],
            }
        ]
    return {
        "lines": [{"line": start + i, "text": text} for i, text in enumerate(selected)],
        "evidence": evidence,
    }


async def execute(store, run_id, call_id, name, arguments):
    feature = await store.toolkit(run_id)
    entry = feature["tools"].get(name)
    if entry is None:
        raise ValueError("tool_not_selected")
    schema = ToolRegistry.validate_snapshot(entry)
    args = schema.model_validate(arguments).model_dump()
    old = await store.operation_result(run_id, call_id, {"tool": name, "arguments": args})
    if old is not None:
        return old
    if name != "record_note":
        await store.reserve_usage(run_id, "tool_calls")
    if name == "add":
        result = {"value": args["a"] + args["b"]}
    elif name == "convert_temperature":
        async with Client(settings().mcp_url, timeout=10) as client:
            value = await client.call_tool(name, args, timeout=10)
            result = {"value": float(value.data)}
    elif name == "record_note":
        result = {"value": await store.record_note(run_id, call_id, args["text"])}
    elif name == "document_compare":
        left, a = await store.artifact(args["left_id"], run_id)
        right, b = await store.artifact(args["right_id"], run_id)
        if left.media_type == "application/zip" or right.media_type == "application/zip":
            raise ValueError("text_artifact_required")
        al, bl = a.decode().splitlines(True), b.decode().splitlines(True)
        diff = "".join(difflib.unified_diff(al, bl, fromfile=left.filename, tofile=right.filename)).encode()
        ref = await store.upload(diff, "text/x-diff", "comparison.diff", f"tool:{run_id}:{call_id}", run_id)
        # Include unchanged surrounding original lines, avoiding inference from a diff alone.
        evidence = (
            excerpt(left, a.decode(), 1, min(10, len(al)))["evidence"]
            + excerpt(right, b.decode(), 1, min(10, len(bl)))["evidence"]
        )
        result = {"equal": a == b, "evidence": evidence[:12], "artifact": ref.model_dump(mode="json")}
    elif name in {
        "document_read",
        "document_search",
        "repository_read",
        "repository_inspect",
        "repository_patch",
        "csv_analyze",
        "python_analyze",
    }:
        ref, content = await store.artifact(args["artifact_id"], run_id)
        if name.startswith("repository_"):
            if ref.media_type != "application/zip":
                raise ValueError("repository_archive_required")
            files = archive(content)
            if name == "repository_inspect":
                result = {"files": [{"path": p, "lines": len(t.splitlines())} for p, t in files.items()]}
            else:
                path = args["path"]
                if path not in files:
                    raise ValueError("repository_path_not_found")
                text = files[path]
                if name == "repository_read":
                    result = excerpt(ref, text, args["start_line"], args["max_lines"], path)
                else:
                    if text.count(args["old"]) != 1:
                        raise ValueError("patch_requires_unique_match")
                    new = text.replace(args["old"], args["new"], 1)
                    diff = "".join(
                        difflib.unified_diff(
                            text.splitlines(True),
                            new.splitlines(True),
                            fromfile="a/" + path,
                            tofile="b/" + path,
                        )
                    ).encode()
                    output = await store.upload(
                        diff, "text/x-diff", "fix.patch", f"tool:{run_id}:{call_id}", run_id
                    )
                    line = text[: text.index(args["old"])].count("\n") + 1
                    result = {
                        "artifact": output.model_dump(mode="json"),
                        **excerpt(ref, text, line, min(5, len(args["old"].splitlines())), path),
                    }
        elif name in {"csv_analyze", "python_analyze"}:
            code = CSV_CODE if name == "csv_analyze" else args["code"]
            deadline = await store.sandbox_intent(run_id, f"{run_id}:{call_id}")
            data, stdout = await run_python(f"{run_id}:{call_id}", code, content, deadline=deadline)
            output = await store.upload(
                data,
                "text/csv" if name == "csv_analyze" else "text/plain",
                "cleaned.csv" if name == "csv_analyze" else "result.txt",
                f"tool:{run_id}:{call_id}",
                run_id,
            )
            result = {
                "artifact": output.model_dump(mode="json"),
                "measurements": json.loads(stdout) if name == "csv_analyze" else stdout[:4000],
            }
        else:
            if ref.media_type == "application/zip":
                raise ValueError("text_artifact_required")
            text = content.decode()
            if name == "document_read":
                result = excerpt(ref, text, args["start_line"], args["max_lines"])
            else:
                matches = [
                    i + 1
                    for i, line in enumerate(text.splitlines())
                    if args["query"].casefold() in line.casefold()
                ][:12]
                result = {"matches": [excerpt(ref, text, line, 1) for line in matches]}
                result["evidence"] = [e for m in result["matches"] for e in m["evidence"]]
    else:
        raise ValueError("unsupported_tool")
    return await store.save_operation(run_id, call_id, result, name)
