"""格式处理工具 - 深色现代界面。"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from processor import (
    ProcessError,
    dedupe_files,
    extract_lines,
    get_output_dir,
    merge_files,
    parse_alias_length,
    process_alias_file,
    process_file,
    validate_mapping,
)


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


COLORS = {
    "bg": "#0b1220",
    "panel": "#121a2b",
    "panel_alt": "#182338",
    "border": "#2a3a55",
    "text": "#e8eefc",
    "muted": "#93a4c3",
    "accent": "#2dd4bf",
    "accent_hover": "#14b8a6",
    "danger": "#fb7185",
    "ok": "#34d399",
    "input": "#0f172a",
}


class SlidingSegment(ctk.CTkFrame):
    """一体轨道 + 滑动主按钮；选中块与「选择文件」同款（青色底+深色字）。"""

    def __init__(self, master, values: list[str], command=None, **kwargs):
        self._pad = 3
        self._seg_w = 88
        self._btn_h = 40
        self._track_h = self._btn_h + self._pad * 2
        super().__init__(
            master,
            fg_color=COLORS["panel_alt"],
            corner_radius=12,
            border_width=1,
            border_color=COLORS["border"],
            height=self._track_h,
            **kwargs,
        )
        self.values = values
        self.command = command
        self._index = 0
        self._animating = False
        total_w = self._pad * 2 + self._seg_w * len(values)
        self.configure(width=total_w)
        self.pack_propagate(False)
        self.grid_propagate(False)

        # 底层：未选中文字（可点击）
        self._labels: list[ctk.CTkLabel] = []
        for i, text in enumerate(values):
            lab = ctk.CTkLabel(
                self,
                text=text,
                width=self._seg_w,
                height=self._btn_h,
                fg_color="transparent",
                font=ctk.CTkFont(family="Microsoft YaHei UI", size=13, weight="bold"),
                text_color=COLORS["text"],
                cursor="hand2",
            )
            lab.place(x=self._pad + i * self._seg_w, y=self._pad)
            lab.bind("<Button-1>", lambda _e, idx=i: self._on_click(idx))
            self._labels.append(lab)

        # 上层滑块：直接用 CTkButton，样式与「选择文件」一致（避免 Frame 被盖住看不见）
        self._pill = ctk.CTkButton(
            self,
            text=values[0],
            width=self._seg_w,
            height=self._btn_h,
            corner_radius=10,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color="#042f2e",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13, weight="bold"),
            command=lambda: None,
        )
        self._pill.place(x=self._pad, y=self._pad)
        self._sync_ghosts()

    def get(self) -> str:
        return self.values[self._index]

    def set(self, value: str, animate: bool = True) -> None:
        if value not in self.values:
            return
        idx = self.values.index(value)
        if idx == self._index and not self._animating:
            self._pill.configure(text=value)
            self._sync_ghosts()
            return
        self._move_to(idx, animate=animate)

    def _on_click(self, idx: int) -> None:
        if idx == self._index or self._animating:
            return
        self._move_to(idx, animate=True)
        if self.command:
            self.command(self.values[idx])

    def _pill_x(self, idx: int) -> int:
        return self._pad + idx * self._seg_w

    def _sync_ghosts(self) -> None:
        for i, lab in enumerate(self._labels):
            # 选中位由青色按钮盖住，底层字藏掉避免重影
            lab.configure(text_color=COLORS["panel_alt"] if i == self._index else COLORS["text"])

    def _move_to(self, idx: int, animate: bool = False) -> None:
        # 直接切换选中，不做滑动动画
        self._index = idx
        self._animating = False
        self._pill.configure(text=self.values[idx])
        self._pill.place(x=self._pill_x(idx), y=self._pad)
        self._sync_ghosts()


class FormatToolApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("TXT 格式处理工具")
        self.geometry("980x760")
        self.minsize(900, 680)
        self.configure(fg_color=COLORS["bg"])

        self.source_path: Path | None = None
        self.merge_first_path: Path | None = None
        self.merge_second_path: Path | None = None
        self.alias_path: Path | None = None
        self.extract_path: Path | None = None
        self.dedupe_first_path: Path | None = None
        self.dedupe_second_path: Path | None = None
        self.mapping_entries: list[ctk.CTkEntry] = []
        self.index_labels: list[ctk.CTkLabel] = []
        self._busy = False
        self._current_tab = "map"
        self._process_btn_width = 180
        self._tab_labels = {
            "map": "格式映射",
            "merge": "格式添加",
            "alias": "别名随机",
            "extract": "提取数据",
            "dedupe": "文件去重",
        }
        self._tab_by_label = {v: k for k, v in self._tab_labels.items()}
        self._tab_subtitles = {
            "map": "按自定义映射重组 ---- 分隔字段",
            "merge": "两个 txt 按行拼接，先上传的在前",
            "alias": "第 1 段邮箱 @ 前加 +指定串+随机字母数字，其余段原样",
            "extract": "从开头提取 N 条有效行，逐行写入输出并从原文件删除",
            "dedupe": "两文件整行对比：相同行一份，两边独有整合一份",
        }

        self._build_ui()

    def _build_ui(self) -> None:
        root = ctk.CTkFrame(self, fg_color=COLORS["bg"])
        root.pack(fill="both", expand=True, padx=24, pady=18)

        header = ctk.CTkFrame(root, fg_color="transparent")
        header.pack(fill="x", pady=(0, 12))

        title = ctk.CTkLabel(
            header,
            text="TXT 格式处理工具",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=20, weight="bold"),
            text_color=COLORS["text"],
        )
        title.pack(side="left")

        self.tab_seg = SlidingSegment(
            header,
            values=["格式映射", "格式添加", "别名随机", "提取数据", "文件去重"],
            command=self._on_tab_seg,
        )
        self.tab_seg.pack(side="right")
        self.tab_seg.set("格式映射", animate=False)

        self.subtitle = ctk.CTkLabel(
            root,
            text=self._tab_subtitles["map"],
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
            text_color=COLORS["muted"],
        )
        self.subtitle.pack(anchor="w", pady=(0, 12))

        self.page_host = ctk.CTkFrame(root, fg_color="transparent")
        self.page_host.pack(fill="both", expand=True)

        self.map_page = ctk.CTkFrame(self.page_host, fg_color="transparent")
        self.merge_page = ctk.CTkFrame(self.page_host, fg_color="transparent")
        self.alias_page = ctk.CTkFrame(self.page_host, fg_color="transparent")
        self.extract_page = ctk.CTkFrame(self.page_host, fg_color="transparent")
        self.dedupe_page = ctk.CTkFrame(self.page_host, fg_color="transparent")

        self._build_map_page(self.map_page)
        self._build_merge_page(self.merge_page)
        self._build_alias_page(self.alias_page)
        self._build_extract_page(self.extract_page)
        self._build_dedupe_page(self.dedupe_page)
        self.switch_tab("map", animate_tab=False)

    def _on_tab_seg(self, value: str) -> None:
        name = self._tab_by_label.get(value, "map")
        if self._busy and name != self._current_tab:
            messagebox.showinfo("请稍候", "当前正在处理，请等待完成后再切换。")
            self.tab_seg.set(self._tab_labels[self._current_tab], animate=False)
            return
        self.switch_tab(name, from_segment=True)

    def switch_tab(self, name: str, from_segment: bool = False, animate_tab: bool = True) -> None:
        if self._busy and name != self._current_tab:
            messagebox.showinfo("请稍候", "当前正在处理，请等待完成后再切换。")
            self.tab_seg.set(self._tab_labels[self._current_tab], animate=False)
            return
        self._current_tab = name
        if not from_segment:
            self.tab_seg.set(self._tab_labels[name], animate=animate_tab)
        self.map_page.pack_forget()
        self.merge_page.pack_forget()
        self.alias_page.pack_forget()
        self.extract_page.pack_forget()
        self.dedupe_page.pack_forget()
        self.subtitle.configure(text=self._tab_subtitles[name])
        page = {
            "map": self.map_page,
            "merge": self.merge_page,
            "alias": self.alias_page,
            "extract": self.extract_page,
            "dedupe": self.dedupe_page,
        }[name]
        page.pack(fill="both", expand=True)

    # ---------- 格式映射页 ----------
    def _build_map_page(self, root: ctk.CTkFrame) -> None:
        file_card = ctk.CTkFrame(
            root, fg_color=COLORS["panel"], corner_radius=16, border_width=1, border_color=COLORS["border"]
        )
        file_card.pack(fill="x", pady=(0, 16))

        file_inner = ctk.CTkFrame(file_card, fg_color="transparent")
        file_inner.pack(fill="x", padx=18, pady=16)

        ctk.CTkLabel(
            file_inner,
            text="1. 选择 TXT 文件",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=15, weight="bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w")

        row = ctk.CTkFrame(file_inner, fg_color="transparent")
        row.pack(fill="x", pady=(12, 0))

        self.file_label = ctk.CTkLabel(
            row,
            text="尚未选择文件",
            anchor="w",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13),
            text_color=COLORS["muted"],
            fg_color=COLORS["input"],
            corner_radius=10,
            height=40,
        )
        self.file_label.pack(side="left", fill="x", expand=True, padx=(0, 12))

        ctk.CTkButton(
            row,
            text="选择文件",
            width=120,
            height=40,
            corner_radius=10,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color="#042f2e",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13, weight="bold"),
            command=self.choose_file,
        ).pack(side="right")

        seg_card = ctk.CTkFrame(
            root, fg_color=COLORS["panel"], corner_radius=16, border_width=1, border_color=COLORS["border"]
        )
        seg_card.pack(fill="x", pady=(0, 16))

        seg_inner = ctk.CTkFrame(seg_card, fg_color="transparent")
        seg_inner.pack(fill="x", padx=18, pady=16)

        ctk.CTkLabel(
            seg_inner,
            text="2. 设置总段数并生成映射",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=15, weight="bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w")

        seg_row = ctk.CTkFrame(seg_inner, fg_color="transparent")
        seg_row.pack(fill="x", pady=(12, 0))

        ctk.CTkLabel(
            seg_row,
            text="总段数",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13),
            text_color=COLORS["muted"],
        ).pack(side="left")

        self.segment_entry = ctk.CTkEntry(
            seg_row,
            width=100,
            height=38,
            corner_radius=10,
            fg_color=COLORS["input"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(size=14),
            justify="center",
        )
        self.segment_entry.pack(side="left", padx=(12, 12))
        self.segment_entry.insert(0, "7")

        ctk.CTkButton(
            seg_row,
            text="生成映射框",
            width=130,
            height=38,
            corner_radius=10,
            fg_color=COLORS["panel_alt"],
            hover_color="#22314d",
            border_width=1,
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13, weight="bold"),
            command=self.generate_mapping_boxes,
        ).pack(side="left")

        map_card = ctk.CTkFrame(
            root, fg_color=COLORS["panel"], corner_radius=16, border_width=1, border_color=COLORS["border"]
        )
        map_card.pack(fill="x")

        map_inner = ctk.CTkFrame(map_card, fg_color="transparent")
        map_inner.pack(fill="x", padx=18, pady=14)

        ctk.CTkLabel(
            map_inner,
            text="3. 自定义导出映射（上面为原段序号，下面填写要保留的段；0 表示删除）",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=15, weight="bold"),
            text_color=COLORS["text"],
            anchor="w",
            height=28,
        ).pack(anchor="w")

        self.map_hint = ctk.CTkLabel(
            map_inner,
            text="示例：1 5 0 0 0 0 0 → 仅输出第 1 段和第 5 段",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
            text_color=COLORS["muted"],
            anchor="w",
            height=22,
        )
        self.map_hint.pack(anchor="w", pady=(4, 10))

        self._map_row_h = 48
        self._map_row_gap = 8
        self._map_rows_h = self._map_row_h * 2 + self._map_row_gap
        self._map_scroll_bar_space = 24

        self.map_scroll_wrap = tk.Frame(
            map_inner,
            bg=COLORS["panel"],
            height=self._map_rows_h + self._map_scroll_bar_space,
        )
        self.map_scroll_wrap.pack(fill="x")
        self.map_scroll_wrap.pack_propagate(False)

        self._map_canvas = tk.Canvas(
            self.map_scroll_wrap,
            highlightthickness=0,
            bd=0,
            height=self._map_rows_h,
            bg=COLORS["panel"],
        )
        self._map_h_scroll = ctk.CTkScrollbar(
            self.map_scroll_wrap,
            orientation="horizontal",
            command=self._map_canvas.xview,
            fg_color=COLORS["panel"],
            button_color=COLORS["border"],
            button_hover_color="#3a4f73",
            height=14,
        )
        self._map_canvas.configure(xscrollcommand=self._map_h_scroll.set)
        self._map_h_scroll.pack(side="bottom", fill="x")
        self._map_canvas.pack(side="top", fill="x")

        self.map_content = ctk.CTkFrame(self._map_canvas, fg_color="transparent", width=1, height=1)
        self._map_canvas_window = self._map_canvas.create_window(
            (0, 0), window=self.map_content, anchor="nw"
        )
        self.map_content.bind("<Configure>", lambda _e: self._sync_map_scroll())

        self.index_row = ctk.CTkFrame(
            self.map_content, fg_color=COLORS["panel_alt"], corner_radius=10, height=self._map_row_h
        )
        self.index_row.pack(anchor="w", pady=(0, self._map_row_gap))
        self.index_row.pack_propagate(False)

        self.mapping_row = ctk.CTkFrame(
            self.map_content, fg_color=COLORS["panel_alt"], corner_radius=10, height=self._map_row_h
        )
        self.mapping_row.pack(anchor="w")
        self.mapping_row.pack_propagate(False)

        ctk.CTkFrame(root, fg_color="transparent", height=1).pack(fill="both", expand=True)

        footer = ctk.CTkFrame(root, fg_color="transparent")
        footer.pack(fill="x", pady=(16, 0))

        # 按钮单独窗口居中，状态文字再贴在按钮右侧（不参与居中）
        action = ctk.CTkFrame(footer, fg_color="transparent", height=52)
        action.pack(fill="x", pady=(0, 12))
        action.pack_propagate(False)

        self.process_btn = ctk.CTkButton(
            action,
            text="开始处理",
            width=self._process_btn_width,
            height=44,
            corner_radius=12,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color="#042f2e",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=15, weight="bold"),
            command=self.start_process,
        )
        self.process_btn.place(relx=0.5, rely=0.5, anchor="center")

        self.status_label = ctk.CTkLabel(
            action,
            text="就绪",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13),
            text_color=COLORS["muted"],
        )
        self.status_label.place(
            relx=0.5,
            rely=0.5,
            anchor="w",
            x=self._process_btn_width // 2 + 16,
        )

        self.progress = ctk.CTkProgressBar(
            footer,
            height=8,
            corner_radius=8,
            fg_color=COLORS["panel_alt"],
            progress_color=COLORS["accent"],
        )
        self.progress.pack(fill="x")
        self.progress.set(0)

        self.generate_mapping_boxes()

    # ---------- 格式添加页 ----------
    def _build_merge_page(self, root: ctk.CTkFrame) -> None:
        tip = ctk.CTkLabel(
            root,
            text="先后选择两个 txt，跳过空行后按行用 ---- 整行拼接；行少的一侧用完即停。",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
            text_color=COLORS["muted"],
            anchor="w",
        )
        tip.pack(anchor="w", pady=(0, 14))

        first_card = self._make_file_pick_card(
            root,
            title="1. 先上传的文件（拼在前面）",
            label_attr="merge_first_label",
            command=self.choose_merge_first,
        )
        first_card.pack(fill="x", pady=(0, 16))

        second_card = self._make_file_pick_card(
            root,
            title="2. 后上传的文件（拼在后面）",
            label_attr="merge_second_label",
            command=self.choose_merge_second,
        )
        second_card.pack(fill="x", pady=(0, 16))

        out_card = ctk.CTkFrame(
            root, fg_color=COLORS["panel"], corner_radius=16, border_width=1, border_color=COLORS["border"]
        )
        out_card.pack(fill="x")
        out_inner = ctk.CTkFrame(out_card, fg_color="transparent")
        out_inner.pack(fill="x", padx=18, pady=16)
        ctk.CTkLabel(
            out_inner,
            text="3. 输出位置",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=15, weight="bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w")
        self.merge_out_label = ctk.CTkLabel(
            out_inner,
            text=str(get_output_dir()),
            anchor="w",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13),
            text_color=COLORS["muted"],
        )
        self.merge_out_label.pack(anchor="w", pady=(10, 0))

        ctk.CTkFrame(root, fg_color="transparent", height=1).pack(fill="both", expand=True)

        footer = ctk.CTkFrame(root, fg_color="transparent")
        footer.pack(fill="x", pady=(16, 0))

        action = ctk.CTkFrame(footer, fg_color="transparent", height=52)
        action.pack(fill="x", pady=(0, 12))
        action.pack_propagate(False)

        self.merge_btn = ctk.CTkButton(
            action,
            text="开始拼接",
            width=self._process_btn_width,
            height=44,
            corner_radius=12,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color="#042f2e",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=15, weight="bold"),
            command=self.start_merge,
        )
        self.merge_btn.place(relx=0.5, rely=0.5, anchor="center")

        self.merge_status_label = ctk.CTkLabel(
            action,
            text="就绪",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13),
            text_color=COLORS["muted"],
        )
        self.merge_status_label.place(
            relx=0.5,
            rely=0.5,
            anchor="w",
            x=self._process_btn_width // 2 + 16,
        )

        self.merge_progress = ctk.CTkProgressBar(
            footer,
            height=8,
            corner_radius=8,
            fg_color=COLORS["panel_alt"],
            progress_color=COLORS["accent"],
        )
        self.merge_progress.pack(fill="x")
        self.merge_progress.set(0)

    # ---------- 别名随机页 ----------
    def _build_alias_page(self, root: ctk.CTkFrame) -> None:
        tip = ctk.CTkLabel(
            root,
            text="第 1 段邮箱在 @ 前加 +、可选指定串、再接随机（首位字母，其余字母+数字）；无 @ / 空行跳过。",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
            text_color=COLORS["muted"],
            anchor="w",
        )
        tip.pack(anchor="w", pady=(0, 14))

        file_card = self._make_file_pick_card(
            root,
            title="1. 选择 TXT 文件",
            label_attr="alias_file_label",
            command=self.choose_alias_file,
        )
        file_card.pack(fill="x", pady=(0, 16))

        len_card = ctk.CTkFrame(
            root, fg_color=COLORS["panel"], corner_radius=16, border_width=1, border_color=COLORS["border"]
        )
        len_card.pack(fill="x", pady=(0, 16))
        len_inner = ctk.CTkFrame(len_card, fg_color="transparent")
        len_inner.pack(fill="x", padx=18, pady=16)
        ctk.CTkLabel(
            len_inner,
            text="2. 随机位数（空=4~6；只填一边=固定位数；左大于右则对调）",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=15, weight="bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w")
        len_row = ctk.CTkFrame(len_inner, fg_color="transparent")
        len_row.pack(fill="x", pady=(12, 0))
        self.alias_len_low = ctk.CTkEntry(
            len_row,
            width=80,
            height=38,
            corner_radius=10,
            fg_color=COLORS["input"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(size=14),
            justify="center",
        )
        self.alias_len_low.pack(side="left")
        self.alias_len_low.insert(0, "4")
        ctk.CTkLabel(
            len_row,
            text="-",
            width=24,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=16, weight="bold"),
            text_color=COLORS["muted"],
        ).pack(side="left")
        self.alias_len_high = ctk.CTkEntry(
            len_row,
            width=80,
            height=38,
            corner_radius=10,
            fg_color=COLORS["input"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(size=14),
            justify="center",
        )
        self.alias_len_high.pack(side="left")
        self.alias_len_high.insert(0, "6")

        spec_card = ctk.CTkFrame(
            root, fg_color=COLORS["panel"], corner_radius=16, border_width=1, border_color=COLORS["border"]
        )
        spec_card.pack(fill="x", pady=(0, 16))
        spec_inner = ctk.CTkFrame(spec_card, fg_color="transparent")
        spec_inner.pack(fill="x", padx=18, pady=16)
        ctk.CTkLabel(
            spec_inner,
            text="3. 指定随机（可空；有内容则原样接在 + 后、随机前）",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=15, weight="bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w")
        self.alias_specified = ctk.CTkEntry(
            spec_inner,
            height=38,
            corner_radius=10,
            fg_color=COLORS["input"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13),
            placeholder_text="例如 vip，结果如 frank+vipab3x@…",
        )
        self.alias_specified.pack(fill="x", pady=(12, 0))

        out_card = ctk.CTkFrame(
            root, fg_color=COLORS["panel"], corner_radius=16, border_width=1, border_color=COLORS["border"]
        )
        out_card.pack(fill="x")
        out_inner = ctk.CTkFrame(out_card, fg_color="transparent")
        out_inner.pack(fill="x", padx=18, pady=16)
        ctk.CTkLabel(
            out_inner,
            text="4. 输出位置",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=15, weight="bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w")
        self.alias_out_label = ctk.CTkLabel(
            out_inner,
            text=str(get_output_dir()),
            anchor="w",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13),
            text_color=COLORS["muted"],
        )
        self.alias_out_label.pack(anchor="w", pady=(10, 0))

        ctk.CTkFrame(root, fg_color="transparent", height=1).pack(fill="both", expand=True)

        footer = ctk.CTkFrame(root, fg_color="transparent")
        footer.pack(fill="x", pady=(16, 0))

        action = ctk.CTkFrame(footer, fg_color="transparent", height=52)
        action.pack(fill="x", pady=(0, 12))
        action.pack_propagate(False)

        self.alias_btn = ctk.CTkButton(
            action,
            text="开始处理",
            width=self._process_btn_width,
            height=44,
            corner_radius=12,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color="#042f2e",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=15, weight="bold"),
            command=self.start_alias,
        )
        self.alias_btn.place(relx=0.5, rely=0.5, anchor="center")

        self.alias_status_label = ctk.CTkLabel(
            action,
            text="就绪",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13),
            text_color=COLORS["muted"],
        )
        self.alias_status_label.place(
            relx=0.5,
            rely=0.5,
            anchor="w",
            x=self._process_btn_width // 2 + 16,
        )

        self.alias_progress = ctk.CTkProgressBar(
            footer,
            height=8,
            corner_radius=8,
            fg_color=COLORS["panel_alt"],
            progress_color=COLORS["accent"],
        )
        self.alias_progress.pack(fill="x")
        self.alias_progress.set(0)

    # ---------- 提取数据页 ----------
    def _build_extract_page(self, root: ctk.CTkFrame) -> None:
        tip = ctk.CTkLabel(
            root,
            text="从开头取 N 条非空行；每提一行立刻写入输出并从原文件删除。空行只删不写。",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
            text_color=COLORS["muted"],
            anchor="w",
        )
        tip.pack(anchor="w", pady=(0, 14))

        file_card = self._make_file_pick_card(
            root,
            title="1. 选择 TXT 文件（会改写该文件）",
            label_attr="extract_file_label",
            command=self.choose_extract_file,
        )
        file_card.pack(fill="x", pady=(0, 16))

        count_card = ctk.CTkFrame(
            root, fg_color=COLORS["panel"], corner_radius=16, border_width=1, border_color=COLORS["border"]
        )
        count_card.pack(fill="x", pady=(0, 16))
        count_inner = ctk.CTkFrame(count_card, fg_color="transparent")
        count_inner.pack(fill="x", padx=18, pady=16)
        ctk.CTkLabel(
            count_inner,
            text="2. 提取个数",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=15, weight="bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w")
        count_row = ctk.CTkFrame(count_inner, fg_color="transparent")
        count_row.pack(fill="x", pady=(12, 0))
        ctk.CTkLabel(
            count_row,
            text="有效行数",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13),
            text_color=COLORS["muted"],
        ).pack(side="left")
        self.extract_count_entry = ctk.CTkEntry(
            count_row,
            width=120,
            height=38,
            corner_radius=10,
            fg_color=COLORS["input"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            font=ctk.CTkFont(size=14),
            justify="center",
        )
        self.extract_count_entry.pack(side="left", padx=(12, 0))
        self.extract_count_entry.insert(0, "10")

        out_card = ctk.CTkFrame(
            root, fg_color=COLORS["panel"], corner_radius=16, border_width=1, border_color=COLORS["border"]
        )
        out_card.pack(fill="x")
        out_inner = ctk.CTkFrame(out_card, fg_color="transparent")
        out_inner.pack(fill="x", padx=18, pady=16)
        ctk.CTkLabel(
            out_inner,
            text="3. 输出位置",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=15, weight="bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w")
        self.extract_out_label = ctk.CTkLabel(
            out_inner,
            text=str(get_output_dir()),
            anchor="w",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13),
            text_color=COLORS["muted"],
        )
        self.extract_out_label.pack(anchor="w", pady=(10, 0))

        ctk.CTkFrame(root, fg_color="transparent", height=1).pack(fill="both", expand=True)

        footer = ctk.CTkFrame(root, fg_color="transparent")
        footer.pack(fill="x", pady=(16, 0))
        action = ctk.CTkFrame(footer, fg_color="transparent", height=52)
        action.pack(fill="x", pady=(0, 12))
        action.pack_propagate(False)

        self.extract_btn = ctk.CTkButton(
            action,
            text="开始提取",
            width=self._process_btn_width,
            height=44,
            corner_radius=12,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color="#042f2e",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=15, weight="bold"),
            command=self.start_extract,
        )
        self.extract_btn.place(relx=0.5, rely=0.5, anchor="center")

        self.extract_status_label = ctk.CTkLabel(
            action,
            text="就绪",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13),
            text_color=COLORS["muted"],
        )
        self.extract_status_label.place(
            relx=0.5,
            rely=0.5,
            anchor="w",
            x=self._process_btn_width // 2 + 16,
        )

        self.extract_progress = ctk.CTkProgressBar(
            footer,
            height=8,
            corner_radius=8,
            fg_color=COLORS["panel_alt"],
            progress_color=COLORS["accent"],
        )
        self.extract_progress.pack(fill="x")
        self.extract_progress.set(0)

    # ---------- 文件去重页 ----------
    def _build_dedupe_page(self, root: ctk.CTkFrame) -> None:
        tip = ctk.CTkLabel(
            root,
            text="两文件按整行内容集合对比（忽略空行）；写出相同行与两边独有整合，行内只留一份。",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
            text_color=COLORS["muted"],
            anchor="w",
        )
        tip.pack(anchor="w", pady=(0, 14))

        first_card = self._make_file_pick_card(
            root,
            title="1. 选择文件 1",
            label_attr="dedupe_first_label",
            command=self.choose_dedupe_first,
        )
        first_card.pack(fill="x", pady=(0, 16))

        second_card = self._make_file_pick_card(
            root,
            title="2. 选择文件 2",
            label_attr="dedupe_second_label",
            command=self.choose_dedupe_second,
        )
        second_card.pack(fill="x", pady=(0, 16))

        out_card = ctk.CTkFrame(
            root, fg_color=COLORS["panel"], corner_radius=16, border_width=1, border_color=COLORS["border"]
        )
        out_card.pack(fill="x")
        out_inner = ctk.CTkFrame(out_card, fg_color="transparent")
        out_inner.pack(fill="x", padx=18, pady=16)
        ctk.CTkLabel(
            out_inner,
            text="3. 输出位置",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=15, weight="bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w")
        self.dedupe_out_label = ctk.CTkLabel(
            out_inner,
            text=str(get_output_dir()),
            anchor="w",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13),
            text_color=COLORS["muted"],
        )
        self.dedupe_out_label.pack(anchor="w", pady=(10, 0))

        ctk.CTkFrame(root, fg_color="transparent", height=1).pack(fill="both", expand=True)

        footer = ctk.CTkFrame(root, fg_color="transparent")
        footer.pack(fill="x", pady=(16, 0))

        action = ctk.CTkFrame(footer, fg_color="transparent", height=52)
        action.pack(fill="x", pady=(0, 12))
        action.pack_propagate(False)

        self.dedupe_btn = ctk.CTkButton(
            action,
            text="开始去重",
            width=self._process_btn_width,
            height=44,
            corner_radius=12,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color="#042f2e",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=15, weight="bold"),
            command=self.start_dedupe,
        )
        self.dedupe_btn.place(relx=0.5, rely=0.5, anchor="center")

        self.dedupe_status_label = ctk.CTkLabel(
            action,
            text="就绪",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13),
            text_color=COLORS["muted"],
        )
        self.dedupe_status_label.place(
            relx=0.5,
            rely=0.5,
            anchor="w",
            x=self._process_btn_width // 2 + 16,
        )

        self.dedupe_progress = ctk.CTkProgressBar(
            footer,
            height=8,
            corner_radius=8,
            fg_color=COLORS["panel_alt"],
            progress_color=COLORS["accent"],
        )
        self.dedupe_progress.pack(fill="x")
        self.dedupe_progress.set(0)

    def _make_file_pick_card(self, parent, title: str, label_attr: str, command):
        card = ctk.CTkFrame(
            parent, fg_color=COLORS["panel"], corner_radius=16, border_width=1, border_color=COLORS["border"]
        )
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=18, pady=16)
        ctk.CTkLabel(
            inner,
            text=title,
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=15, weight="bold"),
            text_color=COLORS["text"],
        ).pack(anchor="w")
        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x", pady=(12, 0))
        label = ctk.CTkLabel(
            row,
            text="尚未选择文件",
            anchor="w",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13),
            text_color=COLORS["muted"],
            fg_color=COLORS["input"],
            corner_radius=10,
            height=40,
        )
        label.pack(side="left", fill="x", expand=True, padx=(0, 12))
        setattr(self, label_attr, label)
        ctk.CTkButton(
            row,
            text="选择文件",
            width=120,
            height=40,
            corner_radius=10,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color="#042f2e",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13, weight="bold"),
            command=command,
        ).pack(side="right")
        return card

    def _sync_map_scroll(self) -> None:
        self.map_content.update_idletasks()
        req_h = max(self.map_content.winfo_reqheight(), 1)
        req_w = max(self.map_content.winfo_reqwidth(), 1)
        self._map_canvas.configure(height=req_h)
        self.map_scroll_wrap.configure(height=req_h + self._map_scroll_bar_space)
        self._map_canvas.itemconfigure(self._map_canvas_window, width=req_w, height=req_h)
        bbox = self._map_canvas.bbox("all")
        if bbox is not None:
            self._map_canvas.configure(scrollregion=bbox)

    def choose_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 TXT 文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self.source_path = Path(path)
        self.file_label.configure(text=str(self.source_path), text_color=COLORS["text"])
        self.set_status("已选择文件，设置映射后即可处理", COLORS["muted"])

    def choose_merge_first(self) -> None:
        path = filedialog.askopenfilename(
            title="选择先上传的 TXT",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self.merge_first_path = Path(path)
        self.merge_first_label.configure(text=str(self.merge_first_path), text_color=COLORS["text"])
        self.set_merge_status("已选择先上传文件", COLORS["muted"])

    def choose_merge_second(self) -> None:
        path = filedialog.askopenfilename(
            title="选择后上传的 TXT",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self.merge_second_path = Path(path)
        self.merge_second_label.configure(text=str(self.merge_second_path), text_color=COLORS["text"])
        self.set_merge_status("已选择后上传文件", COLORS["muted"])

    def choose_alias_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 TXT 文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self.alias_path = Path(path)
        self.alias_file_label.configure(text=str(self.alias_path), text_color=COLORS["text"])
        self.set_alias_status("已选择文件", COLORS["muted"])

    def choose_extract_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择要提取的 TXT（会改写原文件）",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self.extract_path = Path(path)
        self.extract_file_label.configure(text=str(self.extract_path), text_color=COLORS["text"])
        self.set_extract_status("已选择文件（提取后原文件会被改写）", COLORS["muted"])

    def choose_dedupe_first(self) -> None:
        path = filedialog.askopenfilename(
            title="选择文件 1",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self.dedupe_first_path = Path(path)
        self.dedupe_first_label.configure(text=str(self.dedupe_first_path), text_color=COLORS["text"])
        self.set_dedupe_status("已选择文件 1", COLORS["muted"])

    def choose_dedupe_second(self) -> None:
        path = filedialog.askopenfilename(
            title="选择文件 2",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self.dedupe_second_path = Path(path)
        self.dedupe_second_label.configure(text=str(self.dedupe_second_path), text_color=COLORS["text"])
        self.set_dedupe_status("已选择文件 2", COLORS["muted"])

    def generate_mapping_boxes(self) -> None:
        raw = self.segment_entry.get().strip()
        if not raw.isdigit() or int(raw) < 1:
            messagebox.showerror("参数错误", "总段数必须是大于等于 1 的整数。")
            return

        count = int(raw)
        if count > 64:
            messagebox.showerror("参数错误", "总段数过大，请控制在 64 以内。")
            return

        for widget in self.index_row.winfo_children():
            widget.destroy()
        for widget in self.mapping_row.winfo_children():
            widget.destroy()
        self.index_labels.clear()
        self.mapping_entries.clear()

        cell_w = 52
        cell_pad = 4
        label_area = 12 + 48 + 8
        content_w = label_area + count * (cell_w + cell_pad * 2) + 12
        self.index_row.configure(width=content_w, height=self._map_row_h)
        self.mapping_row.configure(width=content_w, height=self._map_row_h)

        ctk.CTkLabel(
            self.index_row,
            text="原段",
            width=48,
            anchor="w",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
            text_color=COLORS["muted"],
        ).pack(side="left", padx=(12, 8), pady=7)

        ctk.CTkLabel(
            self.mapping_row,
            text="映射",
            width=48,
            anchor="w",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=12),
            text_color=COLORS["muted"],
        ).pack(side="left", padx=(12, 8), pady=7)

        for i in range(1, count + 1):
            label = ctk.CTkLabel(
                self.index_row,
                text=str(i),
                width=cell_w,
                height=34,
                corner_radius=8,
                fg_color=COLORS["input"],
                text_color=COLORS["muted"],
                font=ctk.CTkFont(size=13, weight="bold"),
            )
            label.pack(side="left", padx=cell_pad, pady=7)
            self.index_labels.append(label)

            entry = ctk.CTkEntry(
                self.mapping_row,
                width=cell_w,
                height=34,
                corner_radius=8,
                fg_color=COLORS["input"],
                border_color=COLORS["border"],
                text_color=COLORS["text"],
                justify="center",
                font=ctk.CTkFont(size=13),
            )
            entry.pack(side="left", padx=cell_pad, pady=7)
            entry.insert(0, "0")
            self.mapping_entries.append(entry)

        self.after_idle(self._sync_map_scroll)
        self.set_status(f"已生成 {count} 段映射框，默认全为 0", COLORS["muted"])

    def read_mapping(self) -> tuple[int, list[int]]:
        raw = self.segment_entry.get().strip()
        if not raw.isdigit() or int(raw) < 1:
            raise ProcessError("总段数必须是大于等于 1 的整数。")
        count = int(raw)

        if len(self.mapping_entries) != count:
            raise ProcessError("映射框数量与总段数不一致，请先点击「生成映射框」。")

        mapping: list[int] = []
        for idx, entry in enumerate(self.mapping_entries, start=1):
            text = entry.get().strip()
            if text == "":
                mapping.append(0)
                continue
            if not text.isdigit():
                raise ProcessError(f"第 {idx} 个映射必须是整数（可留空视为 0）。")
            mapping.append(int(text))
        return count, mapping

    def start_process(self) -> None:
        if self._busy:
            return
        try:
            if self.source_path is None:
                raise ProcessError("请先选择 txt 文件。")
            segment_count, mapping = self.read_mapping()
            validate_mapping(segment_count, mapping)
        except ProcessError as exc:
            messagebox.showerror("无法开始", str(exc))
            self.set_status(str(exc), COLORS["danger"])
            return

        self._busy = True
        self.process_btn.configure(state="disabled")
        self.progress.set(0)
        self.set_status("正在处理，请稍候…", COLORS["accent"])

        thread = threading.Thread(
            target=self._run_process,
            args=(self.source_path, segment_count, mapping),
            daemon=True,
        )
        thread.start()

    def _run_process(self, source: Path, segment_count: int, mapping: list[int]) -> None:
        try:
            def on_progress(done: int, total: int, success: int, skipped: int) -> None:
                ratio = (done / total) if total else 1.0
                self.after(
                    0,
                    lambda d=done, t=total, s=success, k=skipped, r=ratio: (
                        self.set_status(
                            f"已处理 {d}/{t} 行｜成功 {s}｜跳过 {k}",
                            COLORS["accent"],
                        ),
                        self.progress.set(r),
                    ),
                )

            result = process_file(source, segment_count, mapping, on_progress)
            self.after(0, lambda r=result: self._on_success(r))
        except ProcessError as exc:
            self.after(0, lambda msg=str(exc): self._on_error(msg))
        except Exception as exc:  # noqa: BLE001
            self.after(0, lambda msg=f"处理失败：{exc}": self._on_error(msg))

    def start_merge(self) -> None:
        if self._busy:
            return
        try:
            if self.merge_first_path is None:
                raise ProcessError("请先选择先上传的 txt 文件。")
            if self.merge_second_path is None:
                raise ProcessError("请选择后上传的 txt 文件。")
        except ProcessError as exc:
            messagebox.showerror("无法开始", str(exc))
            self.set_merge_status(str(exc), COLORS["danger"])
            return

        self._busy = True
        self.merge_btn.configure(state="disabled")
        self.merge_progress.set(0)
        self.set_merge_status("正在拼接，请稍候…", COLORS["accent"])
        self.merge_out_label.configure(text=str(get_output_dir()))

        thread = threading.Thread(
            target=self._run_merge,
            args=(self.merge_first_path, self.merge_second_path),
            daemon=True,
        )
        thread.start()

    def _run_merge(self, first: Path, second: Path) -> None:
        try:
            def on_progress(done: int) -> None:
                # 不知道最终总数时给一个缓慢推进感
                ratio = min(0.95, 0.1 + (done % 2000) / 2200)
                self.after(
                    0,
                    lambda d=done, r=ratio: (
                        self.set_merge_status(f"已拼接 {d} 行…", COLORS["accent"]),
                        self.merge_progress.set(r),
                    ),
                )

            result = merge_files(first, second, get_output_dir(), on_progress)
            self.after(0, lambda r=result: self._on_merge_success(r))
        except ProcessError as exc:
            self.after(0, lambda msg=str(exc): self._on_merge_error(msg))
        except Exception as exc:  # noqa: BLE001
            self.after(0, lambda msg=f"拼接失败：{exc}": self._on_merge_error(msg))

    def start_alias(self) -> None:
        if self._busy:
            return
        try:
            if self.alias_path is None:
                raise ProcessError("请先选择 txt 文件。")
            min_len, max_len = parse_alias_length(
                self.alias_len_low.get(),
                self.alias_len_high.get(),
            )
            specified = self.alias_specified.get()
        except ProcessError as exc:
            messagebox.showerror("无法开始", str(exc))
            self.set_alias_status(str(exc), COLORS["danger"])
            return

        self._busy = True
        self.alias_btn.configure(state="disabled")
        self.alias_progress.set(0)
        self.set_alias_status("正在处理，请稍候…", COLORS["accent"])
        self.alias_out_label.configure(text=str(get_output_dir()))

        thread = threading.Thread(
            target=self._run_alias,
            args=(self.alias_path, min_len, max_len, specified),
            daemon=True,
        )
        thread.start()

    def _run_alias(
        self, source: Path, min_len: int, max_len: int, specified: str
    ) -> None:
        try:
            def on_progress(done: int, total: int, success: int, skipped: int) -> None:
                ratio = (done / total) if total else 1.0
                self.after(
                    0,
                    lambda d=done, t=total, s=success, k=skipped, r=ratio: (
                        self.set_alias_status(
                            f"已处理 {d}/{t} 行｜成功 {s}｜跳过 {k}",
                            COLORS["accent"],
                        ),
                        self.alias_progress.set(r),
                    ),
                )

            result = process_alias_file(
                source,
                get_output_dir(),
                on_progress,
                min_len=min_len,
                max_len=max_len,
                specified=specified,
            )
            self.after(0, lambda r=result: self._on_alias_success(r))
        except ProcessError as exc:
            self.after(0, lambda msg=str(exc): self._on_alias_error(msg))
        except Exception as exc:  # noqa: BLE001
            self.after(0, lambda msg=f"处理失败：{exc}": self._on_alias_error(msg))

    def _on_success(self, result) -> None:
        self._busy = False
        self.process_btn.configure(state="normal")
        self.progress.set(1)
        msg = (
            f"处理完成\n\n"
            f"总行数：{result.total_lines}\n"
            f"成功：{result.success_lines}\n"
            f"跳过：{result.skipped_lines}\n\n"
            f"输出文件：\n{result.output_path}"
        )
        self.set_status(
            f"完成｜成功 {result.success_lines}｜跳过 {result.skipped_lines}",
            COLORS["ok"],
        )
        messagebox.showinfo("处理完成", msg)

    def _on_error(self, message: str) -> None:
        self._busy = False
        self.process_btn.configure(state="normal")
        self.progress.set(0)
        self.set_status(message, COLORS["danger"])
        messagebox.showerror("处理失败", message)

    def _on_merge_success(self, result) -> None:
        self._busy = False
        self.merge_btn.configure(state="normal")
        self.merge_progress.set(1)

        if result.remainder_count > 0 and result.remainder_path is not None:
            side = "先上传文件" if result.remainder_side == "first" else "后上传文件"
            rem_text = (
                f"剩余：{result.remainder_count} 行（{side}）\n"
                f"剩余文件：\n{result.remainder_path}"
            )
            status = f"完成｜拼接 {result.merged_count}｜剩余 {result.remainder_count}"
        else:
            rem_text = "剩余：无剩余"
            status = f"完成｜拼接 {result.merged_count}｜无剩余"

        msg = (
            f"拼接完成\n\n"
            f"成功拼接：{result.merged_count} 行\n"
            f"{rem_text}\n\n"
            f"合并文件：\n{result.merged_path}"
        )
        self.set_merge_status(status, COLORS["ok"])
        messagebox.showinfo("拼接完成", msg)

    def _on_merge_error(self, message: str) -> None:
        self._busy = False
        self.merge_btn.configure(state="normal")
        self.merge_progress.set(0)
        self.set_merge_status(message, COLORS["danger"])
        messagebox.showerror("拼接失败", message)

    def _on_alias_success(self, result) -> None:
        self._busy = False
        self.alias_btn.configure(state="normal")
        self.alias_progress.set(1)
        msg = (
            f"处理完成\n\n"
            f"总行数：{result.total_lines}\n"
            f"成功：{result.success_lines}\n"
            f"跳过：{result.skipped_lines}\n\n"
            f"输出文件：\n{result.output_path}"
        )
        self.set_alias_status(
            f"完成｜成功 {result.success_lines}｜跳过 {result.skipped_lines}",
            COLORS["ok"],
        )
        messagebox.showinfo("处理完成", msg)

    def _on_alias_error(self, message: str) -> None:
        self._busy = False
        self.alias_btn.configure(state="normal")
        self.alias_progress.set(0)
        self.set_alias_status(message, COLORS["danger"])
        messagebox.showerror("处理失败", message)

    def start_extract(self) -> None:
        if self._busy:
            return
        try:
            if self.extract_path is None:
                raise ProcessError("请先选择 txt 文件。")
            raw = self.extract_count_entry.get().strip()
            if not raw.isdigit() or int(raw) < 1:
                raise ProcessError("提取个数必须是大于等于 1 的整数。")
            count = int(raw)
        except ProcessError as exc:
            messagebox.showerror("无法开始", str(exc))
            self.set_extract_status(str(exc), COLORS["danger"])
            return

        self._busy = True
        self.extract_btn.configure(state="disabled")
        self.extract_progress.set(0)
        self.set_extract_status("正在提取，请稍候…", COLORS["accent"])
        self.extract_out_label.configure(text=str(get_output_dir()))

        thread = threading.Thread(
            target=self._run_extract,
            args=(self.extract_path, count),
            daemon=True,
        )
        thread.start()

    def _run_extract(self, source: Path, count: int) -> None:
        try:
            def on_progress(done: int, total: int, removed_empty: int) -> None:
                ratio = (done / total) if total else 1.0
                self.after(
                    0,
                    lambda d=done, t=total, e=removed_empty, r=ratio: (
                        self.set_extract_status(
                            f"已提取 {d}/{t}｜清理空行 {e}",
                            COLORS["accent"],
                        ),
                        self.extract_progress.set(min(1.0, r)),
                    ),
                )

            result = extract_lines(source, count, get_output_dir(), on_progress)
            self.after(0, lambda r=result: self._on_extract_success(r))
        except ProcessError as exc:
            self.after(0, lambda msg=str(exc): self._on_extract_error(msg))
        except Exception as exc:  # noqa: BLE001
            self.after(0, lambda msg=f"提取失败：{exc}": self._on_extract_error(msg))

    def _on_extract_success(self, result) -> None:
        self._busy = False
        self.extract_btn.configure(state="normal")
        self.extract_progress.set(1)
        extra = "（原文件已提空）" if result.source_exhausted else ""
        msg = (
            f"提取完成{extra}\n\n"
            f"目标：{result.requested} 行\n"
            f"实际提取：{result.extracted} 行\n"
            f"清理空行：{result.removed_empty}\n\n"
            f"输出文件：\n{result.output_path}"
        )
        self.set_extract_status(
            f"完成｜提取 {result.extracted}/{result.requested}",
            COLORS["ok"],
        )
        messagebox.showinfo("提取完成", msg)

    def _on_extract_error(self, message: str) -> None:
        self._busy = False
        self.extract_btn.configure(state="normal")
        self.extract_progress.set(0)
        self.set_extract_status(message, COLORS["danger"])
        messagebox.showerror("提取失败", message)

    def start_dedupe(self) -> None:
        if self._busy:
            return
        try:
            if self.dedupe_first_path is None:
                raise ProcessError("请先选择文件 1。")
            if self.dedupe_second_path is None:
                raise ProcessError("请选择文件 2。")
        except ProcessError as exc:
            messagebox.showerror("无法开始", str(exc))
            self.set_dedupe_status(str(exc), COLORS["danger"])
            return

        self._busy = True
        self.dedupe_btn.configure(state="disabled")
        self.dedupe_progress.set(0)
        self.set_dedupe_status("正在去重，请稍候…", COLORS["accent"])
        self.dedupe_out_label.configure(text=str(get_output_dir()))

        thread = threading.Thread(
            target=self._run_dedupe,
            args=(self.dedupe_first_path, self.dedupe_second_path),
            daemon=True,
        )
        thread.start()

    def _run_dedupe(self, first: Path, second: Path) -> None:
        try:
            def on_progress(stage: str, a: int, b: int) -> None:
                if stage == "read1":
                    text, ratio = f"读取文件 1… {a} 行｜有效 {b}", 0.15
                elif stage == "read2":
                    text, ratio = f"读取文件 2… {a} 行｜有效 {b}", 0.45
                elif stage == "compare":
                    text, ratio = "正在对比集合…", 0.7
                elif stage == "write":
                    text, ratio = f"正在写入… 相同 {a}｜独有 {b}", 0.9
                else:
                    text, ratio = f"完成｜相同 {a}｜独有 {b}", 1.0
                self.after(
                    0,
                    lambda t=text, r=ratio: (
                        self.set_dedupe_status(t, COLORS["accent"]),
                        self.dedupe_progress.set(r),
                    ),
                )

            result = dedupe_files(first, second, get_output_dir(), on_progress)
            self.after(0, lambda r=result: self._on_dedupe_success(r))
        except ProcessError as exc:
            self.after(0, lambda msg=str(exc): self._on_dedupe_error(msg))
        except Exception as exc:  # noqa: BLE001
            self.after(0, lambda msg=f"去重失败：{exc}": self._on_dedupe_error(msg))

    def _on_dedupe_success(self, result) -> None:
        self._busy = False
        self.dedupe_btn.configure(state="normal")
        self.dedupe_progress.set(1)
        msg = (
            f"去重完成\n\n"
            f"相同行：{result.same_count}\n"
            f"{result.same_path}\n\n"
            f"独有行：{result.unique_count}\n"
            f"{result.unique_path}"
        )
        self.set_dedupe_status(
            f"完成｜相同 {result.same_count}｜独有 {result.unique_count}",
            COLORS["ok"],
        )
        messagebox.showinfo("去重完成", msg)

    def _on_dedupe_error(self, message: str) -> None:
        self._busy = False
        self.dedupe_btn.configure(state="normal")
        self.dedupe_progress.set(0)
        self.set_dedupe_status(message, COLORS["danger"])
        messagebox.showerror("去重失败", message)

    def set_status(self, text: str, color: str) -> None:
        self.status_label.configure(text=text, text_color=color)

    def set_merge_status(self, text: str, color: str) -> None:
        self.merge_status_label.configure(text=text, text_color=color)

    def set_alias_status(self, text: str, color: str) -> None:
        self.alias_status_label.configure(text=text, text_color=color)

    def set_extract_status(self, text: str, color: str) -> None:
        self.extract_status_label.configure(text=text, text_color=color)

    def set_dedupe_status(self, text: str, color: str) -> None:
        self.dedupe_status_label.configure(text=text, text_color=color)


def main() -> None:
    app = FormatToolApp()
    app.mainloop()


if __name__ == "__main__":
    main()
