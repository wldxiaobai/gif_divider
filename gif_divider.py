import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk


class ProgressDialog(tk.Toplevel):
    """模态进度对话框，显示百分比和进度条"""

    def __init__(self, parent, title="处理中…"):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", lambda: None)

        frame = ttk.Frame(self, padding=20)
        frame.pack(fill=tk.BOTH, expand=True)

        self.msg_label = ttk.Label(frame, text="请稍候…", width=40)
        self.msg_label.pack(pady=(0, 8))

        self.progress = ttk.Progressbar(frame, length=300, mode="determinate",
                                         maximum=100)
        self.progress.pack(pady=(0, 4))

        self.pct_label = ttk.Label(frame, text="0%")
        self.pct_label.pack()

        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def set_progress(self, value, maximum, message=""):
        """更新进度（必须在主线程调用）"""
        pct = int(value / maximum * 100) if maximum > 0 else 0
        self.progress["maximum"] = maximum
        self.progress["value"] = value
        self.pct_label.config(text=f"{pct}%")
        if message:
            self.msg_label.config(text=message)

    def close(self):
        self.grab_release()
        self.destroy()


class GifDividerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("GIF 拆帧工具")
        self.root.resizable(True, True)

        self.gif_path = None
        self.frames = []          # 暂存解码后的所有帧 (RGBA)
        self.result_image = None
        self._preview_image = None
        self._preview_photo = None
        self._preview_zoom = 1.0
        self._hq_after_id = None
        self._interactive_widgets = []
        self._busy = False

        self._build_ui()

    # ── UI 构建 ─────────────────────────────────────────────
    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)

        # GIF 文件选择
        f_file = ttk.Frame(main)
        f_file.pack(fill=tk.X, pady=4)
        ttk.Label(f_file, text="GIF 文件:").pack(side=tk.LEFT)
        self.file_label = ttk.Label(f_file, text="未选择", width=36, anchor=tk.W)
        self.file_label.pack(side=tk.LEFT, padx=6)
        btn_file = ttk.Button(f_file, text="选择文件…", command=self._select_file)
        btn_file.pack(side=tk.LEFT)
        self._interactive_widgets.append(btn_file)

        # 1) 最大横向帧数
        f1 = ttk.Frame(main)
        f1.pack(fill=tk.X, pady=4)
        ttk.Label(f1, text="最大横向帧数:").pack(side=tk.LEFT)
        self.max_cols_var = tk.IntVar(value=10)
        spin_cols = ttk.Spinbox(f1, from_=1, to=999, textvariable=self.max_cols_var,
                                 width=8)
        spin_cols.pack(side=tk.LEFT, padx=6)
        self._interactive_widgets.append(spin_cols)

        # 2) 最大纵向帧数
        f2 = ttk.Frame(main)
        f2.pack(fill=tk.X, pady=4)
        ttk.Label(f2, text="最大纵向帧数:").pack(side=tk.LEFT)
        self.max_rows_var = tk.IntVar(value=10)
        spin_rows = ttk.Spinbox(f2, from_=1, to=999, textvariable=self.max_rows_var,
                                 width=8)
        spin_rows.pack(side=tk.LEFT, padx=6)
        self._interactive_widgets.append(spin_rows)

        # 3) 排列方向
        f3 = ttk.Frame(main)
        f3.pack(fill=tk.X, pady=4)
        ttk.Label(f3, text="排列方向:").pack(side=tk.LEFT)
        self.direction_var = tk.StringVar(value="horizontal")
        rb_h = ttk.Radiobutton(f3, text="横向优先", variable=self.direction_var,
                                value="horizontal")
        rb_h.pack(side=tk.LEFT, padx=6)
        self._interactive_widgets.append(rb_h)
        rb_v = ttk.Radiobutton(f3, text="纵向优先", variable=self.direction_var,
                                value="vertical")
        rb_v.pack(side=tk.LEFT, padx=6)
        self._interactive_widgets.append(rb_v)

        # 4) 保存方式
        f_save = ttk.Frame(main)
        f_save.pack(fill=tk.X, pady=4)
        ttk.Label(f_save, text="保存方式:").pack(side=tk.LEFT)
        self.save_mode_var = tk.StringVar(value="single")
        rb_single = ttk.Radiobutton(f_save, text="保存为单张png序列帧",
                                     variable=self.save_mode_var, value="single")
        rb_single.pack(side=tk.LEFT, padx=6)
        self._interactive_widgets.append(rb_single)
        rb_folder = ttk.Radiobutton(f_save, text="保存为包含所有帧的子文件夹",
                                     variable=self.save_mode_var, value="folder")
        rb_folder.pack(side=tk.LEFT, padx=6)
        self._interactive_widgets.append(rb_folder)

        # 5) 缩放比例
        f4 = ttk.Frame(main)
        f4.pack(fill=tk.X, pady=4)
        ttk.Label(f4, text="缩放比例:").pack(side=tk.LEFT)
        self.scale_var = tk.DoubleVar(value=1.0)
        spin_scale = ttk.Spinbox(f4, from_=0.1, to=10.0, increment=0.1,
                                  textvariable=self.scale_var, width=8)
        spin_scale.pack(side=tk.LEFT, padx=6)
        self._interactive_widgets.append(spin_scale)

        # 6) 生成预览 + 开始拆帧 按钮
        f_btns = ttk.Frame(main)
        f_btns.pack(pady=10)
        btn_preview = ttk.Button(f_btns, text="👁 生成预览", command=self._update_preview)
        btn_preview.pack(side=tk.LEFT, padx=6)
        self._interactive_widgets.append(btn_preview)
        btn_start = ttk.Button(f_btns, text="▶ 开始拆帧", command=self._start)
        btn_start.pack(side=tk.LEFT, padx=6)
        self._interactive_widgets.append(btn_start)

        # 7) 预览区
        ttk.Label(main, text="拆解预览:").pack(anchor=tk.W)
        self.preview_hint = ttk.Label(main, text="", foreground="gray")
        self.preview_hint.pack(anchor=tk.W)

        f_preview_wrapper = ttk.Frame(main)
        f_preview_wrapper.pack(fill=tk.BOTH, expand=True, pady=4)

        preview_container = ttk.Frame(f_preview_wrapper, relief=tk.SUNKEN, borderwidth=1)
        preview_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(preview_container, width=520, height=400, bg="#f0f0f0")
        h_scroll = ttk.Scrollbar(preview_container, orient=tk.HORIZONTAL,
                                  command=self.canvas.xview)
        v_scroll = ttk.Scrollbar(preview_container, orient=tk.VERTICAL,
                                  command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")
        preview_container.rowconfigure(0, weight=1)
        preview_container.columnconfigure(0, weight=1)

        # 预览信息面板
        info_frame = ttk.Frame(f_preview_wrapper)
        info_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(6, 0))
        self.size_info_label = ttk.Label(info_frame, text="", justify=tk.LEFT)
        self.size_info_label.pack(anchor=tk.NW)
        self.zoom_info_label = ttk.Label(info_frame, text="", justify=tk.LEFT,
                                          foreground="gray")
        self.zoom_info_label.pack(anchor=tk.NW, pady=(4, 0))

        # 鼠标滚轮缩放 + 拖拽平移
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self.canvas.bind("<B1-Motion>", self._on_drag_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_drag_end)

    # ── UI 锁定
    def _lock_ui(self):
        for w in self._interactive_widgets:
            try:
                w.config(state="disabled")
            except tk.TclError:
                pass

    def _unlock_ui(self):
        for w in self._interactive_widgets:
            try:
                w.config(state="normal")
            except tk.TclError:
                pass

    # ── 通用后台线程运行器 ────────────────────────────────────
    def _run_in_thread(self, title, worker, on_done):
        """在后台线程执行 worker(progress_cb)，完成后在主线程调用 on_done(result, error)"""
        self._busy = True
        self._lock_ui()
        dlg = ProgressDialog(self.root, title)

        def progress_cb(current, total, msg=""):
            self.root.after(0, dlg.set_progress, current, total, msg)

        def target():
            try:
                result = worker(progress_cb)
                error = None
            except Exception as e:
                result = None
                error = e
            self.root.after(0, finish, result, error)

        def finish(result, error):
            dlg.close()
            self._unlock_ui()
            self._busy = False
            on_done(result, error)

        threading.Thread(target=target, daemon=True).start()

    # ── 选择文件 ────────────────────────────────────────────
    def _select_file(self):
        path = filedialog.askopenfilename(
            title="选择 GIF 文件",
            filetypes=[("GIF 文件", "*.gif"), ("所有文件", "*.*")]
        )
        if path:
            self.gif_path = path
            self.file_label.config(text=os.path.basename(path))
            self._load_gif()

    # ── 导入并暂存 GIF 帧（异步）──────────────────────────────
    def _load_gif(self):
        def worker(progress_cb):
            gif = Image.open(self.gif_path)
            n_frames = getattr(gif, 'n_frames', 1)
            frames = []
            for i in range(n_frames):
                gif.seek(i)
                frames.append(gif.copy().convert("RGBA"))
                progress_cb(i + 1, n_frames, f"正在解码帧 {i + 1}/{n_frames}…")
            return frames

        def on_done(result, error):
            if error:
                messagebox.showerror("错误", f"无法打开文件:\n{error}")
                self.gif_path = None
                self.frames = []
                self.file_label.config(text="未选择")
                return
            if not result:
                messagebox.showwarning("提示", "未能从 GIF 中提取到帧")
                self.gif_path = None
                self.frames = []
                self.file_label.config(text="未选择")
                return
            self.frames = result
            count = len(self.frames)
            self._update_preview(
                on_complete=lambda: messagebox.showinfo(
                    "导入成功", f"已加载 {count} 帧，可点击开始拆帧"))

        self._run_in_thread("导入 GIF", worker, on_done)

    # ── 拆帧核心逻辑（异步）───────────────────────────────────
    def _start(self):
        if not self.frames:
            messagebox.showwarning("提示", "请先选择一个 GIF 文件")
            return

        src_frames = [f.copy() for f in self.frames]
        total = len(src_frames)
        max_cols = self.max_cols_var.get()
        max_rows = self.max_rows_var.get()
        scale = self.scale_var.get()
        direction = self.direction_var.get()
        save_mode = self.save_mode_var.get()
        gif_dir = os.path.dirname(self.gif_path)
        base_name = os.path.splitext(os.path.basename(self.gif_path))[0]

        def worker(progress_cb):
            frames = src_frames
            fw, fh = frames[0].size
            fw, fh = int(fw * scale), int(fh * scale)

            # 计算行列
            if direction == "horizontal":
                cols = min(max_cols, total)
                rows = min(max_rows, -(-total // cols))
            else:
                rows = min(max_rows, total)
                cols = min(max_cols, -(-total // rows))
            placed = min(total, cols * rows)

            # 计算总步数
            scale_steps = total if scale != 1.0 else 0
            compose_steps = placed
            save_steps = total if save_mode == "folder" else 1
            total_steps = scale_steps + compose_steps + save_steps
            done = 0

            # 缩放每帧
            if scale != 1.0:
                scaled = []
                for i, f in enumerate(frames):
                    scaled.append(f.resize((fw, fh), Image.LANCZOS))
                    done += 1
                    progress_cb(done, total_steps, f"缩放帧 {i + 1}/{total}…")
                frames = scaled

            # 拼合精灵图
            sheet = Image.new("RGBA", (cols * fw, rows * fh), (0, 0, 0, 0))
            for idx, frame in enumerate(frames):
                if direction == "horizontal":
                    r, c = divmod(idx, cols)
                else:
                    c, r = divmod(idx, rows)
                if r >= rows or c >= cols:
                    break
                sheet.paste(frame, (c * fw, r * fh))
                done += 1
                progress_cb(done, total_steps, f"拼合帧 {idx + 1}/{placed}…")

            # 保存
            if save_mode == "folder":
                out_dir = os.path.join(gif_dir, base_name + "_frames")
                os.makedirs(out_dir, exist_ok=True)
                for i, frame in enumerate(frames):
                    frame.save(os.path.join(out_dir, f"frame_{i:04d}.png"))
                    done += 1
                    progress_cb(done, total_steps, f"保存帧 {i + 1}/{total}…")
                save_msg = f"已将 {total} 帧保存至:\n{out_dir}"
            else:
                progress_cb(done, total_steps, "保存拼合图…")
                sheet_path = os.path.join(gif_dir, f"{base_name}_sheet.png")
                sheet.save(sheet_path)
                done += 1
                progress_cb(done, total_steps, "保存完成")
                save_msg = f"已保存至:\n{sheet_path}"

            return sheet, placed, cols, rows, save_msg

        def on_done(result, error):
            if error:
                messagebox.showerror("错误", f"导出失败:\n{error}")
                return
            sheet, placed, cols, rows, save_msg = result
            self.result_image = sheet
            msg = (f"共 {total} 帧，已排列 {placed} 帧 ({cols}×{rows})\n"
                   + save_msg)
            self._update_preview(
                on_complete=lambda: messagebox.showinfo("完成", msg))

        self._run_in_thread("导出", worker, on_done)

    # ── 生成预览（异步）──────────────────────────────────────────
    def _update_preview(self, on_complete=None):
        if self._busy:
            if on_complete:
                on_complete()
            return

        if not self.frames:
            if on_complete:
                on_complete()
            return

        # 子文件夹模式：清空预览，显示提示
        if self.save_mode_var.get() == "folder":
            self.preview_hint.config(text="当前为子文件夹模式，不提供拼合预览")
            self.canvas.delete("all")
            self._preview_image = None
            self._preview_photo = None
            self.canvas.configure(scrollregion=(0, 0, 0, 0))
            self.size_info_label.config(text="")
            self.zoom_info_label.config(text="")
            if on_complete:
                on_complete()
            return

        self.preview_hint.config(text="")

        try:
            max_cols = self.max_cols_var.get()
            max_rows = self.max_rows_var.get()
            scale = self.scale_var.get()
        except (tk.TclError, ValueError):
            if on_complete:
                on_complete()
            return

        if max_cols <= 0 or max_rows <= 0 or scale <= 0:
            if on_complete:
                on_complete()
            return

        direction = self.direction_var.get()
        src_frames = list(self.frames)

        def worker(progress_cb):
            total = len(src_frames)
            fw, fh = src_frames[0].size
            fw_s, fh_s = int(fw * scale), int(fh * scale)
            if fw_s <= 0 or fh_s <= 0:
                return None

            if direction == "horizontal":
                cols = min(max_cols, total)
                rows = min(max_rows, -(-total // cols))
            else:
                rows = min(max_rows, total)
                cols = min(max_cols, -(-total // rows))
            placed = min(total, cols * rows)

            scale_steps = total if scale != 1.0 else 0
            total_steps = scale_steps + placed
            done = 0

            if scale != 1.0:
                frames = []
                for i, f in enumerate(src_frames):
                    frames.append(f.resize((fw_s, fh_s), Image.LANCZOS))
                    done += 1
                    progress_cb(done, total_steps, f"缩放帧 {i + 1}/{total}…")
            else:
                frames = src_frames

            sheet = Image.new("RGBA", (cols * fw_s, rows * fh_s), (0, 0, 0, 0))
            for idx, frame in enumerate(frames):
                if direction == "horizontal":
                    r, c = divmod(idx, cols)
                else:
                    c, r = divmod(idx, rows)
                if r >= rows or c >= cols:
                    break
                sheet.paste(frame, (c * fw_s, r * fh_s))
                done += 1
                progress_cb(done, total_steps, f"生成预览 {idx + 1}/{placed}…")

            return sheet

        def on_done_inner(result, error):
            if result is not None:
                self._show_preview(result)
            if on_complete:
                on_complete()

        self._run_in_thread("生成预览", worker, on_done_inner)

    # ── 预览渲染 ──────────────────────────────────────────────
    def _show_preview(self, image):
        self._preview_image = image
        w, h = image.size
        self.size_info_label.config(text=f"实际尺寸:\n{w} × {h}")

        # Fit-to-View：当横纵尺寸都大于 512 时自动缩小适配
        if w > 512 and h > 512:
            cw = self.canvas.winfo_width()
            ch = self.canvas.winfo_height()
            if cw < 2 or ch < 2:
                cw, ch = 520, 400
            self._preview_zoom = min(cw / w, ch / h)
        else:
            self._preview_zoom = 1.0

        self._apply_preview_zoom(Image.LANCZOS)

    def _apply_preview_zoom(self, resample=Image.LANCZOS):
        if self._preview_image is None:
            return
        w, h = self._preview_image.size
        new_w = max(1, int(w * self._preview_zoom))
        new_h = max(1, int(h * self._preview_zoom))

        resized = self._preview_image.resize((new_w, new_h), resample)
        self._preview_photo = ImageTk.PhotoImage(resized)

        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self._preview_photo, anchor=tk.NW)
        self.canvas.configure(scrollregion=(0, 0, new_w, new_h))

        pct = round(self._preview_zoom * 100)
        self.zoom_info_label.config(text=f"预览缩放: {pct}%")

    def _deferred_hq_render(self):
        """滚轮停止后延迟执行的高质量渲染"""
        self._hq_after_id = None
        self._apply_preview_zoom(Image.LANCZOS)

    # ── 鼠标滚轮缩放 ────────────────────────────────────────────
    def _on_mousewheel(self, event):
        if self._preview_image is None or self._busy:
            return

        old_zoom = self._preview_zoom
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        img_x = cx / old_zoom
        img_y = cy / old_zoom

        factor = 1.1 if event.delta > 0 else 1 / 1.1
        new_zoom = max(0.05, min(10.0, old_zoom * factor))
        if new_zoom == old_zoom:
            return
        self._preview_zoom = new_zoom

        # 交互期间用 NEAREST（快速），停止后延迟 LANCZOS（高质量）
        self._apply_preview_zoom(Image.NEAREST)
        if self._hq_after_id is not None:
            self.root.after_cancel(self._hq_after_id)
        self._hq_after_id = self.root.after(200, self._deferred_hq_render)

        # 保持鼠标指向的图像位置不变
        w, h = self._preview_image.size
        new_w = max(1, int(w * new_zoom))
        new_h = max(1, int(h * new_zoom))
        if new_w > 0:
            self.canvas.xview_moveto((img_x * new_zoom - event.x) / new_w)
        if new_h > 0:
            self.canvas.yview_moveto((img_y * new_zoom - event.y) / new_h)

    # ── 拖拽平移 ─────────────────────────────────────────────
    def _on_drag_start(self, event):
        self.canvas.scan_mark(event.x, event.y)
        self.canvas.config(cursor="fleur")

    def _on_drag_move(self, event):
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _on_drag_end(self, event):
        self.canvas.config(cursor="")


if __name__ == "__main__":
    root = tk.Tk()
    GifDividerApp(root)
    root.mainloop()
