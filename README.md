# Kaipai Talking Head Skill

一个用于 Codex 的竖屏真人口播剪辑技能。它将原始口播整理成开拍软件风格的短视频：中英双语字幕、默认 1.1 倍速、顶部钩子、单张信息卡、结尾 CTA，以及独立封面。

GitHub：<https://github.com/yikang329-droid/kaipai-talking-head-skill>

## 安装

使用 Codex 的 skill installer 安装本 GitHub 仓库，或将仓库目录放到：

```text
$CODEX_HOME/skills/kaipai-talking-head
```

Windows 手动安装：

```powershell
git clone https://github.com/yikang329-droid/kaipai-talking-head-skill "$env:USERPROFILE\.codex\skills\kaipai-talking-head"
```

安装后可直接调用：

```text
使用 $kaipai-talking-head 剪这个口播视频，并生成中英双语成片和封面。
```

## 依赖

- FFmpeg 与 ffprobe
- Python 3.10+
- Node.js 22+ 与 HyperFrames（使用 HTML 视频合成时）

安装 Python 依赖并确认媒体工具可用：

```powershell
python -m pip install -r requirements.txt
ffmpeg -version
ffprobe -version
```

封面脚本依赖 Pillow；未安装时会直接给出安装提示。

仓库内置 Noto Sans SC 字体，许可见 `assets/fonts/OFL.txt`。技能默认不会上传原视频、转写、字幕或成片；仓库的 `.gitignore` 也会忽略常见媒体输出。

本项目是独立的工作流封装，与“开拍”软件官方无隶属或授权关系。
