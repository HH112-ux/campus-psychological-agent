"""文档事实校验：README 里的可验证事实与代码 / 实测结果脱节时让 CI 直接失败。

用法（backend/ 目录）：
    .venv/bin/python3.12 scripts/check_docs_facts.py              # 全量校验（会实跑一次 pytest）
    .venv/bin/python3.12 scripts/check_docs_facts.py --skip-tests # 只校验依赖声明与命令路径

校验项：
1. README.md / backend/README.md 声明的 pytest 基线（passed、skipped、总数）与实跑结果一致；
2. README 声称「使用」的第三方库必须在 requirements*.txt / pyproject.toml 中真实声明；
   反向：声称「未使用」的库不得出现在依赖清单里；
3. README 命令块中引用的路径与模块（`-m` 模块、uvicorn 入口、`pip -r`、`cp`、`find`）真实存在；
4. README 中的相对链接目标真实存在。

口径说明：
- 实跑 pytest 时固定清空 REDIS_TEST_URL，使文档里「1 skipped（真 Redis 集成）」的口径可复现；
- MongoDB 不可达会导致大批集成用例被 skip，此时直接报基础设施错误，而不是拿错误数字比对；
- 依赖库清单是显式登记表（KNOWN_LIBRARIES），只校验登记过的库，避免把 MongoDB、微信小程序
  等非 pip 依赖误判为缺失；README 新增技术栈声明时在此登记对应的 distribution 名。
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
DOCS = (REPO_ROOT / "README.md", BACKEND_DIR / "README.md")

# 文档里的测试基线写法：`1114 passed, 1 skipped（共 1115 项）`
BASELINE_RE = re.compile(
    r"(?P<passed>\d+)\s+passed,\s*(?P<skipped>\d+)\s+skipped\s*[（(]共\s*(?P<total>\d+)\s*项"
)

SHELL_LANGS = {"bash", "sh", "shell", "zsh", "console"}

# 否定语境：命中即视为「声明未使用」，反过来要求依赖清单里不得出现
NEGATION_CUES = (
    "未使用",
    "不使用",
    "未引入",
    "不引入",
    "不依赖",
    "未依赖",
    "没有使用",
    "未包含",
    "不含",
)

# 文档可能声称使用的第三方库：distribution 名 -> 文档中的提及写法
KNOWN_LIBRARIES = {
    "fastapi": r"\bFastAPI\b",
    "uvicorn": r"\buvicorn\b",
    "pydantic": r"\bPydantic\b",
    "pydantic-settings": r"pydantic[- ]settings",
    "motor": r"\bmotor\b",
    "redis": r"\bRedis\b",
    "httpx": r"\bhttpx\b",
    "pyjwt": r"\bPyJWT\b",
    "cryptography": r"\bcryptography\b",
    "python-multipart": r"python-multipart",
    "pytest": r"\bpytest\b",
    "ruff": r"\bruff\b",
    "langchain": r"\bLangChain\b",
    "langgraph": r"\bLangGraph\b",
}

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _normalize(name: str) -> str:
    """PEP 503 归一化：`PyJWT` / `py_jwt` 视为同一个包。"""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def _requirement_name(spec: str) -> str:
    return re.split(r"[<>=!~\[;\s]", spec.strip(), maxsplit=1)[0]


def _collect_requirements(path: Path, declared: dict[str, str], seen: set[Path]) -> None:
    path = path.resolve()
    if path in seen or not path.is_file():
        return
    seen.add(path)
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith(("-r ", "--requirement ")):
            _collect_requirements(path.parent / line.split(None, 1)[1], declared, seen)
            continue
        if line.startswith("-"):  # --index-url 等选项
            continue
        name = _requirement_name(line)
        if name:
            declared.setdefault(_normalize(name), path.name)


def declared_dependencies() -> dict[str, str]:
    """返回 distribution 名 -> 声明文件，覆盖 requirements*.txt（含 -r 递归）与 pyproject。"""
    declared: dict[str, str] = {}
    seen: set[Path] = set()
    for name in ("requirements.txt", "requirements-dev.txt"):
        _collect_requirements(BACKEND_DIR / name, declared, seen)
    pyproject = BACKEND_DIR / "pyproject.toml"
    if pyproject.is_file():
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        for spec in data.get("project", {}).get("dependencies", []):
            name = _requirement_name(spec)
            if name:
                declared.setdefault(_normalize(name), "pyproject.toml")
    return declared


def check_library_claims(declared: dict[str, str]) -> tuple[int, list[str]]:
    checked = 0
    failures: list[str] = []
    for doc in DOCS:
        text = doc.read_text(encoding="utf-8")
        for dist, pattern in KNOWN_LIBRARIES.items():
            for match in re.finditer(pattern, text):
                checked += 1
                line_no = text.count("\n", 0, match.start()) + 1
                context = text[max(0, match.start() - 16) : match.end() + 16]
                negated = any(cue in context for cue in NEGATION_CUES)
                installed = dist in declared
                if negated and installed:
                    failures.append(
                        f"{_rel(doc)}:{line_no} 声称未使用 {match.group(0)}，"
                        f"但 {declared[dist]} 声明了该依赖（{dist}）"
                    )
                elif not negated and not installed:
                    failures.append(
                        f"{_rel(doc)}:{line_no} 声称使用 {match.group(0)}，"
                        f"但 requirements*.txt / pyproject.toml 均未声明（{dist}）"
                    )
    return checked, failures


def _parse_pytest_summary(output: str) -> dict[str, int] | None:
    for line in reversed([item.strip() for item in output.splitlines() if item.strip()][-5:]):
        counts: dict[str, int] = {}
        for match in re.finditer(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed)", line):
            key = "error" if match.group(2).startswith("error") else match.group(2)
            counts[key] = counts.get(key, 0) + int(match.group(1))
        if "passed" in counts:
            return counts
    return None


def run_pytest() -> tuple[dict[str, int] | None, str]:
    """实跑 pytest，返回 (计数, 错误说明)。计数为 None 表示无法得到可信结果。"""
    env = os.environ.copy()
    env.pop("REDIS_TEST_URL", None)  # 固定文档口径：真 Redis 集成用例应 skip
    env.pop("PYTEST_ADDOPTS", None)
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=BACKEND_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=1800,
        )
    except subprocess.TimeoutExpired:
        return None, "pytest 运行超时（1800s）"

    output = f"{proc.stdout}\n{proc.stderr}"
    if "MongoDB 未启动" in output or "MongoDB 未连接" in output:
        return None, "本地 MongoDB 不可达，集成用例被批量跳过，拒绝用错误数字比对文档基线"

    counts = _parse_pytest_summary(output)
    if counts is None:
        return None, f"未能从 pytest 输出解析结果（退出码 {proc.returncode}）"
    if proc.returncode != 0:
        return counts, f"pytest 未通过（退出码 {proc.returncode}）"
    return counts, ""


def check_test_baseline(counts: dict[str, int]) -> tuple[int, list[str]]:
    actual = {
        "passed": counts.get("passed", 0),
        "skipped": counts.get("skipped", 0),
        "total": sum(counts.values()),
    }
    checked = 0
    failures: list[str] = []
    for doc in DOCS:
        text = doc.read_text(encoding="utf-8")
        matches = list(BASELINE_RE.finditer(text))
        if not matches:
            failures.append(
                f"{_rel(doc)} 未找到 pytest 基线声明（期望写法：`N passed, M skipped（共 T 项）`）"
            )
            continue
        for match in matches:
            checked += 1
            line_no = text.count("\n", 0, match.start()) + 1
            declared = {
                "passed": int(match.group("passed")),
                "skipped": int(match.group("skipped")),
                "total": int(match.group("total")),
            }
            if declared["passed"] + declared["skipped"] != declared["total"]:
                failures.append(
                    f"{_rel(doc)}:{line_no} 基线自相矛盾：{declared['passed']} passed + "
                    f"{declared['skipped']} skipped ≠ 共 {declared['total']} 项"
                )
            diffs = [
                f"{key} 文档 {declared[key]} / 实际 {actual[key]}"
                for key in ("passed", "skipped", "total")
                if declared[key] != actual[key]
            ]
            if diffs:
                failures.append(f"{_rel(doc)}:{line_no} 测试基线不一致：" + "；".join(diffs))
    return checked, failures


def _is_dynamic(ref: str) -> bool:
    """含变量 / 通配 / 选项的引用无法静态校验，跳过。"""
    return ref.startswith(("$", "~", "-")) or "$" in ref or "*" in ref


def _resolve(ref: str, cwd: Path) -> Path | None:
    """按当前目录、backend/、仓库根依次尝试解析相对路径（README 常混用不同起点）。"""
    ref = ref.strip().strip("'\"")
    path = Path(ref)
    if path.is_absolute():
        return path if path.exists() else None
    for base in (cwd, BACKEND_DIR, REPO_ROOT):
        candidate = base / path
        if candidate.exists():
            return candidate
    return None


def _resolve_module(module: str, cwd: Path) -> Path | None:
    relative = Path(module.replace(".", "/"))
    for candidate in (relative.with_suffix(".py"), relative / "__init__.py"):
        if _resolve(candidate.as_posix(), cwd) is not None:
            return candidate
    return None


def iter_shell_commands(doc: Path):
    """产出 README 中原生 shell 代码块里的单行命令（忽略注释行，去掉行内注释）。"""
    in_block = False
    for line_no, raw in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        while line.startswith(">"):
            line = line[1:].strip()
        if line.startswith("```"):
            if in_block:
                in_block = False
            else:
                in_block = line[3:].strip().lower() in SHELL_LANGS
            continue
        if not in_block or not line or line.startswith("#"):
            continue
        command = re.sub(r"\s+#.*$", "", line).strip()
        if command:
            yield line_no, command


def check_commands(doc: Path) -> tuple[int, list[str]]:
    checked = 0
    failures: list[str] = []
    cwd = REPO_ROOT

    for line_no, command in iter_shell_commands(doc):
        cd_match = re.fullmatch(r"cd\s+(\S+)", command)
        if cd_match:
            ref = cd_match.group(1)
            if _is_dynamic(ref):
                continue
            checked += 1
            target = _resolve(ref, cwd)
            if target is None:
                failures.append(f"{_rel(doc)}:{line_no} cd 目标不存在：{ref}")
            else:
                cwd = target
            continue

        for match in re.finditer(
            r"(?:^|\s)(?:\S*/)?python(?:3(?:\.\d+)*)?\s+-m\s+([A-Za-z_][\w.]*)", command
        ):
            module = match.group(1)
            if module in {"pip", "venv", "pytest"}:
                continue
            checked += 1
            if _resolve_module(module, cwd) is None:
                expected = module.replace(".", "/")
                failures.append(
                    f"{_rel(doc)}:{line_no} python -m 模块不存在：{module}（期望 {expected}.py）"
                )

        uvicorn_match = re.search(r"(?:^|\s)(?:\S*/)?uvicorn\s+([A-Za-z_][\w.]*):", command)
        if uvicorn_match:
            checked += 1
            module = uvicorn_match.group(1)
            if _resolve_module(module, cwd) is None:
                failures.append(f"{_rel(doc)}:{line_no} uvicorn 入口模块不存在：{module}")

        if "pip install" in command:
            for req in re.finditer(r"(?:^|\s)(?:-r|--requirement)\s+(\S+)", command):
                ref = req.group(1)
                if _is_dynamic(ref):
                    continue
                checked += 1
                if _resolve(ref, cwd) is None:
                    failures.append(f"{_rel(doc)}:{line_no} 依赖文件不存在：{ref}")

        cp_match = re.match(r"cp\s+(\S+)\s+(\S+)", command)
        if cp_match and not _is_dynamic(cp_match.group(1)):
            checked += 1
            if _resolve(cp_match.group(1), cwd) is None:
                failures.append(f"{_rel(doc)}:{line_no} cp 源文件不存在：{cp_match.group(1)}")

        find_match = re.match(r"find\s+(\S+)", command)
        if find_match and not _is_dynamic(find_match.group(1)):
            checked += 1
            if _resolve(find_match.group(1), cwd) is None:
                failures.append(f"{_rel(doc)}:{line_no} find 目录不存在：{find_match.group(1)}")

    return checked, failures


def check_links(doc: Path) -> tuple[int, list[str]]:
    checked = 0
    failures: list[str] = []
    for line_no, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
        for match in LINK_RE.finditer(line):
            target = match.group(1)
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            ref = unquote(target.split("#", 1)[0])
            if not ref:
                continue
            checked += 1
            if _resolve(ref, doc.parent) is None:
                failures.append(f"{_rel(doc)}:{line_no} 相对链接目标不存在：{target}")
    return checked, failures


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 README 可验证事实与代码 / 实测是否一致")
    parser.add_argument("--skip-tests", action="store_true", help="跳过实跑 pytest")
    args = parser.parse_args()

    failures: list[str] = []

    declared = declared_dependencies()
    checks, found = check_library_claims(declared)
    failures.extend(found)
    print(f"[1/4] 依赖声明：校验 {checks} 处库提及，失败 {len(found)} 项")

    if args.skip_tests:
        print("[2/4] 测试基线：已按 --skip-tests 跳过")
    else:
        counts, error = run_pytest()
        if counts is None:
            failures.append(f"测试基线：{error}")
            print(f"[2/4] 测试基线：无法校验（{error}）")
        else:
            checks, found = check_test_baseline(counts)
            if error:
                found = [f"测试基线：{error}", *found]
            failures.extend(found)
            print(
                f"[2/4] 测试基线：实际 {counts.get('passed', 0)} passed / "
                f"{counts.get('skipped', 0)} skipped / 共 {sum(counts.values())} 项，"
                f"校验 {checks} 处声明，失败 {len(found)} 项"
            )

    checks = 0
    found = []
    for doc in DOCS:
        part_checks, part_failures = check_commands(doc)
        checks += part_checks
        found.extend(part_failures)
    failures.extend(found)
    print(f"[3/4] 命令与路径：校验 {checks} 处引用，失败 {len(found)} 项")

    checks = 0
    found = []
    for doc in DOCS:
        part_checks, part_failures = check_links(doc)
        checks += part_checks
        found.extend(part_failures)
    failures.extend(found)
    print(f"[4/4] 相对链接：校验 {checks} 处链接，失败 {len(found)} 项")

    if failures:
        sys.stdout.flush()
        print("\n文档事实校验未通过：", file=sys.stderr)
        for failure in failures:
            print(f"[FAIL] {failure}", file=sys.stderr)
        return 1
    print("\n文档事实校验通过：README 事实与代码 / 实测一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
