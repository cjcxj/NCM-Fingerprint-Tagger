# audio_fingerprint.py

"""
音频指纹生成模块

本模块提供了从音频文件生成指纹的核心功能。它依赖于 ffmpeg 进行音频处理，
并通过 pythonmonkey 调用一个 JavaScript 库 (afp.js) 来计算指纹。

主要功能:
- generate_fingerprint_from_file(file_path, start_time=0): 从指定音频文件生成指纹。

依赖:
- pythonmonkey: 用于执行 JavaScript 代码。
- pyncm (可选，仅用于示例): 用于演示如何使用指纹。
- ffmpeg: 必须安装在系统中，并且其路径在 PATH 环境变量中。

使用示例 (作为库导入):
    try:
        from audio_fingerprint import generate_fingerprint_from_file

        file_path = "path/to/your/music.mp3"
        fingerprint = generate_fingerprint_from_file(file_path, start_time=30)
        print(f"生成的指纹是: {fingerprint}")

    except FileNotFoundError:
        print("错误: ffmpeg 未安装或不在系统 PATH 中。")
    except Exception as e:
        print(f"发生错误: {e}")

命令行用法:
    python audio_fingerprint.py "path/to/your/music.mp3"

参考：https://github.com/mos9527/ncm-afp
"""

import asyncio
import subprocess
import sys
from struct import unpack
from typing import List

# 使用 try-except 来处理导入，使得在不运行示例的情况下，pyncm 不是必需的
try:
    from pythonmonkey import require
    from pyncm.apis.track import GetMatchTrackByFP
    from pprint import pprint

    _PYNCM_AVAILABLE = True
except ImportError:
    _PYNCM_AVAILABLE = False

# --------------------------------------------------------------------------
# 模块级常量 (配置)
# --------------------------------------------------------------------------
FINGERPRINT_DURATION: int = 3  # 指纹计算所需的音频时长（秒）
FINGERPRINT_SAMPLERATE: int = 8000  # 音频采样率 (Hz)
FINGERPRINT_SAMPLECOUNT: int = FINGERPRINT_DURATION * FINGERPRINT_SAMPLERATE  # 总样本数


# --------------------------------------------------------------------------
# 内部辅助函数 (私有)
# --------------------------------------------------------------------------

def _generate_fingerprint_js(sample: List[float]) -> str:
    """
    [内部函数] 调用 JS 库生成指纹的核心实现。

    使用一个新的事件循环来运行异步JS代码，以避免与外部可能存在的
    事件循环冲突。
    """
    # 确保样本数量正确
    assert len(sample) == FINGERPRINT_SAMPLECOUNT, \
        f'期望 {FINGERPRINT_SAMPLECOUNT} 个样本, 但收到了 {len(sample)}'

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def run():
        # 注意: afp.js 的路径是相对于执行此脚本的位置。
        # 在实际部署中，可能需要更可靠的路径解析方法。
        afp_js = require('./docs/afp.js')
        return await afp_js.GenerateFP(sample)

    try:
        fingerprint = loop.run_until_complete(run())
    finally:
        loop.close()

    return fingerprint


# --------------------------------------------------------------------------
# 公共 API 函数
# --------------------------------------------------------------------------

def generate_fingerprint_from_file(file_path: str, start_time: int = 0) -> str:
    """
    从指定的音频文件生成音频指纹。

    此函数通过调用 ffmpeg 将音频文件解码并重采样为 32位浮点、8000Hz、
    单声道的 PCM 数据流，然后使用 afp.js 库计算并返回音频指纹。

    Args:
        file_path (str): 音频文件的路径。
        start_time (int): 从音频的第几秒开始截取片段进行指纹识别。默认为 0。

    Returns:
        str: Base64 编码的音频指纹字符串。

    Raises:
        FileNotFoundError: 如果 ffmpeg 命令不存在。
        subprocess.CalledProcessError: 如果 ffmpeg 执行失败（例如，文件损坏或格式不支持）。
        ValueError: 如果 ffmpeg 没有输出任何有效的音频数据。
        RuntimeError: 如果 pythonmonkey 或 afp.js 加载失败。
    """
    if not _PYNCM_AVAILABLE:
        # pyncm 包含了 pythonmonkey，如果它不可用，则核心功能也无法使用。
        raise RuntimeError("核心依赖 'pythonmonkey' 未安装。请执行 'pip install pyncm' 或 'pip install pythonmonkey'。")

    print(f"[*] 正在为文件生成指纹: {file_path} (开始时间: {start_time}s)")

    # 构建 ffmpeg 命令
    ffmpeg_command = [
        'ffmpeg',
        '-nostdin',  # 避免从 stdin 读取，增加稳定性
        '-i', file_path,
        '-ss', str(start_time),
        '-t', str(FINGERPRINT_DURATION),
        '-acodec', 'pcm_f32le',
        '-f', 'f32le',
        '-ar', str(FINGERPRINT_SAMPLERATE),
        '-ac', '1',
        '-'  # 输出到 stdout
    ]

    # 执行 ffmpeg 并捕获输出
    process = subprocess.run(
        ffmpeg_command,
        capture_output=True,
        check=True  # 如果 ffmpeg 返回非零退出码，将引发 CalledProcessError
    )
    buffer = process.stdout

    if not buffer:
        raise ValueError(f"ffmpeg 未能从 '{file_path}' 生成任何音频数据。请检查文件是否有效且长度足够。")

    print(f"[*] ffmpeg 成功转换，接收到 {len(buffer)} 字节数据。")

    # 解包二进制数据为浮点数列表
    bytes_expected = FINGERPRINT_SAMPLECOUNT * 4  # 32-bit float is 4 bytes
    actual_sample_count = len(buffer) // 4

    # 根据实际获取的数据长度进行处理
    if actual_sample_count < FINGERPRINT_SAMPLECOUNT:
        print(f"[!] 警告：音频数据不足 {FINGERPRINT_DURATION} 秒。实际获取 {actual_sample_count} 个样本，将用静音填充。")
        buffer_list = list(unpack(f'<{actual_sample_count}f', buffer))
        # 用静音 (0.0) 填充到所需的长度
        buffer_list.extend([0.0] * (FINGERPRINT_SAMPLECOUNT - actual_sample_count))
    else:
        # 如果数据多于或等于预期，只取需要的部分
        buffer_list = list(unpack(f'<{FINGERPRINT_SAMPLECOUNT}f', buffer[:bytes_expected]))

    # 调用内部函数生成并返回指纹
    fingerprint = _generate_fingerprint_js(buffer_list)
    return fingerprint


# --------------------------------------------------------------------------
# 主程序执行部分 (作为示例)
# --------------------------------------------------------------------------

def main():
    """
    脚本的主入口，用于演示 `generate_fingerprint_from_file` 函数的用法。
    """
    # 检查命令行参数
    if len(sys.argv) < 2:
        print("\n错误：请提供一个音频文件路径作为参数。")
        print(f"用法: python {sys.argv[0]} \"<文件路径>\" [开始时间(秒)]")
        sys.exit(1)

    input_file = sys.argv[1]
    start_offset = int(sys.argv[2]) if len(sys.argv) > 2 else 0

    try:
        # 1. 调用核心函数获取指纹
        fp = generate_fingerprint_from_file(input_file, start_time=start_offset)
        print(f"\n[*] 成功获取指纹: {fp}")

        # 2. (可选) 使用指纹进行后续操作，例如调用网易云API
        if _PYNCM_AVAILABLE:
            print("[*] 正在使用指纹匹配歌曲 (需要 pyncm 库)...")
            result = GetMatchTrackByFP(fp, FINGERPRINT_DURATION)
            print("\n--- 匹配结果 ---")
            pprint(result)
            print("----------------\n")
        else:
            print("[*] 'pyncm' 库未安装，跳过歌曲匹配步骤。")

    except FileNotFoundError:
        print("\n[X] 致命错误：找不到 'ffmpeg' 命令。")
        print("    请确保你已经安装了 ffmpeg，并且它的路径已添加到系统的 PATH 环境变量中。")
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print("\n[X] 致命错误：ffmpeg 执行失败。")
        print("    这可能是因为文件路径错误、文件损坏、或音频格式不被支持。")
        print(f"    ffmpeg 错误信息: {e.stderr.decode('utf-8', errors='ignore').strip()}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[X] 发生未知错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


# 当这个脚本被直接运行时，调用 main() 函数
if __name__ == "__main__":
    main()