# tag_updater.py

import os
import time
import argparse
import mutagen
from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.easyid3 import EasyID3
from mutagen.easymp4 import EasyMP4

try:
    from audio_fingerprint import generate_fingerprint_from_file, FINGERPRINT_DURATION
    from pyncm.apis.track import GetMatchTrackByFP
except ImportError:
    print("[错误] 无法导入核心模块。请确保 'audio_fingerprint.py' 和 'pyncm' 已正确安装。")
    exit(1)


def extract_song_info(api_result: dict) -> dict or None:
    """
    安全地从网易云 API 的返回结果中提取歌曲信息。

    Args:
        api_result (dict): 从 GetMatchTrackByFP 返回的字典。

    Returns:
        dict: 包含 'title', 'artist', 'album' 的字典，如果未找到则返回 None。
    """
    try:
        songs = api_result.get('data', {}).get('result', [])
        if not songs:
            return None

        song_data = songs[0].get('song', {})
        if not song_data:
            return None

        title = song_data.get('name')
        album = song_data.get('album', {}).get('name')

        # 艺术家可能是多个，需要拼接
        artists_list = song_data.get('artists', [])
        artist = ' & '.join([artist.get('name', '未知') for artist in artists_list])

        info = {}
        if title: info['title'] = title
        if artist: info['artist'] = artist
        if album: info['album'] = album

        return info if info else None
    except (IndexError, KeyError, TypeError):
        return None


def recognize_song(file_path: str, num_segments: int = 3) -> dict or None:
    """
    通过音频指纹识别歌曲信息，可尝试多个时间点以提高成功率。

    Args:
        file_path (str): 音频文件路径。
        num_segments (int): 尝试识别的次数（分段数）。

    Returns:
        dict: 包含识别到的歌曲信息的字典，或 None。
    """
    print(f"[*] 正在识别: {os.path.basename(file_path)} (尝试 {num_segments} 个分段)")

    try:
        audio = mutagen.File(file_path)
        if not audio or not hasattr(audio, 'info') or audio.info.length < FINGERPRINT_DURATION:
            # 如果文件太短或无法读取时长，只尝试从头开始
            start_times = [0]
        else:
            duration = audio.info.length
            # 动态计算采样点，使其均匀分布在音频的 10% 到 90% 之间
            # 避免采样文件开头和结尾的静音部分
            if num_segments == 1:
                start_times = [int(duration * 0.3)]  # 如果只采一次，取 30% 位置
            else:
                padding = 0.1  # 距离开头和结尾的距离
                effective_duration = duration * (1 - 2 * padding)
                interval = effective_duration / (num_segments - 1) if num_segments > 1 else 0
                start_times = [int(duration * padding + i * interval) for i in range(num_segments)]

    except Exception:
        # 如果无法获取时长，使用默认列表
        start_times = [0, 30, 60][:num_segments]

    for offset in start_times:
        try:
            fp = generate_fingerprint_from_file(file_path, start_time=offset)
            result = GetMatchTrackByFP(fp, FINGERPRINT_DURATION)

            song_info = extract_song_info(result)
            if song_info:
                print(f"[+] 在 {offset}s 处成功匹配！")
                return song_info

            time.sleep(0.5)  # 短暂等待，避免过于频繁的 API 请求
        except Exception as e:
            print(f"[!] 匹配失败 (偏移 {offset}s): {str(e)[:100]}...")  # 打印简短的错误信息

    return None


def update_metadata(file_path: str, song_info: dict, tags_to_write: list):
    """
    更新音频文件的元数据标签 (标题, 艺术家, 专辑)。

    Args:
        file_path (str): 音频文件路径。
        song_info (dict): 包含 'title', 'artist', 'album' 的字典。
        tags_to_write (list): 一个列表，指定要写入哪些标签, e.g., ['title', 'artist']。
    """
    try:
        audio = mutagen.File(file_path, easy=True)
        if audio is None:
            # EasyID3/EasyMP4 对某些格式支持不佳，尝试手动加载
            if file_path.lower().endswith('.mp3'):
                audio = EasyID3(file_path)
            elif file_path.lower().endswith('.m4a'):
                audio = EasyMP4(file_path)
            else:
                print(f"[!] 警告: mutagen(easy) 不支持此文件格式: {file_path}")
                return

        # 为没有标签的文件添加标签
        if audio.tags is None:
            audio.add_tags()

        print("    原标签 -> "
              f"标题: {audio.get('title', ['N/A'])[0]}, "
              f"艺术家: {audio.get('artist', ['N/A'])[0]}, "
              f"专辑: {audio.get('album', ['N/A'])[0]}")

        updated_tags = []
        if 'title' in tags_to_write and 'title' in song_info:
            audio['title'] = song_info['title']
            updated_tags.append(f"标题: {song_info['title']}")

        if 'artist' in tags_to_write and 'artist' in song_info:
            audio['artist'] = song_info['artist']
            updated_tags.append(f"艺术家: {song_info['artist']}")

        if 'album' in tags_to_write and 'album' in song_info:
            audio['album'] = song_info['album']
            updated_tags.append(f"专辑: {song_info['album']}")

        audio.save()
        print(f"    新标签 -> {', '.join(updated_tags)}")

    except Exception as e:
        print(f"[!] 写入元数据失败: {e}")


def process_path(path: str, num_segments: int, tags_to_write: list):
    """
    处理指定的路径，可以是单个文件或整个文件夹。
    """
    if not os.path.exists(path):
        print(f"[错误] 路径不存在: {path}")
        return

    files_to_process = []
    if os.path.isdir(path):
        print(f"--- 开始扫描文件夹: {path} ---")
        supported_formats = ('.wav', '.mp3', '.flac', '.m4a', '.ogg', '.ape')
        for root, _, files in os.walk(path):
            for file in files:
                if file.lower().endswith(supported_formats):
                    files_to_process.append(os.path.join(root, file))
    elif os.path.isfile(path):
        files_to_process.append(path)

    total_files = len(files_to_process)
    print(f"找到 {total_files} 个支持的音频文件。")

    for i, file_path in enumerate(files_to_process):
        print(f"\n--- [{i + 1}/{total_files}] 处理中 ---")
        song_info = recognize_song(file_path, num_segments)

        if song_info:
            update_metadata(file_path, song_info, tags_to_write)
        else:
            print("[x] 未能找到匹配的歌曲信息，跳过写入。")


def main():
    """
    主函数，用于解析命令行参数并启动处理流程。
    """
    parser = argparse.ArgumentParser(
        description="音频识别与元数据写入工具",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
使用示例:
  # 处理单个文件，尝试 5 次识别，写入所有标签
  python tag_updater.py "C:\\Music\\song.mp3" -n 5

  # 处理整个文件夹，使用默认 3 次识别，只写入标题和艺术家
  python tag_updater.py "D:\\My Music" -t title artist

  # 处理文件夹，并为每个文件尝试 10 次识别以提高准确率
  python tag_updater.py "/path/to/folder" --segments 10
"""
    )

    parser.add_argument(
        "path",
        type=str,
        help="要处理的音频文件或文件夹路径。"
    )
    parser.add_argument(
        "-n", "--segments",
        type=int,
        default=3,
        help="每个文件尝试识别的次数（分段数）。增加此值可提高识别成功率，但会花费更长时间。 (默认: 3)"
    )
    parser.add_argument(
        "-t", "--tags",
        nargs='+',
        choices=['title', 'artist', 'album'],
        default=['title', 'artist', 'album'],
        help="指定要写入的元数据标签。可以选择 'title', 'artist', 'album' 中的一个或多个。 (默认: 写入全部三个)"
    )

    args = parser.parse_args()

    process_path(args.path, args.segments, args.tags)
    print("\n--- 所有任务处理完成！ ---")


if __name__ == "__main__":
    main()
