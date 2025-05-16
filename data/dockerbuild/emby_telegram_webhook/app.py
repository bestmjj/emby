from flask import Flask, request, abort
import requests
from os import environ
import yaml
import logging
import time
from threading import Timer

app = Flask(__name__)

# 配置日志
#logging.basicConfig(level=logging.INFO,
#                    format='%(asctime)s - %(levelname)s - %(message)s')
#app.logger.setLevel(logging.INFO)

# 消息缓存
message_cache = {}
MESSAGE_DELAY = 5  # 等待 5 秒


def load_config():
    """加载配置信息."""
    try:
        with open("/config/config.yaml", "r") as f:
            config_data = yaml.safe_load(f)
        return config_data
    except FileNotFoundError:
        app.logger.error("Config file not found: /config/config.yaml")
        return None
    except yaml.YAMLError as e:
        app.logger.error(f"Error parsing config file: {e}")
        return None


def get_telegram_token(config):
    """获取 Telegram Token."""
    try:
        token = config["token"][0]
        return token
    except (KeyError, TypeError):
        app.logger.error("Telegram token not found in config.")
        return None


def get_emby_url(config):
    """获取 Emby Server URL."""
    try:
        server = config["emby-server"][0]
        return server
    except (KeyError, TypeError):
        app.logger.error("Emby server URL not found in config.")
        return None


def get_ids(config, key):
    """获取用户或管理员 ID 列表."""
    try:
        ids = config[key]
        if isinstance(ids, list):
            return ids
        else:
            app.logger.warning(f"{key} is not a list in config.  Returning None")
            return None
    except KeyError:
        app.logger.info(f"{key} not found in config.  Returning None")
        return None


def get_icon(argument):
    """根据事件类型获取对应图标."""
    icons = {
        "playback.start": "▶ ",
        "playback.stop": "⏹ ",
        "playback.pause": "⏸ ",
        "playback.unpause": "⏯ ",
        "library.deleted": "🗑 ",
        "item.markunplayed": "❎",
        "item.markplayed": "✅",
        "system.updateavailable": "💾",
        "user.authenticationfailed": "🔒",
        "user.authenticated": "🔐",
        "system.serverrestartrequired": "🔄",
        "plugins.pluginuninstalled": "📤",
        "plugins.plugininstalled": "📥",
    }
    return icons.get(argument, "")


def update(response, token, send_id):
    """处理 Emby 更新事件."""
    try:
        server_version = response["Server"]["Version"]
        new_version = response["PackageVersionInfo"]["versionStr"]
        info_url = response["PackageVersionInfo"]["infoUrl"]
        desc = response["PackageVersionInfo"]["description"]
        event = response["Event"]
        icon = get_icon(event)
        text = (
            f"{icon} Update from version {server_version} to {new_version} available"
            f"\nDescription: {desc}\nMore info: {info_url}"
        )
        send_telegram_message(token, send_id, text)
    except KeyError as e:
        app.logger.error(f"Missing key in update event: {e}")
    except Exception as e:
        app.logger.error(f"Error processing update event: {e}")


def marked(response, token, send_id):
    """处理 Emby 标记已读/未读事件."""
    try:
        event = response["Event"]
        item = response["Item"]
        icon = get_icon(event)
        item_type = item["Type"]

        if item_type == "Movie":
            item_name = item["Name"]
            text = f"{icon} Marked {'played' if 'markplayed' in event else 'unplayed'}: {item_name}"
        elif item_type == "Episode":
            series_name = item["SeriesName"]
            season_name = item["SeasonName"]
            episode_name = item["Name"]
            episode_number = item["IndexNumber"]
            text = (
                f"{icon} Marked {'played' if 'markplayed' in event else 'unplayed'}:"
                f" {series_name} {season_name} episode {episode_number} - {episode_name}"
            )
        else:
            app.logger.warning(f"Unsupported item type: {item_type}")
            return

        send_telegram_message(token, send_id, text)
    except KeyError as e:
        app.logger.error(f"Missing key in marked event: {e}")
    except Exception as e:
        app.logger.error(f"Error processing marked event: {e}")


def send_message(response, token, send_id):
    """发送 Emby 事件消息."""
    try:
        event = response["Event"]
        text = response["Title"]
        icon = get_icon(event)
        message = icon + text
        send_telegram_message(token, send_id, message)
    except KeyError as e:
        app.logger.error(f"Missing key in send_message event: {e}")
    except Exception as e:
        app.logger.error(f"Error processing send_message event: {e}")


def lib_new(response, token, send_id, emby_server):
    """处理 Emby 媒体库新增事件."""
    try:
        title = response.get("Title", "无标题")
        desc = response.get("Description", "**Can't get description**")
        item = response.get("Item")  # 使用 .get() 方法，如果不存在则返回 None

        if not item:
            app.logger.warning("Item is None in lib_new event, skipping image.")
            text = f"{title}\n\nDescription: {desc}"
            send_telegram_message(token, send_id, text)
            return

        if not emby_server:
            app.logger.error("emby_server is None, cannot construct image URL.")
            text = f"{title}\n\nDescription: {desc}"
            send_telegram_message(token, send_id, text)
            return

        item_id = item.get("Id")  # 使用 .get() 方法，如果不存在则返回 None
        if not item_id:
            app.logger.warning("Item ID is None in lib_new event, skipping image.")
            text = f"{title}\n\nDescription: {desc}"
            send_telegram_message(token, send_id, text)
            return
        container = item.get("Container")
        if not container:
            app.logger.warning("Container is None in lib_new event, skipping image.")
            text = f"{title}\n\nDescription: {desc}"
            send_telegram_message(token, send_id, text)
            return

        photo_url = f"{emby_server}/emby/Items/{item_id}/Images/Primary"
        files = None  # 初始化 files 变量
        image_response = None  # 初始化 image_response

        try:
            image_response = requests.get(photo_url, timeout=5)  # 添加超时
            image_response.raise_for_status()
            photo = ("photo.jpg", image_response.content, "image/jpeg")
            files = {"photo": photo}  # 赋值 files 变量
            caption = f"{title}\n\nDescription: {desc}"
            # send_telegram_message(token, send_id, None, photo=photo, caption=caption)
            message_data = {
                "token": token,
                "send_id": send_id,
                "text": None,
                "photo": photo,
                "caption": caption
            }

        except requests.exceptions.RequestException as e:
            app.logger.error(f"Failed to get image from {photo_url}: {e}")
            # text = f"{title}\n\nDescription: {desc}"
            # send_telegram_message(token, send_id, text)
            message_data = {
                "token": token,
                "send_id": send_id,
                "text": f"{title}\n\nDescription: {desc}",
                "photo": None,
                "caption": None
            }

        except Exception as e:
            app.logger.error(f"Failed to get image from {photo_url}: {e}")
            # text = f"{title}\n\nDescription: {desc}"
            # send_telegram_message(token, send_id, text)
            message_data = {
                "token": token,
                "send_id": send_id,
                "text": f"{title}\n\nDescription: {desc}",
                "photo": None,
                "caption": None
            }

        # 延迟发送消息
        schedule_message(item_id, message_data)

    except KeyError as e:
        app.logger.error(f"Missing key in lib_new event: {e}")
    except Exception as e:
        app.logger.error(f"Error processing lib_new event: {e}")


def send_telegram_message(token, chat_id, text, photo=None, caption=None):
    """发送 Telegram 消息."""
    base_url = f"https://api.telegram.org/bot{token}"
    if photo:
        url = f"{base_url}/sendPhoto"
        data = {
            "chat_id": chat_id,
            "caption": caption,
            "parse_mode": "Markdown",
        }
        try:
            response = requests.post(url, data=data, files={"photo": photo}, timeout=10)  # 添加超时
            response.raise_for_status()  # 检查 HTTP 状态码
            log_message = f"Message sent to chat_id {chat_id}: {caption[:50]}..." if caption else f"Message sent to chat_id {chat_id}: (No Caption)"
            app.logger.info(log_message)  # 记录发送的消息 (截取前50个字符)
        except requests.exceptions.RequestException as e:
            app.logger.error(f"Failed to send message to chat_id {chat_id}: {e}")

    else:
        url = f"{base_url}/sendMessage"
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        try:
            response = requests.post(url, data=data, timeout=10)  # 添加超时
            response.raise_for_status()  # 检查 HTTP 状态码
            log_message = f"Message sent to chat_id {chat_id}: {text[:50]}..." if text else f"Message sent to chat_id {chat_id}: (No Text)"
            app.logger.info(log_message)  # 记录发送的消息 (截取前50个字符)
        except requests.exceptions.RequestException as e:
            app.logger.error(f"Failed to send message to chat_id {chat_id}: {e}")

def schedule_message(item_id, message_data):
    """延迟发送消息."""
    if item_id in message_cache:
        # 取消之前的定时器
        message_cache[item_id].cancel()

    # 创建新的定时器
    timer = Timer(MESSAGE_DELAY, send_message_callback, args=[item_id, message_data])
    message_cache[item_id] = timer
    timer.start()


def send_message_callback(item_id, message_data):
    """发送消息的回调函数."""
    token = message_data["token"]
    send_id = message_data["send_id"]
    text = message_data["text"]
    photo = message_data["photo"]
    caption = message_data["caption"]

    send_telegram_message(token, send_id, text, photo, caption)

    # 从缓存中删除消息
    del message_cache[item_id]


def process_event(response, token, send_id, emby_server):
    """处理 Emby 事件，根据事件类型调用相应的处理函数."""
    event = response["Event"]
    app.logger.info(f"Received event: {event}")
    if "playback.start" in event:
        send_message(response, token, send_id)
    elif "playback.stop" in event:
        send_message(response, token, send_id)
    elif "playback.pause" in event:
        send_message(response, token, send_id)
    elif "playback.unpause" in event:
        send_message(response, token, send_id)
    elif "library.new" in event:
        lib_new(response, token, send_id, emby_server)
    elif "library.deleted" in event:
        send_message(response, token, send_id)
    elif "item.markunplayed" in event:
        marked(response, token, send_id)
    elif "item.markplayed" in event:
        marked(response, token, send_id)
    elif "system.updateavailable" in event:
        update(response, token, send_id)
    elif "user.authenticationfailed" in event:
        send_message(response, token, send_id)
    elif "user.authenticated" in event:
        send_message(response, token, send_id)
    elif "system.serverrestartrequired" in event:
        send_message(response, token, send_id)
    elif "plugins.pluginuninstalled" in event:
        send_message(response, token, send_id)
    elif "plugins.plugininstalled" in event:
        send_message(response, token, send_id)
    else:
        app.logger.warning(f"Unknown event: {event}")


@app.route("/webhook", methods=["POST"])
def webhook():
    """Emby Webhook 入口."""
    if request.method != "POST":
        abort(400)

    response = request.get_json()
    app.logger.debug(f"Received JSON: {response}")  # 记录收到的完整 JSON 数据

    config = load_config()
    if not config:
        app.logger.error("Config load failed, aborting webhook.")
        return "Config error", 500

    token = get_telegram_token(config)
    if not token:
        app.logger.error("Telegram token error, aborting webhook.")
        return "Telegram token error", 500

    emby_server = get_emby_url(config)
    if not emby_server:
        app.logger.error("Emby server URL error, aborting webhook.")
        return "Emby server URL error", 500

    admin_ids = get_ids(config, "admins")
    # user_ids = get_ids(config, "users")
    user_ids = None

    if admin_ids:
        for send_id in admin_ids:
            process_event(response, token, send_id, emby_server)

    if user_ids:
        for send_id in user_ids:
            #  For users, we ONLY process library.new and library.deleted events
            event = response["Event"]
            if "library.new" in event or "library.deleted" in event:
                process_event(response, token, send_id, emby_server)
            else:
                app.logger.debug(f"Skipping event {event} for user {send_id}")

    return "success", 200


@app.route("/")
def hello():
    return "Hello, World!"


if __name__ == "__main__":
    config = load_config()
    if config:
        debug = config.get("debug", False)
    else:
        debug = False

    # debug = True
    # 根据 debug 值设置日志级别
    if debug:
        logging.basicConfig(level=logging.DEBUG,
                            format='%(asctime)s - %(levelname)s - %(message)s')
        app.logger.setLevel(logging.DEBUG)
        app.logger.info("Debug mode enabled, setting log level to DEBUG.")  # 提示信息
    else:
        logging.basicConfig(level=logging.INFO,
                            format='%(asctime)s - %(levelname)s - %(message)s')
        app.logger.setLevel(logging.INFO)

    app.run(debug=debug, host="0.0.0.0")
