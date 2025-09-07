import os
import subprocess
import time
import argparse
from typing import Counter
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

def find_most_common_result(results: list) -> dict or None:
    """
    从一个结果列表中，通过对每个标签（标题、艺术家、专辑）独立投票，
    合成并返回最可靠的结果。

    Args:
        results (list): 一个包含多个歌曲信息字典的列表。

    Returns:
        dict: 包含了最可靠的 'title', 'artist', 'album' 的字典。
    """
    if not results:
        return None

    # 创建三个列表，分别存放所有识别到的标题、艺术家和专辑
    titles = [info.get('title') for info in results if info.get('title')]
    artists = [info.get('artist') for info in results if info.get('artist')]
    albums = [info.get('album') for info in results if info.get('album')]

    final_result = {}
    print("    [独立投票结果]")

    # 1. 对标题进行投票
    if titles:
        title_counter = Counter(titles)
        best_title, count = title_counter.most_common(1)[0]
        final_result['title'] = best_title
        print(f"      -> 最佳标题: '{best_title}' (出现 {count} 次)")
    
    # 2. 对艺术家进行投票
    if artists:
        artist_counter = Counter(artists)
        best_artist, count = artist_counter.most_common(1)[0]
        final_result['artist'] = best_artist
        print(f"      -> 最佳艺术家: '{best_artist}' (出现 {count} 次)")
        
    # 3. 对专辑进行投票
    if albums:
        album_counter = Counter(albums)
        best_album, count = album_counter.most_common(1)[0]
        final_result['album'] = best_album
        print(f"      -> 最佳专辑: '{best_album}' (出现 {count} 次)")

    return final_result if final_result else None

def get_audio_duration(file_path: str) -> float or None:
    """
    使用 ffprobe (首选) 或 mutagen (备用) 来获取音频文件的时长。
    """
    # 优先尝试 ffprobe
    try:
        command = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ]
        # 设置 subprocess.DEVNULL 来隐藏 ffmpeg 的额外输出
        process = subprocess.run(command, capture_output=True, text=True, check=True, stderr=subprocess.DEVNULL)
        return float(process.stdout.strip())
    except (FileNotFoundError, subprocess.CalledProcessError, ValueError):
        # 如果 ffprobe 失败 (未安装或文件问题)，则回退到 mutagen
        try:
            audio = mutagen.File(file_path)
            if audio and hasattr(audio, 'info'):
                return audio.info.length
        except Exception:
            return None
    return None

def recognize_song(file_path: str, num_segments: int = 3) -> dict or None:
    """
    通过音频指纹识别歌曲信息，执行所有分段并根据投票结果确定最佳匹配。
    """
    print(f"[*] 正在识别: {os.path.basename(file_path)} (执行 {num_segments} 个分段进行投票)")
    
    duration = get_audio_duration(file_path)

    start_times = []
    if duration is None:
        # 情况1: 无法获取时长。使用固定间隔生成回退采样点。
        fallback_interval = 30  # 假设每隔30秒采样一次
        start_times = [i * fallback_interval for i in range(num_segments)]
        print(f"[!] 警告: 无法获取音频时长。将使用固定的 {fallback_interval}s 间隔生成采样点: {start_times}s。")

    elif duration < FINGERPRINT_DURATION:
        # 情况2: 时长已知，但太短无法生成完整指纹。
        # 仅从头开始尝试一次，因为没有其他有效的采样点。
        start_times = [0]
        print(f"[!] 警告: 音频时长 ({duration:.1f}s) 短于指纹所需时长 ({FINGERPRINT_DURATION}s)。将仅从 0s 处尝试识别一次。")

    else:
        # 情况3: 时长正常，按比例计算采样点。
        if num_segments == 1:
            # 对于单次采样，选择一个靠前但不是最开头的位置
            start_times = [int(duration * 0.3)]
        else:
            # 确保最后一个采样点之后仍有足够的时间来生成一个完整的指纹
            # 有效的采样窗口是从 0 到 (duration - FINGERPRINT_DURATION)
            valid_window_end = max(0, duration - FINGERPRINT_DURATION)
            
            # 在这个有效窗口内均匀分布采样点
            # 避免 num_segments=1 时除以零
            interval = valid_window_end / (num_segments - 1) if num_segments > 1 else 0
            start_times = [int(i * interval) for i in range(num_segments)]

    all_successful_results = []
    
    # 确保只对有效的采样点进行循环
    for i, offset in enumerate(start_times):
        print(f"    -> 正在分析分段 {i+1}/{len(start_times)} (从 {offset}s 开始)")
        try:
            fp = generate_fingerprint_from_file(file_path, start_time=offset)
            if not fp:
                print(f"    [!] 在 {offset}s 处无法生成指纹 (可能已到文件末尾)。")
                continue # 如果无法生成指纹，跳到下一个点

            result = GetMatchTrackByFP(fp, FINGERPRINT_DURATION)
            song_info = extract_song_info(result)
            
            if song_info:
                print(f"    [+] 在 {offset}s 处匹配到: {song_info.get('title', '未知')}")
                all_successful_results.append(song_info)
            else:
                print(f"    [-] 在 {offset}s 处未匹配到结果。")
            time.sleep(0.5)
        except Exception as e:
            print(f"    [!] 分段 {i+1} 失败: {str(e)[:100]}...")

    return find_most_common_result(all_successful_results)

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

        if updated_tags:
            audio.save()
            print(f"    新标签 -> {', '.join(updated_tags)}")
        else:
            print("    [i] 没有需要更新的标签。")

    except Exception as e:
        print(f"[!] 写入元数据失败: {e}")

# --- 检查文件是否已有完整标签 ---
def has_complete_tags(file_path: str) -> bool:
    """
    检查一个音频文件是否已经包含 'title', 'artist', 'album' 三个非空标签。
    
    Args:
        file_path (str): 音频文件路径。

    Returns:
        bool: 如果三个标签都存在且不为空，则返回 True，否则返回 False。
    """
    try:
        audio = mutagen.File(file_path, easy=True)
        if audio is None or audio.tags is None:
            return False
        
        # 检查三个关键标签是否存在且内容不为空白
        title = audio.get('title', [''])[0].strip()
        artist = audio.get('artist', [''])[0].strip()
        album = audio.get('album', [''])[0].strip()
        
        return bool(title and artist and album)
    except Exception:
        # 如果读取文件时发生任何错误，都认为它没有完整标签
        return False

def process_path(path: str, num_segments: int, tags_to_write: list, force_update: bool):
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

    skipped_count = 0
    for i, file_path in enumerate(files_to_process):
        print(f"\n--- [{i + 1}/{total_files}] 处理文件: {os.path.basename(file_path)} ---")

        # 检查是否需要跳过
        if not force_update and has_complete_tags(file_path):
            print("[i] 文件已有完整标签，跳过。(可使用 --force 强制更新)")
            skipped_count += 1
            continue

        song_info = recognize_song(file_path, num_segments)

        if song_info:
            update_metadata(file_path, song_info, tags_to_write)
        else:
            print("[x] 未能找到匹配的歌曲信息，跳过写入。")

    # 在结束时提供一个总结
    if skipped_count > 0:
        print(f"\n--- 跳过了 {skipped_count} 个已有完整标签的文件。 ---")

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

  # 处理整个文件夹，使用默认 1 次识别，只写入标题和艺术家
  python tag_updater.py "D:\\My Music" -t title artist

  # 处理文件夹，并为每个文件尝试 10 次识别以提高准确率
  python tag_updater.py "/path/to/folder" --segments 10
  
  # 处理文件夹，但强制更新所有文件，即便是已有完整标签的文件
  python tag_updater.py "/path/to/folder" --force
  
  # 组合使用：强制更新并尝试 5 次识别
  python tag_updater.py "/path/to/folder" -n 5 -f
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
        default=1,
        help="每个文件尝试识别的次数（分段数）。增加此值可提高识别成功率，但会花费更长时间。 (默认: 1)"
    )
    parser.add_argument(
        "-t", "--tags",
        nargs='+',
        choices=['title', 'artist', 'album'],
        default=['title', 'artist', 'album'],
        help="指定要写入的元数据标签。可以选择 'title', 'artist', 'album' 中的一个或多个。 (默认: 写入全部三个)"
    )
    # 新增的命令行参数
    parser.add_argument(
        "-f", "--force",
        action="store_true",
        help="强制更新所有文件的标签，即使文件已有完整的标题、艺术家和专辑信息。"
    )

    args = parser.parse_args()

    # 将新增的 force 参数传递给处理函数
    process_path(args.path, args.segments, args.tags, args.force)
    print("\n--- 所有任务处理完成！ ---")


if __name__ == "__main__":
    main()