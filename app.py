"""格式处理工具 - 深色现代界面。"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from processor import ProcessError, process_file, validate_mapping


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


class FormatToolApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("TXT 格式处理工具")
        self.geometry("920x700")
        self.minsize(820, 640)
        self.configure(fg_color=COLORS["bg"])

        self.source_path: Path | None = None
        self.mapping_entries: list[ctk.CTkEntry] = []
        self.index_labels: list[ctk.CTkLabel] = []
        self._busy = False

        self._build_ui()

    def _build_ui(self) -> None:
        root = ctk.CTkFrame(self, fg_color=COLORS["bg"])
        root.pack(fill="both", expand=True, padx=28, pady=24)

        title = ctk.CTkLabel(
            root,
            text="TXT 格式处理工具",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=28, weight="bold"),
            text_color=COLORS["text"],
        )
        title.pack(anchor="w")

        subtitle = ctk.CTkLabel(
            root,
            text="按自定义映射重组 ---- 分隔字段，一键导出处理后的文本",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=13),
            text_color=COLORS["muted"],
        )
        subtitle.pack(anchor="w", pady=(6, 22))

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

        # 第 3 区先按内容固高排版，避免被底部栏 side=bottom 挤占后纵向压扁
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

        # 横向滚动：tk.Frame 固高 + Canvas，高度锁定为两行内容。
        # 根因不是「height 数值偏小」，而是 CTkScrollableFrame(horizontal)
        # 在父级被挤压时会缩小 canvas，并把内部窗口高度锁成缩小后的值，
        # 第二行被裁掉且没有纵向滚动可找回。
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

        # 弹性空白吃掉多余高度，把底部栏顶在窗口下方，同时不挤压第 3 区
        ctk.CTkFrame(root, fg_color="transparent", height=1).pack(fill="both", expand=True)

        footer = ctk.CTkFrame(root, fg_color="transparent")
        footer.pack(fill="x", pady=(12, 0))

        action = ctk.CTkFrame(footer, fg_color="transparent", height=48)
        action.pack(fill="x", pady=(0, 14))
        action.pack_propagate(False)

        # 按钮单独左右居中，状态文字再贴在按钮右侧（不参与居中）
        self._process_btn_width = 180
        self.process_btn = ctk.CTkButton(
            action,
            text="开始处理",
            width=self._process_btn_width,
            height=48,
            corner_radius=12,
            fg_color=COLORS["accent"],
            hover_color=COLORS["accent_hover"],
            text_color="#042f2e",
            font=ctk.CTkFont(family="Microsoft YaHei UI", size=16, weight="bold"),
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

    def _sync_map_scroll(self) -> None:
        """锁定两行完整可见高度，只维护横向 scrollregion。"""
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
            # 开始前就校验（含全 0），避免进入处理状态后才报错/卡住
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
            # 必须用默认参数绑定消息，否则 except 结束后 exc 会被清除，回调卡住
            self.after(0, lambda msg=str(exc): self._on_error(msg))
        except Exception as exc:  # noqa: BLE001
            self.after(0, lambda msg=f"处理失败：{exc}": self._on_error(msg))

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

    def set_status(self, text: str, color: str) -> None:
        self.status_label.configure(text=text, text_color=color)


def main() -> None:
    app = FormatToolApp()
    app.mainloop()


if __name__ == "__main__":
    main()
