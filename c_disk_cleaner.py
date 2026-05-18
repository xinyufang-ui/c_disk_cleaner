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
MOVE_TARGET = "D:\\小方搬家"

# 可以安全删除的目录（缓存/临时文件）
SAFE_TO_DELETE = [
    (os.environ.get("TEMP", ""), "用户临时文件"),
    (os.environ.get("TMP", ""), "系统临时文件"),
    (r"C:\Windows\Temp", "Windows临时文件"),
    (r"C:\Windows\Prefetch", "预读取缓存"),
    (r"C:\Windows\SoftwareDistribution\Download", "Windows更新下载缓存（14.9GB大头！）"),
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
    # === 周老师电脑专用：软件更新垃圾 ===
    (os.path.expanduser(r"~\AppData\Roaming\baidu\BaiduNetdisk\AutoUpdate\Download"), "百度网盘旧更新包（2.4GB垃圾）"),
    (os.path.expanduser(r"~\AppData\Roaming\Xmind\Electron v3\vana\auto-updater"), "Xmind历史更新包（1.8GB垃圾）"),
    (os.path.expanduser(r"~\AppData\Local\ima.copilot\Application\138.0.7204.3560\Installer"), "腾讯AI安装缓存"),
    (os.path.expanduser(r"~\AppData\Local\xmind-updater"), "Xmind更新器缓存"),
    (os.path.expanduser(r"~\AppData\Roaming\kingsoft\wps\addons\data\win-i386\cef\cache"), "WPS缓存"),
    (os.path.expanduser(r"~\AppData\Local\Microsoft\Edge\User Data\ProvenanceData"), "Edge AI模型缓存"),
    (os.path.expanduser(r"~\AppData\Local\Microsoft\Edge\User Data\component_crx_cache"), "Edge组件缓存"),
    (os.path.expanduser(r"~\AppData\Local\Microsoft\Olk\EBWebView\Default\Cache"), "Outlook缓存"),
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

# 系统级大头（C盘膨胀真凶，只扫描不删，每条带专门操作方法）
# 格式：(路径, 描述, 处理建议)
SYSTEM_BLOAT = [
    (r"C:\hiberfil.sys",
     "休眠文件（=物理内存大小）",
     "不用休眠功能可关：管理员CMD运行  powercfg -h off"),
    (r"C:\pagefile.sys",
     "虚拟内存（建议挪到D盘）",
     "系统属性→高级→性能设置→高级→虚拟内存→C设无、D设系统管理→重启"),
    (r"C:\swapfile.sys",
     "UWP应用交换文件",
     "关闭hiberfil后通常自动消失"),
    (r"C:\Windows\Installer",
     "MSI安装缓存（孤儿文件多则可清几GB）",
     "下载 PatchCleaner（官方工具）→ 扫描 → 移动孤儿文件到D盘"),
    (r"C:\Windows.old",
     "旧系统升级备份（10-30GB）",
     "搜索栏输'磁盘清理'→选C盘→点'清理系统文件'→勾'以前的Windows安装'"),
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


def scan_system_bloat():
    """扫描系统级大头（hiberfil/pagefile/Windows.old等），返回 (path, size_mb, desc, action)"""
    results = []
    for path, desc, action in SYSTEM_BLOAT:
        if not os.path.exists(path):
            continue
        try:
            if os.path.isfile(path):
                size = os.path.getsize(path) / (1024 * 1024)
            else:
                size = get_dir_size(path)
            if size > 1:
                results.append((path, size, desc, action))
        except (OSError, PermissionError):
            # 权限不足读不到大小（如pagefile被系统锁），仍标记存在
            results.append((path, 0, desc + "（权限不足，无法读取大小，请管理员运行）", action))
    return results


def scan_wsl_docker():
    """扫描WSL发行版和Docker WSL镜像（ext4.vhdx只增不减）"""
    results = []
    packages_dir = os.path.expanduser(r"~\AppData\Local\Packages")
    distro_keywords = ("Canonical", "Ubuntu", "Debian", "Kali", "openSUSE", "SUSE", "Oracle", "Alpine")
    if os.path.exists(packages_dir):
        try:
            for d in os.listdir(packages_dir):
                if any(k in d for k in distro_keywords):
                    vhdx = os.path.join(packages_dir, d, "LocalState", "ext4.vhdx")
                    if os.path.exists(vhdx):
                        try:
                            size = os.path.getsize(vhdx) / (1024 * 1024)
                            action = (f"管理员PowerShell运行：\n"
                                      f"             wsl --shutdown\n"
                                      f"             Optimize-VHD -Path '{vhdx}' -Mode Full")
                            results.append((vhdx, size, f"WSL镜像 ({d})", action))
                        except (OSError, PermissionError):
                            pass
        except (OSError, PermissionError):
            pass

    docker_candidates = [
        os.path.expanduser(r"~\AppData\Local\Docker\wsl\data\ext4.vhdx"),
        os.path.expanduser(r"~\AppData\Local\Docker\wsl\disk\docker_data.vhdx"),
    ]
    for vhdx in docker_candidates:
        if os.path.exists(vhdx):
            try:
                size = os.path.getsize(vhdx) / (1024 * 1024)
                action = "Docker Desktop → Settings → Resources → 'Clean / Purge data'，或重置Docker"
                results.append((vhdx, size, "Docker WSL镜像", action))
            except (OSError, PermissionError):
                pass
    return results


def scan_onedrive():
    """扫描OneDrive本地缓存（个人版+企业版）"""
    results = []
    user_home = os.path.expanduser("~")
    candidates = []
    od_personal = os.path.join(user_home, "OneDrive")
    if os.path.exists(od_personal):
        candidates.append((od_personal, "OneDrive个人版本地缓存"))
    try:
        for d in os.listdir(user_home):
            if d.startswith("OneDrive -") or d.startswith("OneDrive-"):
                full = os.path.join(user_home, d)
                if os.path.isdir(full):
                    candidates.append((full, f"OneDrive企业版本地缓存 ({d})"))
    except (OSError, PermissionError):
        pass

    action = "右键OneDrive文件夹 → 选'释放空间'，本地副本删除，文件保留在云端"
    for path, desc in candidates:
        size = get_dir_size(path)
        if size > 100:
            results.append((path, size, desc, action))
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

    # ====== 第四阶段：扫描系统级大头（C盘膨胀真凶） ======
    print_header("阶段4：扫描系统级大头（盲区，需专门处理）")
    print("  扫描中，请稍候...")

    system_bloat = scan_system_bloat() + scan_wsl_docker() + scan_onedrive()
    total_bloat = sum(s for _, s, _, _ in system_bloat)
    if system_bloat:
        for path, size, desc, action in system_bloat:
            shown = format_size(size) if size > 0 else "  ?  "
            print(f"  [{shown:>8}] {desc}")
            print(f"            {path}")
        print(f"\n  >>> 系统级大头总计：{format_size(total_bloat)}")
        print(f"  注意：这些文件不能直接删，每条对应专门处理方法（详见报告）")
    else:
        print("  未发现系统级大头（恭喜，系统状态健康）")

    # ====== 操作阶段 ======
    print_header("操作菜单")
    print(f"""
  预计可释放空间：{format_size(total_deletable + total_movable)}

  [1] 清理所有缓存/临时文件（安全，推荐）
  [2] 搬运用户文件夹到D盘
  [3] 清理缓存 + 搬运（全部执行）
  [4] 逐项选择要清理的内容
  [5] 生成报告（不执行任何操作）
  [6] 治本模式：把默认存储路径改到D盘（防止C盘再涨）
  [0] 退出
""")

    choice = input("请选择操作 [0-6]: ").strip()

    if choice == "0":
        print("已退出")
        return

    if choice == "5":
        # 生成报告 - 保存到exe同目录，避免桌面路径问题
        try:
            exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
            report_path = os.path.join(exe_dir, "C盘清理报告.txt")
        except:
            report_path = "C:\\C盘清理报告.txt"
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
            f.write("\n")
            f.write("【系统级大头（C盘膨胀真凶，需专门处理）】\n")
            if system_bloat:
                for path, size, desc, action in system_bloat:
                    shown = format_size(size) if size > 0 else "未知大小"
                    f.write(f"  {shown:>8} | {desc}\n")
                    f.write(f"           路径: {path}\n")
                    f.write(f"           处理: {action}\n\n")
                f.write(f"  小计：{format_size(total_bloat)}\n")
                f.write(f"  说明：以上文件不可直接删除，按每条'处理'方法逐项操作\n")
            else:
                f.write("  未发现\n")
        print(f"\n  报告已保存到：{report_path}")
        print(f"  （和本程序在同一个文件夹里）")
        input("\n按回车退出...")
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

    if choice == "6":
        print_header("治本模式：修改默认存储路径到D盘（逐条确认）")
        print("  修改后，新文件会自动存到D盘，C盘不再增长\n")

        # Windows用户文件夹重定向（通过注册表）
        import winreg
        shell_folders_key = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders"

        redirects = [
            ("{374DE290-123F-4565-9164-39C4925E467B}", "Downloads", "下载文件夹", "D:\\小方搬家\\Downloads"),
            ("Personal", "Documents", "文档", "D:\\小方搬家\\Documents"),
            ("My Video", "Videos", "视频", "D:\\小方搬家\\Videos"),
            ("My Music", "Music", "音乐", "D:\\小方搬家\\Music"),
            ("My Pictures", "Pictures", "图片", "D:\\小方搬家\\Pictures"),
            ("Desktop", "Desktop", "桌面", "D:\\小方搬家\\Desktop"),
        ]

        changed = 0
        for reg_name, folder_name, desc, new_path in redirects:
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, shell_folders_key, 0, winreg.KEY_READ)
                current, _ = winreg.QueryValueEx(key, reg_name)
                winreg.CloseKey(key)
            except:
                current = "未知"

            print(f"  [{desc}]")
            print(f"    当前路径：{current}")
            print(f"    修改为  ：{new_path}")
            ans = input(f"    确认修改? [y/N]: ").strip().lower()

            if ans == "y":
                try:
                    os.makedirs(new_path, exist_ok=True)
                    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, shell_folders_key, 0, winreg.KEY_SET_VALUE)
                    winreg.SetValueEx(key, reg_name, 0, winreg.REG_EXPAND_SZ, new_path)
                    winreg.CloseKey(key)
                    print(f"    ✓ 已修改\n")
                    changed += 1
                except Exception as e:
                    print(f"    ✗ 失败: {e}\n")
            else:
                print(f"    - 跳过\n")

        # 额外提示
        print("  " + "-" * 50)
        print("  以下需要手动修改（程序无法自动改）：")
        print("  ")
        print("  [微信] 设置 → 文件管理 → 更改存储路径到 D盘")
        print("  [浏览器] 设置 → 下载 → 修改默认下载位置到 D盘")
        print("  [QQ] 设置 → 文件管理 → 修改路径")
        print("  " + "-" * 50)

        if changed > 0:
            print(f"\n  已修改 {changed} 项路径，重启电脑后生效")
            print("  重启后新文件会自动存到D盘，C盘不再膨胀")
        else:
            print("\n  未做任何修改")

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
