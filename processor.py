"""TXT 字段格式处理核心逻辑。"""

from __future__ import annotations

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
