#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量抠图换白底 —— macOS GUI 版
运行：python bg_gui.py
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from PIL import Image, ImageFilter, ImageOps, ImageTk

# ---- 可选：拖拽支持 ----
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _HAS_DND = True
except Exception:
    _HAS_DND = False

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".jfif"}
AM_PREFIXES = ("u2net", "silueta")
MODELS = ["u2net", "isnet-general-use", "birefnet-general", "birefnet-portrait",
          "birefnet-general-lite", "isnet-anime", "bria-rmbg", "u2net_human_seg"]
DEVICES = ["CPU", "CoreML (Apple GPU)", "CUDA (NVIDIA)"]


# ============================================================ 抠图核心

_SESSION_LOCK = threading.Lock()
_SESSIONS: dict = {}


def providers_for(device: str):
    if device.startswith("CoreML"):
        return ["CoreMLExecutionProvider", "CPUExecutionProvider"]
    if device.startswith("CUDA"):
        return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    return None


def get_session(model: str, device: str):
    """按 (模型, 设备) 缓存 rembg 会话，避免每张图重复加载。"""
    key = (model, device)
    with _SESSION_LOCK:
        if key not in _SESSIONS:
            from rembg import new_session
            provs = providers_for(device)
            try:
                _SESSIONS[key] = new_session(model, providers=provs) if provs else new_session(model)
            except Exception as e:
                print(f"[warn] {device} 会话创建失败({e})，回退 CPU")
                _SESSIONS[key] = new_session(model)
        return _SESSIONS[key]


def rembg_foreground(im: Image.Image, cfg: dict) -> Image.Image:
    from rembg import remove

    full_size = im.size
    work = im
    if cfg["max_size"] and max(full_size) > cfg["max_size"]:
        work = im.copy()
        work.thumbnail((cfg["max_size"], cfg["max_size"]), Image.LANCZOS)

    kwargs = {"session": get_session(cfg["model"], cfg["device"]),
              "post_process_mask": cfg["post_process"]}
    if cfg["alpha_matting"]:
        kwargs.update(alpha_matting=True,
                      alpha_matting_foreground_threshold=cfg["am_fg"],
                      alpha_matting_background_threshold=cfg["am_bg"],
                      alpha_matting_erode_size=cfg["am_erode"])
    try:
        res = remove(work, **kwargs)
    except TypeError:
        kwargs.pop("post_process_mask", None)
        res = remove(work, **kwargs)

    if isinstance(res, (bytes, bytearray)):
        import io
        res = Image.open(io.BytesIO(res))
    res = res.convert("RGBA")

    if res.size != full_size:                        # alpha 放大回原分辨率
        alpha = res.getchannel("A").resize(full_size, Image.LANCZOS)
        res = im.convert("RGBA")
        res.putalpha(alpha)
    return res


def finalize(fg: Image.Image, cfg: dict) -> Image.Image:
    alpha = fg.getchannel("A")
    if cfg["erode"] > 0:
        alpha = alpha.filter(ImageFilter.MinFilter(cfg["erode"] * 2 + 1))
    if cfg["feather"] > 0:
        alpha = alpha.filter(ImageFilter.GaussianBlur(cfg["feather"]))

    fg = fg.copy()
    fg.putalpha(alpha)

    if cfg["trim"]:
        bbox = alpha.getbbox()
        if bbox:
            fg = fg.crop(bbox)

    w, h = fg.size
    m = cfg["margin"]
    if cfg["square"]:
        side = max(1, int(round(max(w, h) * (1 + 2 * m))))
        canvas_size = (side, side)
    elif m > 0:
        canvas_size = (max(1, int(round(w * (1 + 2 * m)))),
                       max(1, int(round(h * (1 + 2 * m)))))
    else:
        canvas_size = (w, h)

    base = (0, 0, 0, 0) if cfg["transparent"] else cfg["bg_rgb"] + (255,)
    canvas = Image.new("RGBA", canvas_size, base)
    canvas.alpha_composite(fg, ((canvas_size[0] - w) // 2, (canvas_size[1] - h) // 2))

    if cfg["transparent"]:
        return canvas
    flat = Image.new("RGB", canvas_size, cfg["bg_rgb"])
    flat.paste(canvas, mask=canvas.getchannel("A"))
    return flat


def process_one(src: Path, dst: Path, cfg: dict):
    cancel = cfg.get("cancel")
    try:
        if cancel is not None and cancel.is_set():
            return src, dst, "cancel", ""
        if dst.exists() and not cfg["overwrite"]:
            return src, dst, "skip", ""

        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im).convert("RGBA")
            fg = rembg_foreground(im, cfg)
        out = finalize(fg, cfg)

        dst.parent.mkdir(parents=True, exist_ok=True)
        suffix = dst.suffix.lower()
        if suffix in (".jpg", ".jpeg"):
            out.convert("RGB").save(dst, quality=cfg["quality"], subsampling=0, optimize=True)
        elif suffix == ".webp":
            out.save(dst, quality=cfg["quality"], method=4)
        else:
            out.save(dst, optimize=True)
        return src, dst, "ok", ""
    except Exception as e:
        return src, dst, "fail", f"{type(e).__name__}: {e}"


def collect_images(path: Path, recursive: bool) -> list:
    if path.is_file():
        return [path] if path.suffix.lower() in IMAGE_EXTS else []
    it = path.rglob("*") if recursive else path.glob("*")
    return sorted(p for p in it if p.is_file() and p.suffix.lower() in IMAGE_EXTS)


def dst_for(src: Path, base: Path, out_dir: Path, from_dir: bool, ext: str) -> Path:
    if from_dir:
        return out_dir / src.relative_to(base).with_suffix(ext)
    return out_dir / (src.stem + ext)


def load_thumb(path: Path, box: int = 250, bg=(245, 245, 245, 255)):
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGBA")
        im.thumbnail((box, box), Image.LANCZOS)
        canvas = Image.new("RGBA", im.size, bg)
        canvas.alpha_composite(im)
        return ImageTk.PhotoImage(canvas.convert("RGB"))


# ============================================================ GUI

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("批量抠图换白底")
        root.geometry("980x860")
        root.minsize(880, 720)

        self.q = queue.Queue()
        self.cancel_event = threading.Event()
        self.running = False
        self.picked_files: list = []
        self.bg_rgb = (255, 255, 255)
        self._thumbs = []
        self.settings_path = Path.home() / ".batch_bg2white_gui.json"

        self._build_vars()
        self._build_ui()
        self._load_settings()
        self._install_dnd()

        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(80, self._poll)

    # ---------------- 变量
    def _build_vars(self):
        v = tk.StringVar
        self.var_input = v(value="")
        self.var_output = v(value=str(Path.home() / "Desktop" / "抠图输出"))
        self.var_model = v(value="u2net")
        self.var_device = v(value="CPU")
        self.var_format = v(value="jpg")
        self.var_workers = v(value="1")
        self.var_maxsize = v(value="0")
        self.var_quality = v(value="95")
        self.var_erode = v(value="1")
        self.var_feather = v(value="0")
        self.var_margin = v(value="0")
        self.var_transparent = tk.BooleanVar(value=False)
        self.var_square = tk.BooleanVar(value=False)
        self.var_recursive = tk.BooleanVar(value=False)
        self.var_overwrite = tk.BooleanVar(value=False)
        self.var_am = tk.BooleanVar(value=False)
        self.var_post = tk.BooleanVar(value=False)

    # ---------------- 界面
    def _build_ui(self):
        pad = dict(padx=6, pady=4)

        # ---- 路径
        top = ttk.LabelFrame(self.root, text="路径")
        top.pack(fill="x", padx=10, pady=(10, 6))
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="输入").grid(row=0, column=0, sticky="e", **pad)
        ttk.Entry(top, textvariable=self.var_input).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(top, text="选择文件夹", command=self._pick_dir).grid(row=0, column=2, **pad)
        ttk.Button(top, text="选择图片", command=self._pick_files).grid(row=0, column=3, **pad)

        ttk.Label(top, text="输出").grid(row=1, column=0, sticky="e", **pad)
        ttk.Entry(top, textvariable=self.var_output).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(top, text="选择文件夹", command=self._pick_out).grid(row=1, column=2, **pad)
        ttk.Button(top, text="打开", command=self._open_out).grid(row=1, column=3, **pad)

        hint = ("把文件夹或图片直接拖进窗口即可" if _HAS_DND
                else "pip install tkinterdnd2 后支持拖拽文件")
        ttk.Label(top, text="提示：" + hint, foreground="#8a8a8a").grid(
            row=2, column=1, columnspan=3, sticky="w", padx=6)

        # ---- 参数
        pf = ttk.LabelFrame(self.root, text="参数")
        pf.pack(fill="x", padx=10, pady=6)
        pf.columnconfigure(1, weight=1)
        pf.columnconfigure(3, weight=1)

        def add(row, col, text, widget):
            ttk.Label(pf, text=text).grid(row=row, column=col * 2, sticky="e", padx=(10, 4), pady=4)
            widget.grid(row=row, column=col * 2 + 1, sticky="ew", padx=(0, 10), pady=4)

        add(0, 0, "模型", ttk.Combobox(pf, textvariable=self.var_model,
                                     values=MODELS, state="readonly"))
        add(0, 1, "推理设备", ttk.Combobox(pf, textvariable=self.var_device,
                                       values=DEVICES, state="readonly"))
        add(1, 0, "输出格式", ttk.Combobox(pf, textvariable=self.var_format,
                                       values=["jpg", "png", "webp"], state="readonly"))
        add(1, 1, "并行线程", ttk.Spinbox(pf, from_=1, to=8, textvariable=self.var_workers))
        add(2, 0, "背景色", ttk.Button(pf, text="选择颜色", command=self._pick_color))
        add(2, 1, "推理长边(0=原图)", ttk.Spinbox(pf, from_=0, to=8000, increment=100,
                                             textvariable=self.var_maxsize))
        add(3, 0, "去除白边(0-4)", ttk.Spinbox(pf, from_=0, to=4, textvariable=self.var_erode))
        add(3, 1, "边缘羽化(0-3)", ttk.Spinbox(pf, from_=0, to=3, increment=0.5,
                                          textvariable=self.var_feather))
        add(4, 0, "留白比例(0-0.5)", ttk.Spinbox(pf, from_=0, to=0.5, increment=0.01,
                                            textvariable=self.var_margin))
        add(4, 1, "JPG 质量", ttk.Spinbox(pf, from_=60, to=100, textvariable=self.var_quality))

        self.swatch = tk.Label(pf, text="  纯白  ", bg="#FFFFFF", relief="solid", bd=1)
        self.swatch.grid(row=2, column=0, columnspan=2, sticky="w", padx=(120, 0))

        chk = ttk.Frame(pf)
        chk.grid(row=5, column=0, columnspan=4, sticky="w", padx=10, pady=(6, 8))
        for txt, var in [("透明底(PNG)", self.var_transparent),
                         ("正方形白底", self.var_square),
                         ("递归子目录", self.var_recursive),
                         ("覆盖已存在", self.var_overwrite),
                         ("alpha matting", self.var_am),
                         ("mask 后处理", self.var_post)]:
            ttk.Checkbutton(chk, text=txt, variable=var).pack(side="left", padx=8)

        # ---- 操作栏
        act = ttk.Frame(self.root)
        act.pack(fill="x", padx=10, pady=(0, 6))
        self.btn_start = ttk.Button(act, text="▶  开始处理", command=self.start)
        self.btn_start.pack(side="left")
        self.btn_stop = ttk.Button(act, text="■  停止", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=6)
        ttk.Button(act, text="恢复默认", command=self._reset).pack(side="left", padx=6)
        ttk.Button(act, text="清空日志", command=self._clear_log).pack(side="left")

        self.progress = ttk.Progressbar(act, mode="determinate", length=240)
        self.progress.pack(side="right", padx=8)
        self.lbl_status = ttk.Label(act, text="就绪")
        self.lbl_status.pack(side="right")

        # ---- 预览
        pv = ttk.LabelFrame(self.root, text="预览（左：原图 / 右：结果）")
        pv.pack(fill="x", padx=10, pady=4)
        self.lbl_orig = ttk.Label(pv, text="原图", anchor="center", width=36)
        self.lbl_orig.pack(side="left", expand=True, pady=8)
        ttk.Separator(pv, orient="vertical").pack(side="left", fill="y", pady=6)
        self.lbl_out = ttk.Label(pv, text="结果", anchor="center", width=36)
        self.lbl_out.pack(side="left", expand=True, pady=8)

        # ---- 日志
        lf = ttk.LabelFrame(self.root, text="日志")
        lf.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self.txt = tk.Text(lf, height=10, wrap="none",
                           font=("Menlo", 11) if sys.platform == "darwin" else ("Consolas", 10))
        sb = ttk.Scrollbar(lf, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set, state="disabled")
        sb.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)

    # ---------------- 拖拽
    def _install_dnd(self):
        if not _HAS_DND:
            return
        for w in (self.root,):
            w.drop_target_register(DND_FILES)
            w.dnd_bind("<<Drop>>", self._on_drop)

    def _on_drop(self, event):
        paths = [Path(p) for p in self.root.tk.splitlist(event.data)]
        dirs = [p for p in paths if p.is_dir()]
        files = [p for p in paths if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
        if dirs:
            self.picked_files = []
            self.var_input.set(str(dirs[0]))
            self._log(f"输入目录：{dirs[0]}")
        elif files:
            self.picked_files = sorted(files)
            self.var_input.set(f"已选择 {len(files)} 张图片")
            self._log(f"已选择 {len(files)} 张图片")

    # ---------------- 浏览
    def _pick_dir(self):
        p = filedialog.askdirectory(title="选择图片文件夹")
        if p:
            self.picked_files = []
            self.var_input.set(p)

    def _pick_files(self):
        ps = filedialog.askopenfilenames(
            title="选择图片",
            filetypes=[("图片", "*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff")])
        if ps:
            self.picked_files = sorted(Path(p) for p in ps)
            self.var_input.set(f"已选择 {len(ps)} 张图片")

    def _pick_out(self):
        p = filedialog.askdirectory(title="选择输出文件夹")
        if p:
            self.var_output.set(p)

    def _pick_color(self):
        rgb, _ = colorchooser.askcolor(color="#%02X%02X%02X" % self.bg_rgb,
                                       title="选择背景色")
        if rgb:
            self.bg_rgb = tuple(int(c) for c in rgb)
            self.swatch.configure(bg="#%02X%02X%02X" % self.bg_rgb)

    def _open_out(self):
        p = Path(self.var_output.get()).expanduser()
        if p.exists():
            if sys.platform == "darwin":
                subprocess.run(["open", str(p)])
            elif os.name == "nt":
                os.startfile(str(p))  # type: ignore[attr-defined]
            else:
                subprocess.run(["xdg-open", str(p)])
        else:
            messagebox.showinfo("提示", "输出目录还不存在")

    # ---------------- 开始 / 停止
    def collect_cfg(self) -> dict:
        fmt = self.var_format.get()
        transparent = self.var_transparent.get()
        model = self.var_model.get()
        ext = ".png" if transparent else "." + fmt
        return {
            "model": model,
            "device": self.var_device.get(),
            "alpha_matting": self.var_am.get() and model.startswith(AM_PREFIXES),
            "am_fg": 240, "am_bg": 10, "am_erode": 10,
            "post_process": self.var_post.get(),
            "max_size": int(float(self.var_maxsize.get() or 0)),
            "bg_rgb": self.bg_rgb,
            "erode": int(float(self.var_erode.get() or 0)),
            "feather": float(self.var_feather.get() or 0),
            "trim": True,
            "square": self.var_square.get(),
            "margin": float(self.var_margin.get() or 0),
            "transparent": transparent,
            "quality": int(float(self.var_quality.get() or 95)),
            "overwrite": self.var_overwrite.get(),
            "ext": ext,
            "recursive": self.var_recursive.get(),
            "workers": max(1, int(float(self.var_workers.get() or 1))),
            "cancel": self.cancel_event,
        }

    def start(self):
        if self.running:
            return
        out_dir = Path(self.var_output.get()).expanduser()
        if not self.var_output.get().strip():
            messagebox.showerror("错误", "请先选择输出目录")
            return

        if self.picked_files:
            files = [f for f in self.picked_files if f.exists()]
            in_path = files[0].parent if files else out_dir
        else:
            raw = self.var_input.get().strip()
            if not raw:
                messagebox.showerror("错误", "请先选择输入文件夹或图片")
                return
            in_path = Path(raw).expanduser()
            if not in_path.exists():
                messagebox.showerror("错误", f"输入路径不存在：\n{in_path}")
                return
            files = collect_images(in_path, self.var_recursive.get())

        if not files:
            messagebox.showwarning("提示", "没有找到可处理的图片")
            return

        cfg = self.collect_cfg()
        if self.var_am.get() and not cfg["alpha_matting"]:
            self._log(f"[提示] 模型 {cfg['model']} 自带软边 alpha，已忽略 alpha matting")

        self.cancel_event.clear()
        self.running = True
        self.progress.configure(maximum=len(files), value=0)
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.lbl_status.configure(text="准备中…")
        self._log(f"==== 共 {len(files)} 张，模型 {cfg['model']} / {cfg['device']} ====")

        threading.Thread(target=self._worker,
                         args=(files, in_path, out_dir, cfg), daemon=True).start()

    def stop(self):
        if self.running:
            self.cancel_event.set()
            self.btn_stop.configure(state="disabled")
            self._log("已请求停止，正在结束当前图片…")

    # ---------------- 后台处理
    def _worker(self, files, in_path: Path, out_dir: Path, cfg: dict):
        stats = {"ok": 0, "skip": 0, "fail": 0, "cancel": 0}
        problems = []
        from_dir = in_path.is_dir()
        base = in_path if from_dir else in_path.parent
        done = 0

        try:
            with ThreadPoolExecutor(max_workers=cfg["workers"]) as ex:
                futures = {}
                for f in files:
                    if self.cancel_event.is_set():
                        break
                    dst = dst_for(f, base, out_dir, from_dir, cfg["ext"])
                    futures[ex.submit(process_one, f, dst, cfg)] = f

                for fut in as_completed(futures):
                    try:
                        src, dst, status, msg = fut.result()
                    except Exception:
                        src = futures[fut]
                        status, msg = "fail", traceback.format_exc(limit=1)
                    done += 1
                    stats[status] = stats.get(status, 0) + 1
                    if status == "fail":
                        problems.append((src, msg))
                        self.q.put(("log", f"✗ {src.name}：{msg}"))
                    elif status == "skip":
                        self.q.put(("log", f"- 跳过（已存在）{src.name}"))
                    elif status == "ok":
                        self.q.put(("preview", str(src), str(dst)))
                    self.q.put(("progress", done, len(files)))
        except Exception:
            self.q.put(("log", "严重错误：\n" + traceback.format_exc()))
        finally:
            self.q.put(("done", stats, problems))

    # ---------------- 主线程轮询
    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self._log(msg[1])
                elif kind == "progress":
                    done, total = msg[1], msg[2]
                    self.progress.configure(value=done)
                    self.lbl_status.configure(text=f"{done}/{total}")
                elif kind == "preview":
                    self._show_preview(msg[1], msg[2])
                elif kind == "done":
                    self._finish(msg[1], msg[2])
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    def _show_preview(self, src, dst):
        try:
            t1 = load_thumb(Path(src), 250, (238, 238, 238, 255))
            t2 = load_thumb(Path(dst), 250, (255, 255, 255, 255) if not self.var_transparent.get()
                            else (230, 230, 230, 255))
            self._thumbs = [t1, t2]
            self.lbl_orig.configure(image=t1, text="")
            self.lbl_out.configure(image=t2, text="")
            self.lbl_status.configure(text=f"已处理：{Path(dst).name}")
        except Exception as e:
            self._log(f"[预览失败] {e}")

    def _finish(self, stats, problems):
        self.running = False
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.lbl_status.configure(text="完成")
        self._log(f"==== 完成：成功 {stats.get('ok',0)}，跳过 {stats.get('skip',0)}，"
                  f"失败 {stats.get('fail',0)}，取消 {stats.get('cancel',0)} ====")
        if problems and not self.cancel_event.is_set():
            messagebox.showwarning("部分失败", f"{len(problems)} 张图片处理失败，详见日志。")

    # ---------------- 日志 / 设置
    def _log(self, text: str):
        self.txt.configure(state="normal")
        self.txt.insert("end", text + "\n")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _clear_log(self):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")

    def _reset(self):
        self.var_model.set("u2net")
        self.var_device.set("CPU")
        self.var_format.set("jpg")
        self.var_workers.set("1")
        self.var_maxsize.set("0")
        self.var_quality.set("95")
        self.var_erode.set("1")
        self.var_feather.set("0")
        self.var_margin.set("0")
        for v in (self.var_transparent, self.var_square, self.var_recursive,
                  self.var_overwrite, self.var_am, self.var_post):
            v.set(False)
        self.bg_rgb = (255, 255, 255)
        self.swatch.configure(bg="#FFFFFF")

    def _settings(self) -> dict:
        return {
            "output": self.var_output.get(), "model": self.var_model.get(),
            "device": self.var_device.get(), "format": self.var_format.get(),
            "workers": self.var_workers.get(), "maxsize": self.var_maxsize.get(),
            "quality": self.var_quality.get(), "erode": self.var_erode.get(),
            "feather": self.var_feather.get(), "margin": self.var_margin.get(),
            "bg_rgb": list(self.bg_rgb),
            "transparent": self.var_transparent.get(), "square": self.var_square.get(),
            "recursive": self.var_recursive.get(), "overwrite": self.var_overwrite.get(),
            "am": self.var_am.get(), "post": self.var_post.get(),
        }

    def _load_settings(self):
        try:
            d = json.loads(self.settings_path.read_text("utf-8"))
        except Exception:
            return
        mapping = {
            "output": self.var_output, "model": self.var_model, "device": self.var_device,
            "format": self.var_format, "workers": self.var_workers,
            "maxsize": self.var_maxsize, "quality": self.var_quality,
            "erode": self.var_erode, "feather": self.var_feather,
            "margin": self.var_margin,
        }
        for k, var in mapping.items():
            if d.get(k):
                var.set(str(d[k]))
        for k, var in [("transparent", self.var_transparent), ("square", self.var_square),
                       ("recursive", self.var_recursive), ("overwrite", self.var_overwrite),
                       ("am", self.var_am), ("post", self.var_post)]:
            var.set(bool(d.get(k, False)))
        if d.get("bg_rgb"):
            self.bg_rgb = tuple(d["bg_rgb"])
            self.swatch.configure(bg="#%02X%02X%02X" % self.bg_rgb)

    def _on_close(self):
        if self.running:
            if not messagebox.askyesno("确认", "正在处理中，确定要退出吗？"):
                return
            self.cancel_event.set()
        try:
            self.settings_path.write_text(
                json.dumps(self._settings(), ensure_ascii=False, indent=2), "utf-8")
        except Exception:
            pass
        self.root.destroy()


def main():
    root = TkinterDnD.Tk() if _HAS_DND else tk.Tk()
    try:
        if sys.platform == "darwin":
            root.tk.call("tk", "windowingsystem")  # 触发原生主题
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
