# [NCM-Fingerprint-Tagger]

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)

一个强大的命令行工具，使用音频指纹技术自动识别本地音乐文件，并从网易云音乐获取并写入正确的元数据（标题、艺术家、专辑）。

A powerful command-line tool to automatically identify local music files using audio fingerprinting and write correct metadata (Title, Artist, Album) fetched from NetEase Cloud Music.

## ✨ 核心功能 (Features)

-   **精准识别**: 基于音频指纹技术，即使文件名错误也能识别歌曲。
-   **自动写入**: 自动获取歌曲的 **标题、艺术家、专辑** 信息并更新到文件标签。
-   **批量处理**: 支持处理单个文件或整个文件夹。
-   **高成功率**: 可配置多次分段识别，提高识别成功率。
-   **跨平台**: 支持 Windows 和 Linux 系统。
-   **格式广泛**: 支持 MP3, FLAC, M4A, WAV, OGG 等多种主流音频格式。

## ⚙️ 环境要求 (Requirements)

1.  **Python 3.8+**
2.  **FFmpeg**: 必须安装并已添加到系统的 PATH 环境变量中。
    -   访问 [ffmpeg.org](https://ffmpeg.org/download.html) 下载。
    -   在 Linux (Ubuntu/Debian) 上: `sudo apt update && sudo apt install ffmpeg`

## 🚀 安装 (Installation)

1.  克隆本仓库:
    ```bash
    git clone https://github.com/your-username/[YourProjectName].git
    cd [YourProjectName]
    ```

2.  安装 Python 依赖:
    ```bash
    pip install -r requirements.txt
    ```
    *(你需要创建一个 `requirements.txt` 文件，内容如下:)*
    ```
    pyncm
    mutagen
    pythonmonkey
    ```

## 📝 使用方法 (Usage)

所有操作都在命令行中完成。

### 基本语法
```bash
python tag_updater.py <文件或文件夹路径> [选项]
```

### 示例

**1. 处理单个文件 (默认尝试3次识别):**
```bash
python tag_updater.py "/path/to/your/song.mp3"
```

**2. 处理整个文件夹:**
```bash
python tag_updater.py "/path/to/your/music_folder"
```

**3. 提高识别成功率 (尝试10次分段识别):**
```bash
python tag_updater.py "/path/to/your/music_folder" --segments 10
```
或者使用短命令:
```bash
python tag_updater.py "/path/to/your/music_folder" -n 10
```

**4. 自定义写入的标签 (只写入标题和专辑):**
```bash
python tag_updater.py "/path/to/your/song.flac" --tags title album
```
或者使用短命令:
```bash
python tag_updater.py "/path/to/your/song.flac" -t title album
```


## 感谢
[mos9527/ncm-afp: 网易云音乐听歌识曲 API Demo](https://github.com/mos9527/ncm-afp)

[mos9527/pyncm: 第三方网易云音乐 Python API + 转储工具](https://github.com/mos9527/pyncm)

