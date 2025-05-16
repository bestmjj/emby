import sys
import requests
import os
import time
import datetime
import threading
import sqlite3
from typing import List, Dict, Any

# Get Emby URL and API key from environment variables, or use defaults
emby_url = os.environ.get('EMBY_URL', 'http://10.5.0.5:8096').strip()
emby_api_key = os.environ.get('EMBY_API_KEY', 'ssss').strip()
monitor_database = os.environ.get('DATABASE_FILE', '/app/db/emby_monitor.db').strip()
MONITOR_INTERVAL = 60  # seconds - how often to check for new files

# Global database connection and lock
db_conn: sqlite3.Connection = None
db_lock = threading.Lock()

# Define the set of allowed file extensions (lowercase, no leading dot)
ALLOWED_EXTENSIONS = {
    # Video formats
    "mp4", "mkv", "flv", "avi", "wmv", "ts", "rmvb", "webm", "mpg",
    # Audio formats
    "flac", "m4a", "mp3", "wav", "dsg", "dff", "ape", "aiff",
    "alac", "aac", "ogg", "wma", "opus",
    # Strm
    "strm"
}


def log(message: str) -> None:
    """Logs a message with a timestamp."""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)  # Add flush=True

def create_item(item_path: str, update_type: str) -> None:
    """Sends a request to Emby to update the library with the given item."""
    url = f"{emby_url}/emby/Library/Media/Updated"
    payload = {"Updates": [{"Path": item_path, "UpdateType": update_type}]}
    headers = {"X-Emby-Token": emby_api_key}
    try:
        log(f"向 Emby 发送更新请求，路径：{item_path}，类型：{update_type}")
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        if response.status_code == 204:
            log(f"Item '{item_path}' {update_type.lower()} successfully.")
        else:
            log(f"Unexpected status code {response.status_code} for item '{item_path}'. Status code: {response.status_code}")
    except requests.exceptions.RequestException as e:
        log(f"Error occurred while updating item '{item_path}': {e}")
    except Exception as e:
        log(f"发生未知的错误：{e}")

def process_item_library(item_path: str) -> None:
    """Checks if the given item path is within an Emby library and triggers an update."""
    log(f"处理媒体库项目：{item_path}")
    url = f"{emby_url}/emby/Library/SelectableMediaFolders?api_key={emby_api_key}"
    try:
        # Simplified logic: Assume any valid media file should trigger an update.
        # The check against library folders can be complex and might not be necessary
        # if the monitored directories are already part of Emby libraries.
        # Emby will handle updates more intelligently if the path is known.
        response = requests.get(url) # Still check if API is reachable
        response.raise_for_status()
        create_item(item_path, "Created") # Send update for the specific file path
        return

        # Original logic kept commented for reference:
        # response = requests.get(url)
        # response.raise_for_status()
        # json_data: List[Dict[str, Any]] = response.json()
        # found_match = False  # Flag to indicate if a library match was found
        # for folder in json_data:
        #     for subfolder in folder["SubFolders"]:
        #         library_path = subfolder["Path"]
        #         # Check if the item_path starts with the library path.
        #         if item_path.startswith(library_path):
        #             log(f"找到匹配的子文件夹：{library_path}")
        #             create_item(item_path, "Created") # Send update for the specific file path
        #             found_match = True
        #             return  # Exit after finding a match
        # if not found_match:
        #     log(f"No Library match found for '{item_path}'.")

    except requests.exceptions.RequestException as e:
        log(f"Error occurred while getting library information or sending update: {e}")
    except Exception as e:
        log(f"发生未知的错误：{e}")

def get_table_name(directory: str) -> str:
    """Generates a safe table name from the directory path."""
    table_name = ''.join(c if c.isalnum() else '_' for c in directory)
    # Ensure the table name doesn't start with a digit if it happens
    if table_name and table_name[0].isdigit():
        table_name = '_' + table_name
    return f"table_{table_name}" if table_name else "table_default" # Add default case

def initialize_database(directory: str) -> None:
    """Initializes the SQLite database with a table for the given directory."""
    table_name = get_table_name(directory)
    if not table_name:
        log(f"无法为目录 '{directory}' 生成有效的表名。")
        return
    try:
        with db_lock:
            cursor = db_conn.cursor()
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS `{table_name}` (
                    path TEXT PRIMARY KEY,
                    last_modified REAL
                )
            """) # Use REAL for float timestamps
            db_conn.commit()
            log(f"数据库表 '{table_name}' 初始化完成。")
    except sqlite3.Error as e:
        log(f"数据库表 '{table_name}' 初始化失败：{e}")
    except Exception as e:
        log(f"数据库表 '{table_name}' 初始化时发生未知错误：{e}")

def is_table_empty(directory: str) -> bool:
    """Checks if the table for the given directory is empty."""
    table_name = get_table_name(directory)
    if not table_name: return True # Assume empty if table name is invalid
    try:
        with db_lock:
            cursor = db_conn.cursor()
            cursor.execute(f"SELECT COUNT(*) FROM `{table_name}`")
            count = cursor.fetchone()[0]
            return count == 0
    except sqlite3.Error as e:
        log(f"检查数据库表 '{table_name}' 是否为空时发生错误：{e}")
        return True  # Assume it's empty in case of an error
    except Exception as e:
        log(f"检查数据库表 '{table_name}' 时发生未知错误：{e}")
        return True

def file_exists_in_db(path: str, directory: str) -> bool:
    """Checks if a file path exists in the database table for the given directory."""
    table_name = get_table_name(directory)
    if not table_name: return False # Assume not exists if table name is invalid
    try:
        with db_lock:
            cursor = db_conn.cursor()
            cursor.execute(f"SELECT 1 FROM `{table_name}` WHERE path = ?", (path,))
            return cursor.fetchone() is not None
    except sqlite3.Error as e:
        log(f"检查文件是否存在于数据库表 '{table_name}' 时发生错误：{e}")
        return False
    except Exception as e:
        log(f"检查文件 '{path}' 在数据库表 '{table_name}' 时发生未知错误：{e}")
        return False


def add_file_to_db(path: str, last_modified: float, directory: str) -> None:
    """Adds a file path and its last modified timestamp to the database table for the given directory."""
    table_name = get_table_name(directory)
    if not table_name: return # Skip if table name is invalid
    try:
        with db_lock:
            cursor = db_conn.cursor()
            # Use REAL for last_modified
            cursor.execute(f"INSERT OR REPLACE INTO `{table_name}` (path, last_modified) VALUES (?, ?)", (path, last_modified))
            db_conn.commit()
            # Reduce log noise - maybe remove this log or make it conditional
            # log(f"添加/更新文件到数据库表 '{table_name}'：{path}")
    except sqlite3.Error as e:
        log(f"添加文件到数据库表 '{table_name}' 时发生错误：{e}")
    except Exception as e:
        log(f"添加文件 '{path}' 到数据库表 '{table_name}' 时发生未知错误：{e}")


def remove_file_from_db(path: str, directory: str) -> None:
    """Removes a file path from the database table for the given directory."""
    table_name = get_table_name(directory)
    if not table_name: return # Skip if table name is invalid
    try:
        with db_lock:
            cursor = db_conn.cursor()
            cursor.execute(f"DELETE FROM `{table_name}` WHERE path = ?", (path,))
            db_conn.commit()
            log(f"从数据库表 '{table_name}' 中删除文件：{path}")
    except sqlite3.Error as e:
        log(f"从数据库表 '{table_name}' 中删除文件时发生错误：{e}")
    except Exception as e:
        log(f"从数据库表 '{table_name}' 删除文件 '{path}' 时发生未知错误：{e}")


def monitor_directory(directory: str) -> None:
    """Recursively monitors a directory for new/modified media files and triggers Emby library updates, using a database."""
    table_name = get_table_name(directory)
    if not table_name:
        log(f"无法监控目录 '{directory}'，因为无法生成有效的表名。")
        return

    def scan_and_process_directory() -> None:
        try:
            current_files_on_disk = set()
            log(f"开始扫描目录 '{directory}'...") # Log start of scan

            # Scan disk for current files and their modification times
            files_to_check = {}
            for root, _, files in os.walk(directory):
                for file in files:
                    full_path = os.path.join(root, file)
                    try:
                        # Check extension first to avoid unnecessary getmtime
                        file_extension = os.path.splitext(full_path)[1][1:].lower()
                        if file_extension in ALLOWED_EXTENSIONS:
                            current_files_on_disk.add(full_path)
                            # Get mod time only for potentially relevant files
                            last_modified = os.path.getmtime(full_path)
                            files_to_check[full_path] = last_modified
                        # else: # Optional: log skipped files (can be noisy)
                        #     log(f"Skipping non-media file: {full_path}")

                    except FileNotFoundError:
                        log(f"扫描时文件已消失：{full_path}")
                        continue # Skip this file if it disappeared during scan
                    except OSError as e:
                        log(f"访问文件时出错 {full_path}: {e}")
                        continue # Skip problematic files (e.g., permission errors)

            log(f"目录 '{directory}' 扫描完成。找到 {len(current_files_on_disk)} 个媒体文件。")

            # Get files currently tracked in the database for this directory
            db_files_info = {}
            try:
                with db_lock:
                    cursor = db_conn.cursor()
                    # Retrieve path and last_modified time
                    cursor.execute(f"SELECT path, last_modified FROM `{table_name}`")
                    for row in cursor.fetchall():
                        db_files_info[row[0]] = row[1]
            except sqlite3.Error as e:
                 log(f"从数据库表 '{table_name}' 读取数据时出错: {e}")
                 # Decide how to handle this - maybe retry later or skip this cycle?
                 return # Skip processing this cycle if DB read fails


            # --- Process changes ---

            # 1. Check for New or Modified files
            for file_path, current_last_modified in files_to_check.items():
                db_last_modified = db_files_info.get(file_path)

                if db_last_modified is None:
                    # File is on disk but not in DB -> New file
                    log(f"新文件检测到: {file_path}")
                    process_item_library(file_path)
                    add_file_to_db(file_path, current_last_modified, directory)
                # Compare modification times (use a small tolerance if needed)
                elif current_last_modified > db_last_modified:
                    # File is on disk and in DB, but modified time is newer
                    log(f"修改文件检测到: {file_path}")
                    process_item_library(file_path) # Trigger update for modification too
                    add_file_to_db(file_path, current_last_modified, directory)

            # 2. Check for Deleted files
            # Files in DB but no longer on disk in this scan
            db_paths = set(db_files_info.keys())
            deleted_files = db_paths - current_files_on_disk
            for file_path in deleted_files:
                log(f"删除文件检测到: {file_path}")
                # Optional: Send a 'Deleted' update to Emby?
                # create_item(file_path, "Deleted") # This might require API changes or testing
                remove_file_from_db(file_path, directory)

        except Exception as e:
            log(f"扫描目录 '{directory}' 时发生未预料的错误：{e}")

    log(f"开始监控 '{directory}' 每 {MONITOR_INTERVAL} 秒...")

    # Initial delay before first scan can be useful
    # time.sleep(5)

    while True:
        log(f"开始扫描周期 '{directory}'...")
        scan_and_process_directory()
        log(f"扫描周期 '{directory}' 完成，等待 {MONITOR_INTERVAL} 秒...")
        time.sleep(MONITOR_INTERVAL)


def monitor_directory_threaded(directory: str) -> None:
    """Wraps monitor_directory to run it in a separate thread."""
    thread = threading.Thread(target=monitor_directory, args=(directory,))
    thread.daemon = True
    thread.start()

def populate_database(directory: str) -> None:
    """Populates the database for the given directory if the table is empty."""
    table_name = get_table_name(directory)
    if not table_name: return # Skip if table name invalid
    if is_table_empty(directory):
        log(f"数据库表 '{table_name}' 为空，开始填充数据库。")
        count = 0
        try:
            for root, _, files in os.walk(directory):
                for file in files:
                    full_path = os.path.join(root, file)
                    try:
                        # Only add files with allowed extensions during population
                        file_extension = os.path.splitext(full_path)[1][1:].lower()
                        if file_extension in ALLOWED_EXTENSIONS:
                            last_modified = os.path.getmtime(full_path)
                            add_file_to_db(full_path, last_modified, directory)
                            count += 1
                    except FileNotFoundError:
                         log(f"填充数据库时文件不存在: {full_path}")
                         continue # Skip if file disappears during population
                    except OSError as e:
                         log(f"填充数据库时访问文件出错 {full_path}: {e}")
                         continue # Skip problematic files

            log(f"数据库表 '{table_name}' 填充完毕，添加了 {count} 个文件。")
        except OSError as e:
            log(f"填充数据库时访问文件夹 {directory} 出现错误: {e}")
        except Exception as e:
            log(f"填充数据库表 '{table_name}' 时发生未知错误: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python script.py /path/to/monitor1 [/path/to/monitor2 ...]", file=sys.stderr)
        sys.exit(1)

    directories_to_monitor = sys.argv[1:]  # Get all arguments after the script name

    db_dir = os.path.dirname(monitor_database)
    if db_dir and not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir, exist_ok=True)
            log(f"创建数据库目录：{db_dir}")
        except OSError as e:
            log(f"创建数据库目录失败：{db_dir}, 错误: {e}")
            sys.exit(1)


    try:
        # Initialize global database connection
        # Use a timeout to prevent blocking indefinitely if DB is locked
        db_conn = sqlite3.connect(monitor_database, check_same_thread=False, timeout=10.0) # Increased timeout
        log(f"数据库连接成功：{monitor_database}")

        active_threads = []
        # Initialize database tables and populate them if empty
        for directory in directories_to_monitor:
            if not os.path.isdir(directory):
                log(f"错误：提供的路径不是一个有效的目录：{directory}")
                continue # Skip invalid directories

            log(f"正在初始化目录：{directory}")
            initialize_database(directory)
            populate_database(directory) # Populate only adds if empty

            # Start monitoring thread only for valid, initialized directories
            log(f"为目录启动监控线程: {directory}")
            thread = threading.Thread(target=monitor_directory, args=(directory,))
            thread.daemon = True
            thread.start()
            active_threads.append(thread)


        if not active_threads:
             log("没有有效的目录可监控，程序退出。")
             sys.exit(1)

        log(f"开始监控 {len(active_threads)} 个目录...")

        # Keep the main thread alive, checking if monitor threads are alive
        while True:
            # Optional: Check if threads are still running
            if not any(t.is_alive() for t in active_threads):
                 log("所有监控线程已停止。")
                 break
            time.sleep(60) # Check less frequently

    except sqlite3.Error as e:
        log(f"数据库连接或操作失败：{e}")
    except Exception as e:
        log(f"程序运行出错,错误信息：{e}")
    except KeyboardInterrupt:
        log("收到中断信号，正在关闭...")

    finally:
        if db_conn:
            db_conn.close()
            log("关闭数据库连接")
        log("程序退出。")
