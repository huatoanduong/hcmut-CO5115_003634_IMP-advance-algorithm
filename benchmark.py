"""Score and time FastSolution on a labelled test file.

Usage:  python benchmark.py [test_file.json] [repeat] [-v]
The test file is a list of {"text": ..., "result": {"province", "district", "ward"}}.
Run it from the folder holding list_province.txt, list_district.txt, list_ward.txt.
"""
import json
import sys
import time
import unicodedata

from FastSolution import Solution

# Old vs new tone-mark placement, treated as the same name ("Hoà" == "Hòa").
TONE_STYLE = {
    "oà": "òa", "oá": "óa", "oả": "ỏa", "oã": "õa", "oạ": "ọa",
    "oè": "òe", "oé": "óe", "oẻ": "ỏe", "oẽ": "õe", "oẹ": "ọe",
    "uỳ": "ùy", "uý": "úy", "uỷ": "ủy", "uỹ": "ũy", "uỵ": "ụy",
    "qui": "quy",
}


def same_form(name):
    """Canonical form for comparing names: case, spacing, tone placement, leading zeros."""
    name = " ".join(unicodedata.normalize("NFC", name).lower().split())
    for old, new in TONE_STYLE.items():
        name = name.replace(old, new)
    return str(int(name)) if name.isdigit() else name


def main():
    args = [a for a in sys.argv[1:] if a != "-v"]
    test_file = args[0] if args else "public.json"
    repeat = int(args[1]) if len(args) > 1 else 3

    t0 = time.perf_counter()
    solution = Solution()
    build_ms = (time.perf_counter() - t0) * 1000

    with open(test_file, encoding="utf-8") as f:
        data = json.load(f)

    times, field_ok, failures = [], [0, 0, 0], []
    for r in range(repeat):
        for item in data:
            start = time.perf_counter_ns()
            result = solution.process(item["text"])
            times.append(time.perf_counter_ns() - start)
            if r:
                continue
            ok = [same_form(item["result"][k]) == same_form(result[k])
                  for k in ("province", "district", "ward")]
            for i in range(3):
                field_ok[i] += ok[i]
            if not all(ok):
                failures.append((item["text"], item["result"], result))

    n, total = len(times), len(data) * 3
    times.sort()
    correct = sum(field_ok)
    print(f"build {build_ms:.1f} ms")
    print(f"score {correct}/{total} = {correct / total * 10:.2f}/10  "
          f"(province {field_ok[0]}, district {field_ok[1]}, ward {field_ok[2]} of {len(data)})")
    print(f"latency mean {sum(times) / n / 1e6:.3f} ms  p50 {times[n // 2] / 1e6:.3f}  "
          f"p95 {times[int(n * 0.95)] / 1e6:.3f}  max {times[-1] / 1e6:.3f} ms  ({n} calls)")
    if "-v" in sys.argv:
        for text, expected, got in failures:
            print(f"\n{text!r}\n  expected {expected}\n  got      {got}")


if __name__ == "__main__":
    main()
