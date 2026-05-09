"""
C盘清理工具 - 扫描、分类、删除/搬运
使用方法：以管理员身份运行 python c_disk_cleaner.py
"""

import os
import sys
import shutil
import ctypes
import tempfile
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# ============ 配置 ============

# 搬运目标盘（D盘有169GB空闲）
MOVE_TARGET = "D:\\C盘搬家"

# 可以安全删除的目录（缓存/临时文件）
SAFE_TO_DELETE = [
    (os.environ.get("TEMP", ""), "用户临时文件"),
    (os.environ.get("TMP", ""), "系统临时文件"),
    (r"C:\Windows\Temp", "Windows临时文件"),
    (r"C:\Windows\Prefetch", "预读取缓存"),
    (r"C:\Windows\SoftwareDistribution\Download", "Windows更新下载缓存"),
    (r"C:\Windows\Installer\$PatchCache$", "安装补丁缓存"),
    (os.path.expanduser(r"~\AppData\Local\Temp"), "用户Temp"),
    (os.path.expanduser(r"~\AppData\Local\Microsoft\Windows\Explorer"), "缩略图缓存"),
    (os.path.expanduser(r"~\AppData\Local\Google\Chrome\User Data\Default\Cache"), "Chrome缓存"),
    (os.path.expanduser(r"~\AppData\Local\Google\Chrome\User Data\Default\Code Cache"), "Chrome代码缓存"),
    (os.path.expanduser(r"~\AppData\Local\Microsoft\Edge\User Data\Default\Cache"), "Edge缓存"),
    (os.path.expanduser(r"~\AppData\Local\Microsoft\Edge\User Data\Default\Code Cache"), "Edge代码缓存"),
    (os.path.expanduser(r"~\AppData\Local\pip\cache"), "pip缓存"),
    (os.path.expanduser(r"~\AppData\Local\npm-cache"), "npm缓存"),
    (os.path.expanduser(r"~\AppData\Local\yarn\Cache"), "yarn缓存"),
    (os.path.expanduser(r"~\AppData\Roaming\Microsoft\Windows\Recent"), "最近文件记录"),
    (r"C:\$Recycle.Bin", "回收站"),
]

# 可以搬运到D盘的用户目录
MOVABLE_DIRS = [
    (os.path.expanduser("~\\Downloads"), "下载文件夹"),
    (os.path.expanduser("~\\Documents"), "文档"),
    (os.path.expanduser("~\\Videos"), "视频"),
    (os.path.expanduser("~\\Music"), "音乐"),
    (os.path.expanduser("~\\Pictures"), "图片"),
    (os.path.expanduser("~\\Desktop"), "桌面大文件"),
]

# 绝对不能碰的目录
PROTECTED = [
    r"C:\Windows\System32",
    r"C:\Windows\WinSxS",
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    r"C:\ProgramData\Microsoft",
    r"C:\Users\Default",
]


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


def get_dir_size(path):
    """获取目录大小（MB）"""
    total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                except (OSError, PermissionError):
                    pass
    except (OSError, PermissionError):
        pass
    return total / (1024 * 1024)  # MB


def format_size(mb):
    if mb >= 1024:
        return f"{mb/1024:.1f} GB"
    return f"{mb:.0f} MB"


def safe_delete(path):
    """安全删除文件或目录"""
    deleted = 0
    try:
        if os.path.isfile(path):
            size = os.path.getsize(path) / (1024 * 1024)
            os.remove(path)
            return size
        elif os.path.isdir(path):
            for root, dirs, files in os.walk(path, topdown=False):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        size = os.path.getsize(fp) / (1024 * 1024)
                        os.remove(fp)
                        deleted += size
                    except (OSError, PermissionError):
                        pass
                for d in dirs:
                    try:
                        os.rmdir(os.path.join(root, d))
                    except (OSError, PermissionError):
                        pass
    except (OSError, PermissionError):
        pass
    return deleted


def scan_large_files(root="C:\\", min_size_mb=100, max_files=50):
    """扫描C盘大文件"""
    large_files = []
    user_home = os.path.expanduser("~")

    # 只扫描用户目录下的大文件（安全）
    scan_dirs = [
        user_home,
        r"C:\Users\Public",
    ]

    for scan_dir in scan_dirs:
        if not os.path.exists(scan_dir):
            continue
        try:
            for root_dir, dirs, files in os.walk(scan_dir):
                # 跳过AppData中的已知缓存目录（已在SAFE_TO_DELETE中处理）
                for f in files:
                    fp = os.path.join(root_dir, f)
                    try:
                        size = os.path.getsize(fp) / (1024 * 1024)
                        if size >= min_size_mb:
                            large_files.append((fp, size))
                    except (OSError, PermissionError):
                        pass
                if len(large_files) >= max_files:
                    break
        except (OSError, PermissionError):
            pass

    large_files.sort(key=lambda x: x[1], reverse=True)
    return large_files[:max_files]


def scan_wechat_cache():
    """扫描微信缓存（常见空间大户）"""
    wechat_paths = []
    documents = os.path.expanduser("~\\Documents")
    wechat_dir = os.path.join(documents, "WeChat Files")
    if os.path.exists(wechat_dir):
        # 扫描FileStorage（图片视频缓存）
        for user_dir in os.listdir(wechat_dir):
            fs = os.path.join(wechat_dir, user_dir, "FileStorage")
            if os.path.exists(fs):
                size = get_dir_size(fs)
                if size > 100:
                    wechat_paths.append((fs, size, "微信文件缓存"))
    return wechat_paths


def scan_tencent_cache():
    """扫描QQ/腾讯缓存"""
    results = []
    documents = os.path.expanduser("~\\Documents")
    qq_dir = os.path.join(documents, "Tencent Files")
    if os.path.exists(qq_dir):
        size = get_dir_size(qq_dir)
        if size > 100:
            results.append((qq_dir, size, "QQ文件缓存"))
    return results


def print_header(text):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")


def print_logo():
    logo = r"""
  ╔══════════════════════════════════════════════════════════╗
  ║                                                          ║
  ║        ★  周 老 师 请 使 用  ★                         ║
  ║                                                          ║
  ║           C 盘 清 理 工 具  v1.0                        ║
  ║                                                          ║
  ║        搬运目标：D:\C盘搬家                             ║
  ║        安全等级：仅清理缓存，不碰系统文件               ║
  ║                                                          ║
  ╚══════════════════════════════════════════════════════════╝
"""
    print(logo)


def main():
    if sys.platform != "win32":
        print("此工具仅支持Windows系统")
        return

    print_logo()

    if not is_admin():
        print("=" * 60)
        print("  警告：未以管理员身份运行")
        print("  部分系统缓存可能无法清理")
        print("  建议：右键 -> 以管理员身份运行")
        print("=" * 60)
        input("按回车继续（功能受限）...")

    print_header("C盘清理工具 v1.0")
    print(f"扫描时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # ====== 第一阶段：扫描 ======
    print_header("阶段1：扫描可清理的缓存/临时文件")

    deletable = []
    total_deletable = 0

    for path, desc in SAFE_TO_DELETE:
        if not path or not os.path.exists(path):
            continue
        size = get_dir_size(path)
        if size > 1:  # 大于1MB才显示
            deletable.append((path, size, desc))
            total_deletable += size
            print(f"  [{format_size(size):>8}] {desc}")
            print(f"            {path}")

    # 微信缓存
    wechat = scan_wechat_cache()
    for path, size, desc in wechat:
        deletable.append((path, size, desc))
        total_deletable += size
        print(f"  [{format_size(size):>8}] {desc}")
        print(f"            {path}")

    # QQ缓存
    tencent = scan_tencent_cache()
    for path, size, desc in tencent:
        deletable.append((path, size, desc))
        total_deletable += size
        print(f"  [{format_size(size):>8}] {desc}")
        print(f"            {path}")

    print(f"\n  >>> 可清理缓存总计：{format_size(total_deletable)}")

    # ====== 第二阶段：扫描可搬运目录 ======
    print_header("阶段2：扫描可搬运到D盘的目录")

    movable = []
    total_movable = 0

    for path, desc in MOVABLE_DIRS:
        if not os.path.exists(path):
            continue
        size = get_dir_size(path)
        if size > 10:  # 大于10MB才显示
            movable.append((path, size, desc))
            total_movable += size
            print(f"  [{format_size(size):>8}] {desc}")
            print(f"            {path}")

    print(f"\n  >>> 可搬运文件总计：{format_size(total_movable)}")

    # ====== 第三阶段：扫描大文件 ======
    print_header("阶段3：扫描大文件（>100MB）")
    print("  扫描中，请稍候...")

    large_files = scan_large_files()
    if large_files:
        for fp, size in large_files[:20]:
            print(f"  [{format_size(size):>8}] {fp}")
    else:
        print("  未发现超过100MB的文件")

    # ====== 操作阶段 ======
    print_header("操作菜单")
    print(f"""
  预计可释放空间：{format_size(total_deletable + total_movable)}

  [1] 清理所有缓存/临时文件（安全，推荐）
  [2] 搬运用户文件夹到D盘
  [3] 清理缓存 + 搬运（全部执行）
  [4] 逐项选择要清理的内容
  [5] 生成报告（不执行任何操作）
  [0] 退出
""")

    choice = input("请选择操作 [0-5]: ").strip()

    if choice == "0":
        print("已退出")
        return

    if choice == "5":
        # 生成报告
        report_path = os.path.join(os.path.expanduser("~\\Desktop"), "C盘清理报告.txt")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(f"C盘清理报告 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 60 + "\n\n")
            f.write("【可安全删除的缓存】\n")
            for path, size, desc in deletable:
                f.write(f"  {format_size(size):>8} | {desc} | {path}\n")
            f.write(f"\n  小计：{format_size(total_deletable)}\n\n")
            f.write("【可搬运到D盘的目录】\n")
            for path, size, desc in movable:
                f.write(f"  {format_size(size):>8} | {desc} | {path}\n")
            f.write(f"\n  小计：{format_size(total_movable)}\n\n")
            f.write("【大文件列表】\n")
            for fp, size in large_files:
                f.write(f"  {format_size(size):>8} | {fp}\n")
        print(f"\n报告已保存到：{report_path}")
        return

    if choice in ("1", "3"):
        print_header("正在清理缓存...")
        freed = 0
        for path, size, desc in deletable:
            print(f"  清理 {desc}...", end=" ")
            result = safe_delete(path)
            freed += result
            print(f"释放 {format_size(result)}")
        print(f"\n  >>> 缓存清理完成，共释放：{format_size(freed)}")

    if choice in ("2", "3"):
        print_header("正在搬运文件到D盘...")
        os.makedirs(MOVE_TARGET, exist_ok=True)
        moved = 0
        for path, size, desc in movable:
            dest = os.path.join(MOVE_TARGET, desc)
            print(f"  搬运 {desc} -> {dest}...", end=" ")
            try:
                if os.path.exists(dest):
                    # 合并到已有目录
                    for item in os.listdir(path):
                        src_item = os.path.join(path, item)
                        dst_item = os.path.join(dest, item)
                        try:
                            shutil.move(src_item, dst_item)
                        except (OSError, PermissionError) as e:
                            pass
                else:
                    shutil.move(path, dest)
                moved += size
                print("完成")
            except (OSError, PermissionError) as e:
                print(f"失败: {e}")
        print(f"\n  >>> 搬运完成，共移动：{format_size(moved)}")
        print(f"  文件已移至：{MOVE_TARGET}")

    if choice == "4":
        print_header("逐项选择")
        freed = 0

        print("\n--- 缓存/临时文件 ---")
        for i, (path, size, desc) in enumerate(deletable):
            ans = input(f"  删除 {desc} ({format_size(size)})? [y/N]: ").strip().lower()
            if ans == "y":
                result = safe_delete(path)
                freed += result
                print(f"    已释放 {format_size(result)}")

        print("\n--- 可搬运目录 ---")
        os.makedirs(MOVE_TARGET, exist_ok=True)
        for path, size, desc in movable:
            ans = input(f"  搬运 {desc} ({format_size(size)}) 到D盘? [y/N]: ").strip().lower()
            if ans == "y":
                dest = os.path.join(MOVE_TARGET, desc)
                try:
                    shutil.move(path, dest)
                    freed += size
                    print(f"    已搬运到 {dest}")
                except (OSError, PermissionError) as e:
                    print(f"    失败: {e}")

        print(f"\n  >>> 总计释放：{format_size(freed)}")

    # 清理Windows更新缓存（需要管理员）
    if is_admin() and choice in ("1", "3"):
        print("\n  额外：清理Windows更新组件...")
        os.system("Dism.exe /online /Cleanup-Image /StartComponentCleanup /ResetBase")

    print_header("完成")
    # 显示C盘当前状态
    try:
        usage = shutil.disk_usage("C:\\")
        free_gb = usage.free / (1024**3)
        total_gb = usage.total / (1024**3)
        print(f"  C盘当前：{free_gb:.1f} GB 可用 / 共 {total_gb:.1f} GB")
    except:
        pass

    input("\n按回车退出...")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n发生错误：{e}")
        input("按回车退出...")
