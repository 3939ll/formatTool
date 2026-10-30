"""TXT 字段格式处理核心逻辑。"""

from __future__ import annotations

import os
import random
import string
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator


SEPARATOR = "----"


@dataclass
class ProcessResult:
    output_path: Path
    total_lines: int
    success_lines: int
    skipped_lines: int


@dataclass
class MergeResult:
    merged_path: Path
    merged_count: int
    remainder_path: Path | None
    remainder_count: int
    remainder_side: str | None  # "first" | "second" | None


@dataclass
class ExtractResult:
    output_path: Path
    requested: int
    extracted: int
    removed_empty: int
    source_exhausted: bool


@dataclass
class DedupResult:
    same_path: Path
    same_count: int
    unique_path: Path
    unique_count: int


class ProcessError(ValueError):
    """用户可理解的处理错误。"""


def get_output_dir() -> Path:
    """exe 同目录；源码运行则用当前工作目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def detect_encoding(path: Path) -> str:
    # 只抽样读取，避免大文件整文件读入内存导致卡住
    with path.open("rb") as fin:
        raw = fin.read(256 * 1024)
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            raw.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    raise ProcessError("无法识别文件编码，请确认文件为 UTF-8 或 GBK。")


def _require_txt(path: Path, label: str) -> None:
    if not path.is_file():
        raise ProcessError(f"请先选择有效的{label} txt 文件。")
    if path.suffix.lower() != ".txt":
        raise ProcessError(f"{label}仅支持 .txt 文件。")


def iter_nonempty_lines(path: Path) -> Iterator[str]:
    encoding = detect_encoding(path)
    with path.open("r", encoding=encoding, errors="strict", newline="") as fin:
        for line in fin:
            text = line.rstrip("\r\n")
            if text.strip():
                yield text


def validate_mapping(segment_count: int, mapping: list[int]) -> list[int]:
    if segment_count < 1:
        raise ProcessError("总段数必须大于等于 1。")
    if len(mapping) != segment_count:
        raise ProcessError(f"映射数量应为 {segment_count}，当前为 {len(mapping)}。")

    resolved: list[int] = []
    for idx, value in enumerate(mapping, start=1):
        if value < 0:
            raise ProcessError(f"第 {idx} 个映射不能为负数。")
        if value > segment_count:
            raise ProcessError(
                f"第 {idx} 个映射值 {value} 超出范围，有效范围为 0~{segment_count}。"
            )
        if value > 0:
            resolved.append(value)

    if not resolved:
        raise ProcessError("映射全为 0，至少需要保留 1 段。")
    return resolved


def build_output_path(source: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return source.with_name(f"{source.stem}_formatted_{stamp}{source.suffix}")


def process_file(
    source: Path,
    segment_count: int,
    mapping: list[int],
    progress_callback=None,
) -> ProcessResult:
    if not source.is_file():
        raise ProcessError("请先选择有效的 txt 文件。")
    if source.suffix.lower() != ".txt":
        raise ProcessError("仅支持 .txt 文件。")

    active_mapping = validate_mapping(segment_count, mapping)
    encoding = detect_encoding(source)
    output_path = build_output_path(source)

    # 先快速统计行数，便于进度条与上万行文件反馈
    with source.open("r", encoding=encoding, errors="strict", newline="") as fin:
        line_total = sum(1 for _ in fin)

    processed = 0
    success_lines = 0
    skipped_lines = 0
    report_every = 200 if line_total <= 5000 else 1000

    with (
        source.open("r", encoding=encoding, errors="strict", newline="") as fin,
        output_path.open("w", encoding="utf-8", newline="\n") as fout,
    ):
        for line in fin:
            processed += 1
            text = line.rstrip("\r\n")

            if not text.strip():
                skipped_lines += 1
            else:
                parts = text.split(SEPARATOR)
                if len(parts) != segment_count:
                    skipped_lines += 1
                else:
                    out_parts = [parts[i - 1] for i in active_mapping]
                    fout.write(SEPARATOR.join(out_parts))
                    fout.write("\n")
                    success_lines += 1

            if progress_callback and (
                processed == 1
                or processed % report_every == 0
                or processed == line_total
            ):
                progress_callback(processed, line_total, success_lines, skipped_lines)

    return ProcessResult(
        output_path=output_path,
        total_lines=line_total,
        success_lines=success_lines,
        skipped_lines=skipped_lines,
    )


def merge_files(
    first: Path,
    second: Path,
    output_dir: Path | None = None,
    progress_callback=None,
) -> MergeResult:
    """按非空行一一对应拼接：先文件 + ---- + 后文件。少的一侧用完即停。"""
    _require_txt(first, "先上传")
    _require_txt(second, "后上传")

    out_dir = output_dir or get_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    merged_path = out_dir / f"merged_{stamp}.txt"

    first_iter = iter_nonempty_lines(first)
    second_iter = iter_nonempty_lines(second)
    merged_count = 0
    remainder_lines: list[str] = []
    remainder_side: str | None = None
    remainder_stem = ""
    report_every = 500

    with merged_path.open("w", encoding="utf-8", newline="\n") as fout:
        while True:
            try:
                left = next(first_iter)
            except StopIteration:
                remainder_lines = list(second_iter)
                if remainder_lines:
                    remainder_side = "second"
                    remainder_stem = second.stem
                break

            try:
                right = next(second_iter)
            except StopIteration:
                remainder_lines = [left, *first_iter]
                remainder_side = "first"
                remainder_stem = first.stem
                break

            fout.write(left)
            fout.write(SEPARATOR)
            fout.write(right)
            fout.write("\n")
            merged_count += 1

            if progress_callback and (
                merged_count == 1 or merged_count % report_every == 0
            ):
                progress_callback(merged_count)

    if progress_callback:
        progress_callback(merged_count)

    if merged_count == 0 and not remainder_lines:
        # 两边都没有有效行：删掉空的合并文件，避免留下无意义空文件
        merged_path.unlink(missing_ok=True)
        raise ProcessError("两个文件都没有可用于拼接的非空行。")

    if merged_count == 0:
        merged_path.unlink(missing_ok=True)
        raise ProcessError("没有成功拼接的行（至少一侧没有非空行）。")

    remainder_path: Path | None = None
    remainder_count = len(remainder_lines)
    if remainder_count > 0:
        # 使用转义，避免 Windows 下源码编码误读导致文件名乱码
        remainder_path = out_dir / f"\u5269\u4f59_{remainder_stem}_{stamp}.txt"
        with remainder_path.open("w", encoding="utf-8", newline="\n") as fout:
            for line in remainder_lines:
                fout.write(line)
                fout.write("\n")

    return MergeResult(
        merged_path=merged_path,
        merged_count=merged_count,
        remainder_path=remainder_path,
        remainder_count=remainder_count,
        remainder_side=remainder_side,
    )


_ALIAS_RAND_CHARS = string.ascii_lowercase + string.digits
_ALIAS_LEN_MAX = 128


def parse_alias_length(low_raw: str, high_raw: str) -> tuple[int, int]:
    """解析随机位数：都空=4~6；只填一边=固定该位数；左>右则对调；0 不允许。"""
    left = low_raw.strip()
    right = high_raw.strip()

    def _one(text: str, label: str) -> int:
        if not text.isdigit():
            raise ProcessError(f"随机位数{label}必须是正整数。")
        value = int(text)
        if value < 1:
            raise ProcessError("随机位数不能为 0。")
        if value > _ALIAS_LEN_MAX:
            raise ProcessError(f"随机位数不能超过 {_ALIAS_LEN_MAX}。")
        return value

    if not left and not right:
        return 4, 6
    if left and not right:
        n = _one(left, "左侧")
        return n, n
    if right and not left:
        n = _one(right, "右侧")
        return n, n

    lo = _one(left, "左侧")
    hi = _one(right, "右侧")
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


def randomize_email_local(
    email: str,
    min_len: int = 4,
    max_len: int = 6,
    specified: str = "",
) -> str | None:
    """在 @ 前插入 +、可选指定串、再接随机串（首字母必为小写，其余小写+数字）。"""
    if "@" not in email:
        return None
    local, domain = email.split("@", 1)
    if not local or not domain:
        return None
    n = random.randint(min_len, max_len)
    first = random.choice(string.ascii_lowercase)
    rest = "".join(random.choices(_ALIAS_RAND_CHARS, k=n - 1)) if n > 1 else ""
    return f"{local}+{specified}{first}{rest}@{domain}"


def process_alias_file(
    source: Path,
    output_dir: Path | None = None,
    progress_callback=None,
    min_len: int = 4,
    max_len: int = 6,
    specified: str = "",
) -> ProcessResult:
    """对每行第 1 段邮箱做别名随机，其余段原样保留。"""
    _require_txt(source, "上传")
    if min_len < 1 or max_len < 1 or min_len > max_len:
        raise ProcessError("随机位数范围无效。")
    encoding = detect_encoding(source)
    out_dir = output_dir or get_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = out_dir / f"alias_{stamp}.txt"

    with source.open("r", encoding=encoding, errors="strict", newline="") as fin:
        line_total = sum(1 for _ in fin)

    processed = 0
    success_lines = 0
    skipped_lines = 0
    report_every = 200 if line_total <= 5000 else 1000

    with (
        source.open("r", encoding=encoding, errors="strict", newline="") as fin,
        output_path.open("w", encoding="utf-8", newline="\n") as fout,
    ):
        for line in fin:
            processed += 1
            text = line.rstrip("\r\n")

            if not text.strip():
                skipped_lines += 1
            else:
                parts = text.split(SEPARATOR)
                new_email = randomize_email_local(
                    parts[0], min_len, max_len, specified
                )
                if new_email is None:
                    skipped_lines += 1
                else:
                    parts[0] = new_email
                    fout.write(SEPARATOR.join(parts))
                    fout.write("\n")
                    success_lines += 1

            if progress_callback and (
                processed == 1
                or processed % report_every == 0
                or processed == line_total
            ):
                progress_callback(processed, line_total, success_lines, skipped_lines)

    if progress_callback:
        progress_callback(processed, line_total, success_lines, skipped_lines)

    if success_lines == 0:
        output_path.unlink(missing_ok=True)
        raise ProcessError("没有成功处理的行（第 1 段需为含 @ 的邮箱）。")

    return ProcessResult(
        output_path=output_path,
        total_lines=line_total,
        success_lines=success_lines,
        skipped_lines=skipped_lines,
    )


def _pop_first_line(source: Path, encoding: str) -> str | None:
    """删除并返回源文件第一行（不含换行）。文件已空返回 None。每步落盘，防中断丢数据。"""
    tmp = source.with_name(source.name + ".extract_tmp")
    # utf-8-sig 写入会反复加 BOM，重写剩余内容时改用 utf-8
    write_encoding = "utf-8" if encoding.lower().startswith("utf-8") else encoding
    try:
        with source.open("r", encoding=encoding, errors="strict", newline="") as fin:
            first_raw = fin.readline()
            if first_raw == "":
                return None
            first = first_raw.rstrip("\r\n")
            with tmp.open("w", encoding=write_encoding, newline="") as fout:
                while True:
                    chunk = fin.read(1024 * 1024)
                    if not chunk:
                        break
                    fout.write(chunk)
                fout.flush()
                os.fsync(fout.fileno())
        os.replace(tmp, source)
        return first
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def extract_lines(
    source: Path,
    count: int,
    output_dir: Path | None = None,
    progress_callback=None,
) -> ExtractResult:
    """从开头提取 N 条非空行：每提一行立刻写入输出并从原文件删除。"""
    _require_txt(source, "上传")
    if count < 1:
        raise ProcessError("提取个数必须大于等于 1。")

    encoding = detect_encoding(source)
    out_dir = output_dir or get_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # 提取N行_时间戳.txt
    output_path = out_dir / f"\u63d0\u53d6{count}\u884c_{stamp}.txt"

    extracted = 0
    removed_empty = 0
    source_exhausted = False

    with output_path.open("w", encoding="utf-8", newline="\n") as fout:
        while extracted < count:
            line = _pop_first_line(source, encoding)
            if line is None:
                source_exhausted = True
                break

            if not line.strip():
                removed_empty += 1
                if progress_callback:
                    progress_callback(extracted, count, removed_empty)
                continue

            fout.write(line)
            fout.write("\n")
            fout.flush()
            os.fsync(fout.fileno())
            extracted += 1

            if progress_callback:
                progress_callback(extracted, count, removed_empty)

    if extracted == 0:
        output_path.unlink(missing_ok=True)
        raise ProcessError("没有可提取的有效行。")

    return ExtractResult(
        output_path=output_path,
        requested=count,
        extracted=extracted,
        removed_empty=removed_empty,
        source_exhausted=source_exhausted,
    )


def _load_line_set(path: Path, progress_callback=None, stage: str = "") -> set[str]:
    """读入非空行集合（整行内容哈希），忽略空行。"""
    encoding = detect_encoding(path)
    lines: set[str] = set()
    n = 0
    report_every = 5000
    with path.open("r", encoding=encoding, errors="strict", newline="") as fin:
        for line in fin:
            text = line.rstrip("\r\n")
            if text.strip():
                lines.add(text)
            n += 1
            if progress_callback and (n == 1 or n % report_every == 0):
                progress_callback(stage, n, len(lines))
    if progress_callback:
        progress_callback(stage, n, len(lines))
    return lines


def _write_line_set(path: Path, lines: set[str]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fout:
        fout.writelines(f"{line}\n" for line in lines)


def dedupe_files(
    first: Path,
    second: Path,
    output_dir: Path | None = None,
    progress_callback=None,
) -> DedupResult:
    """两文件整行集合对比：写出交集与对称差（各去重一次）。顺序不保证。"""
    _require_txt(first, "文件1")
    _require_txt(second, "文件2")

    out_dir = output_dir or get_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # 相同行_时间戳.txt / 独有行_时间戳.txt
    same_path = out_dir / f"\u76f8\u540c\u884c_{stamp}.txt"
    unique_path = out_dir / f"\u72ec\u6709\u884c_{stamp}.txt"

    set_a = _load_line_set(first, progress_callback, "read1")
    set_b = _load_line_set(second, progress_callback, "read2")

    if not set_a and not set_b:
        raise ProcessError("两个文件都没有可用于对比的非空行。")

    if progress_callback:
        progress_callback("compare", 0, 0)

    same = set_a & set_b
    unique = set_a ^ set_b

    if progress_callback:
        progress_callback("write", len(same), len(unique))

    _write_line_set(same_path, same)
    _write_line_set(unique_path, unique)

    if progress_callback:
        progress_callback("done", len(same), len(unique))

    return DedupResult(
        same_path=same_path,
        same_count=len(same),
        unique_path=unique_path,
        unique_count=len(unique),
    )
