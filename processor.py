"""TXT 字段格式处理核心逻辑。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


SEPARATOR = "----"


@dataclass
class ProcessResult:
    output_path: Path
    total_lines: int
    success_lines: int
    skipped_lines: int


class ProcessError(ValueError):
    """用户可理解的处理错误。"""


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
