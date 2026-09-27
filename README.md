# 批量抠图换白底 GUI

一个基于 Python、Tkinter 和 rembg 的本地批量抠图工具，可一键去除图片背景，并替换为白底、自定义背景色或透明底。支持拖拽导入、原图/结果预览、多线程处理、多种 AI 模型以及 CPU / Apple CoreML / NVIDIA CUDA 推理。

处理过程全部在本机完成，不需要把图片上传到云端。

---

## 功能特性

- 批量处理整个文件夹或手动选择的图片
- 支持拖拽文件或文件夹到窗口
- 支持多种 AI 抠图模型：
  - `u2net`
  - `isnet-general-use`
  - `birefnet-general`
  - `birefnet-portrait`
  - `birefnet-general-lite`
  - `isnet-anime`
  - `bria-rmbg`
  - `u2net_human_seg`
- 支持输出白底、自定义背景色、透明底
- 支持 JPG、PNG、WebP 输出
- 支持 JPG 质量调节
- 支持正方形白底、留白比例调整
- 支持去除白边、边缘羽化、alpha matting
- 支持 mask 后处理
- 支持 CPU、Apple CoreML、NVIDIA CUDA 推理
- 支持多线程并行处理
- 支持递归处理子目录
- 支持覆盖已存在文件
- 支持原图 / 结果预览
- 支持进度条、日志、停止处理
- 自动保存用户设置

---

## 适用场景

- 电商商品图批量换白底
- 头像、证件照、人像图换背景
- 设计素材批量去背景
- 自媒体图片素材整理
- 需要透明底 PNG 的批量处理任务

---

## 环境要求

- Python 3.9+
- 操作系统：macOS / Windows / Linux
- Tkinter
- 可选：NVIDIA GPU / Apple Silicon CoreML

---

## 安装依赖

### 1. 创建虚拟环境

macOS / Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Windows：

```bash
python -m venv .venv
.venv\Scripts\activate
```

### 2. 安装 Python 依赖

```bash
python -m pip install -U pip
python -m pip install -U pillow rembg onnxruntime tkinterdnd2 pymatting
```

### 3. macOS 如果 Tkinter 不可用

```bash
brew install python-tk
```

### 4. 如果需要 NVIDIA GPU 加速

```bash
python -m pip install -U "rembg[gpu]"
```

---

## 运行方式

```bash
python beijing.py
```

---

## 使用说明

1. 选择输入文件夹，或直接选择多张图片。
2. 选择输出文件夹。
3. 选择模型和推理设备。
4. 设置输出格式、背景色、并行线程等参数。
5. 点击“开始处理”。
6. 在预览区查看原图和结果，在日志区查看处理状态。
7. 处理完成后可点击“打开”进入输出目录。

也可以直接把文件夹或图片拖进窗口。

---

## 参数说明

| 参数 | 说明 | 默认值 | 范围 / 选项 |
|---|---|---|---|
| 模型 | 选择 AI 抠图模型 | `u2net` | 见上方模型列表 |
| 推理设备 | 选择推理后端 | `CPU` | CPU / CoreML / CUDA |
| 输出格式 | 结果保存格式 | `jpg` | jpg / png / webp |
| 并行线程 | 同时处理的图片数量 | `1` | 1 - 8 |
| 背景色 | 非透明背景颜色 | 白色 | 颜色选择器 |
| 推理长边 | 限制推理尺寸，0 表示原图 | `0` | 0 - 8000 |
| 去除白边 | 对 alpha 做腐蚀，减少白边 | `1` | 0 - 4 |
| 边缘羽化 | 对 alpha 做高斯模糊 | `0` | 0 - 3 |
| 留白比例 | 前景周围留白比例 | `0` | 0 - 0.5 |
| JPG 质量 | JPG 保存质量 | `95` | 60 - 100 |
| 透明底 | 输出透明背景 PNG | 关闭 | 开 / 关 |
| 正方形白底 | 输出正方形画布 | 关闭 | 开 / 关 |
| 递归子目录 | 递归处理输入目录 | 关闭 | 开 / 关 |
| 覆盖已存在 | 覆盖输出目录已有文件 | 关闭 | 开 / 关 |
| alpha matting | 启用软边抠图 | 关闭 | 仅部分模型生效 |
| mask 后处理 | 启用 rembg mask 后处理 | 关闭 | 开 / 关 |

---

## 输出规则

- 勾选“透明底”时，输出格式自动变为 PNG。
- 未勾选“透明底”时，按选择的输出格式保存。
- 程序会自动裁剪前景区域，然后按“留白比例”或“正方形白底”扩展画布。
- JPG 输出会去除透明通道并使用指定质量保存。
- WebP 输出会使用指定质量保存。

---

## 支持图片格式

```text
.jpg .jpeg .png .webp .bmp .tif .tiff .jfif
```

---

## 依赖列表

### 必需依赖

- Pillow
- rembg
- onnxruntime
- Tkinter

### 可选依赖

- `tkinterdnd2`：启用拖拽功能
- `pymatting`：启用 alpha matting 软边处理
- `onnxruntime-gpu`：启用 NVIDIA CUDA 加速

---

## requirements.txt 示例

```txt
pillow
rembg
onnxruntime
tkinterdnd2
pymatting
```

如果需要 GPU 加速，可将 `onnxruntime` 替换为 `onnxruntime-gpu`，或使用：

```txt
rembg[gpu]
```

---

## 注意事项

- 首次运行需要联网下载模型，模型会缓存到本地。
- CPU 推理速度较慢，图片多时建议根据机器性能选择合适模型。
- CoreML 或 CUDA 初始化失败时，程序会自动回退 CPU。
- `alpha matting` 只对 `u2net`、`silueta` 等部分模型生效。
- `bria-rmbg` 模型商用前请确认其许可证要求。
- 处理大量图片时建议适当调整并行线程数，避免内存占用过高。
- 用户设置会自动保存到 `~/.batch_bg2white_gui.json`。

---

## 常见问题

### 拖拽无效？

安装拖拽支持：

```bash
python -m pip install tkinterdnd2
```

### 报错 `No module named tkinter`？

macOS：

```bash
brew install python-tk
```

Ubuntu / Debian：

```bash
sudo apt install python3-tk
```

### 模型下载慢？

首次运行会自动下载模型，取决于网络环境。模型通常缓存在 `~/.u2net` 或 `~/.cache/rembg`。

### CUDA 不可用？

请确认已安装 GPU 版 onnxruntime，并检查 NVIDIA 驱动和 CUDA 环境。

### alpha matting 没有生效？

`alpha matting` 只对部分模型生效，例如 `u2net` 前缀模型。其他模型自带软边 alpha，程序会忽略该选项。

---

## 项目结构

```text
.
├── beijing.py
├── README.md
```

---

## 致谢

- [rembg](https://github.com/danielgatis/rembg)
- [Pillow](https://python-pillow.org/)
- [Tkinter](https://docs.python.org/3/library/tkinter.html)
- [tkinterdnd2](https://github.com/pmgagne/tkinterdnd2)
- [onnxruntime](https://onnxruntime.ai/)

---
