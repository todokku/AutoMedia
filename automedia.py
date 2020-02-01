#!/usr/bin/env python3

import feedparser
import subprocess
import os
import sys
import time
import json
import uuid
import errno
import signal
import transmissionrpc

from domain import url_extract_domain

from lxml import etree
from datetime import datetime

script_dir = os.path.dirname(os.path.realpath(sys.argv[0]))

config_dir = os.path.expanduser("~/.config/automedia")
rss_config_dir = os.path.join(config_dir, "rss")
html_config_dir = os.path.join(config_dir, "html")
automedia_pid_path = "/tmp/automedia.pid"

only_show_finished_notification = True

class TrackedRss:
    title = None
    latest = None
    link = None
    json_data = None

    def __init__(self, title, latest, link, json_data):
        self.title = title
        self.latest = latest
        self.link = link
        self.json_data = json_data

class TrackedHtml:
    title = None
    latest = None
    link = None
    plugin = None
    json_data = None

    def __init__(self, title, latest, link, plugin, json_data):
        self.title = title
        self.latest = latest
        self.link = link
        self.plugin = plugin
        self.json_data = json_data

class TorrentProgress:
    id = None
    name = None
    progress = None

    def __init__(self, id, name, progress):
        self.id = id
        self.name = name
        self.progress = progress

class HtmlItemProgress:
    name = None
    finished = None

    def __init__(self, name, finished):
        self.name = name
        self.finished = finished

def get_file_content_or_none(path):
    try:
        with open(path, "r") as file:
            return file.read()
    except FileNotFoundError:
        return None

def get_tracked_rss_by_title(tracked_rss, title):
    for t in tracked_rss:
        if t.title == title:
            return t
    return None

def get_tracked_rss(rss_tracked_dir, existing_tracked_rss):
    try:
        tracked_rss = []
        for title in os.listdir(rss_tracked_dir):
            # Check if we already have the data for the title
            #if get_tracked_rss_by_title(existing_tracked_rss, title):
            #    continue

            in_progress = get_file_content_or_none(os.path.join(rss_tracked_dir, title, ".in_progress"))
            if in_progress:
                print("Skipping in-progress rss %s" % title)
                continue
            latest = get_file_content_or_none(os.path.join(rss_tracked_dir, title, "latest"))
            link = get_file_content_or_none(os.path.join(rss_tracked_dir, title, "link"))
            json_data = get_file_content_or_none(os.path.join(rss_tracked_dir, title, "data"))
            if json_data:
                json_data = json.loads(json_data)
            else:
                updated = str(time.time())
                json_data = {
                    "link": link,
                    "updated": updated,
                    "downloaded": []
                }
                if latest:
                    json_data["downloaded"].append({ "title": latest, "time": updated })
            if not link or not json_data:
                print("Rss corrupt, link or data missing for rss %s" % title)
                continue
            tracked_rss.append(TrackedRss(title, latest, link, json_data))
        return tracked_rss
    except FileNotFoundError:
        return []

def rss_update_latest(rss_tracked_dir, rss, latest, url):
    with open(os.path.join(rss_tracked_dir, rss.title, "latest"), "w") as file:
        file.write(latest)

    updated = str(time.time())
    with open(os.path.join(rss_tracked_dir, rss.title, "updated"), "w") as file:
        file.write(updated)

    rss.json_data["updated"] = updated
    rss.json_data["downloaded"].append({ "title": latest, "time": updated, "url": url })
    with open(os.path.join(rss_tracked_dir, rss.title, "data"), "w") as file:
        json.dump(rss.json_data, file, indent=4)

def html_update_latest(html_tracked_dir, html, latest, url):
    with open(os.path.join(html_tracked_dir, html.title, "latest"), "w") as file:
        file.write(latest)

    updated = str(time.time())
    with open(os.path.join(html_tracked_dir, html.title, "updated"), "w") as file:
        file.write(updated)

    html.json_data["updated"] = updated
    html.json_data["downloaded"].append({ "title": latest, "time": updated, "url": url })
    with open(os.path.join(html_tracked_dir, html.title, "data"), "w") as file:
        json.dump(html.json_data, file, indent=4)

def get_tracked_html(html_tracked_dir):
    try:
        tracked_html = []
        for title in os.listdir(html_tracked_dir):
            in_progress = get_file_content_or_none(os.path.join(html_tracked_dir, title, ".in_progress"))
            if in_progress:
                print("Skipping in-progress html %s" % title)
                continue
            latest = get_file_content_or_none(os.path.join(html_tracked_dir, title, "latest"))
            link = get_file_content_or_none(os.path.join(html_tracked_dir, title, "link"))
            if not link:
                print("html corrupt, link missing for html %s" % title)
                continue
            plugin = get_file_content_or_none(os.path.join(html_tracked_dir, title, "plugin"))
            json_data = get_file_content_or_none(os.path.join(html_tracked_dir, title, "data"))
            if json_data:
                json_data = json.loads(json_data)
            else:
                updated = str(time.time())
                json_data = {
                    "plugin": plugin,
                    "link": link,
                    "updated": updated,
                    "downloaded": []
                }
                if latest:
                    json_data["downloaded"].append({ "title": latest, "time": updated })
            if not plugin or not json_data:
                print("html corrupt, plugin or data missing for html %s" % title)
                continue
            tracked_html.append(TrackedHtml(title, latest, link, plugin, json_data))
        return tracked_html
    except FileNotFoundError:
        return []

# @urgency should either be "low", "normal" or "critical"
def show_notification(title, body, urgency="normal"):
    subprocess.Popen(["notify-send", "-u", urgency, "--", title, body])

def fetch_page(url):
    process = subprocess.Popen(["curl", "-s", "-L", "--output", "-", url], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        # TODO: Add file to list of failed files, so the user knows which they should manually download
        if not only_show_finished_notification:
            show_notification("Download failed", "Failed to fetch page: {}, error: {}".format(url, stderr.decode('utf-8')), urgency="critical")
        return None
    return stdout.decode('utf-8')

def is_torrent_daemon_running():
    process = subprocess.Popen(["transmission-remote", "-si"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    process.communicate()
    return process.returncode == 0

def start_torrent_daemon(download_dir):
    # TODO: Make seed ratio configurable
    process = subprocess.Popen(["transmission-daemon", "--global-seedratio", "2.0", "--download-dir", download_dir])
    process.communicate()
    while not is_torrent_daemon_running():
        time.sleep(0.1)
    return process.returncode == 0

def add_torrent(torrent_link):
    process = subprocess.Popen(["transmission-remote", "--add", torrent_link], stderr=subprocess.PIPE)
    _, stderr = process.communicate()
    if process.returncode != 0:
        if not only_show_finished_notification:
            show_notification("Download failed", "Failed to download torrent: {}, error: {}".format(torrent_link, stderr.decode('utf-8')), urgency="critical")
    return process.returncode == 0

def get_torrent_progress(tc):
    torrent_progress = []
    for torrent in tc.get_torrents():
        torrent_progress.append(TorrentProgress(torrent.id, torrent.name, torrent.progress))
    return torrent_progress

def get_finished_torrents(torrents):
    filtered_torrents = []
    for torrent in torrents:
        if abs(100.0 - torrent.progress) <= 0.001:
            filtered_torrents.append(torrent)
    return filtered_torrents

def get_unfinished_torrents(torrents):
    filtered_torrents = []
    for torrent in torrents:
        if abs(100.0 - torrent.progress) > 0.001:
            filtered_torrents.append(torrent)
    return filtered_torrents

def get_matching_torrents_by_name(torrents1, torrents2):
    matching_torrents = []
    for torrent1 in torrents1:
        for torrent2 in torrents2:
            if torrent1.id == torrent2.id:
                matching_torrents.append(torrent1.name)
    return matching_torrents

def get_html_items_progress(download_dir, tracked_html):
    items = []
    for html in tracked_html:
        item_dir = os.path.join(download_dir, html.title)
        try:
            for item in os.listdir(item_dir):
                finished = os.path.isfile(os.path.join(item_dir, item, ".finished"))
                items.append(HtmlItemProgress(html.title + "/" + item, finished))
        except FileNotFoundError:
            pass
    return items

def get_matching_html_items_by_name(html_items1, html_items2):
    matching_items = []
    for html_item1 in html_items1:
        for html_item2 in html_items2:
            if html_item1.name == html_item2.name:
                matching_items.append(html_item1.name)
    return matching_items

def add_rss(name, url, rss_config_dir, start_after):
    feed = feedparser.parse(url)
    if feed.bozo == 1:
        print("Failed to add rss, error: {}".format(str(feed.bozo_exception)))
        return False
        
    if not name:
        name = feed["channel"]["title"].replace("/", "_").strip()

    if not name or len(name) == 0:
        print("Name not provided and name in rss is empty")
        return False

    start_after_url = None
    found_start_after = False
    for item in feed["items"]:
        title = item["title"].replace("/", "_").strip()
        if start_after and title == start_after:
            found_start_after = True
            start_after_url = item["link"]
            break
    
    if start_after and not found_start_after:
        print("Failed to find %s in rss %s" % (start_after, url))
        return False

    name = name.replace("/", "_")
    rss_dir = os.path.join(rss_config_dir, "tracked", name)
    os.makedirs(rss_dir)

    # Create an ".in_progress" file to prevent periodic sync from reading rss data
    # before we have finished adding all the data.
    # Timestamp is added to it to make it possible to automatically cleanup rss that is corrupted
    # (for example if the computer crashes before the in_progress file is removed).
    in_progress_filepath = os.path.join(rss_dir, ".in_progress")
    with open(in_progress_filepath, "w") as file:
        file.write(str(time.time()))

    with open(os.path.join(rss_dir, "link"), "w") as file:
        file.write(url)
    
    if start_after:
        with open(os.path.join(rss_dir, "latest"), "w") as file:
            file.write(start_after)

    updated = str(time.time())
    with open(os.path.join(rss_dir, "updated"), "w") as file:
        file.write(updated)

    data = {
        "link": url,
        "updated": updated,
        "downloaded": []
    }
    if start_after:
        data["downloaded"].append({ "title": start_after, "time": updated, "url": start_after_url })

    with open(os.path.join(rss_dir, "data"), "w") as file:
        json.dump(data, file, indent=4)
    
    os.remove(in_progress_filepath)
    return True

def add_html(name, url, html_config_dir, start_after):
    domain = url_extract_domain(url)
    if len(domain) == 0:
        print("Invalid url: {}".format(url))
        return False
    domain_plugin_path = os.path.join(script_dir, "plugins", domain)
    domain_plugin_py_path = os.path.join(script_dir, "plugins", domain + ".py")

    plugin_path = None
    if os.path.isfile(domain_plugin_path):
        plugin_path = domain_plugin_path
    elif os.path.isfile(domain_plugin_py_path):
        plugin_path = domain_plugin_py_path
    else:
        print("Plugin doesn't exist: {}".format(domain))
        return False

    if not name or len(name) == 0:
        print("Name not provided or empty")
        return False
 
    start_after_url = None
    if start_after:
        items = plugin_list(plugin_path, url, None)
        if items:
            found_start_after = False
            for item in reversed(items):
                title = item["name"].replace("/", "_").strip()
                if start_after and title == start_after:
                    found_start_after = True
                    start_after_url = item["url"]
                    break
            
            if not found_start_after:
                print("Failed to find %s in html %s" % (start_after, url))
                return False

    name = name.replace("/", "_")
    html_dir = os.path.join(html_config_dir, "tracked", name)
    os.makedirs(html_dir)

    # Create an ".in_progress" file to prevent periodic sync from reading rss data
    # before we have finished adding all the data.
    # Timestamp is added to it to make it possible to automatically cleanup rss that is corrupted
    # (for example if the computer crashes before the in_progress file is removed).
    in_progress_filepath = os.path.join(html_dir, ".in_progress")
    with open(in_progress_filepath, "w") as file:
        file.write(str(int(time.time())))

    with open(os.path.join(html_dir, "link"), "w") as file:
        file.write(url)

    with open(os.path.join(html_dir, "plugin"), "w") as file:
        file.write(os.path.basename(plugin_path))
    
    if start_after:
        with open(os.path.join(html_dir, "latest"), "w") as file:
            file.write(start_after)

    updated = str(time.time())
    with open(os.path.join(html_dir, "updated"), "w") as file:
        file.write(updated)

    data = {
        "plugin": os.path.basename(plugin_path),
        "link": url,
        "updated": updated,
        "downloaded": []
    }
    if start_after:
        data["downloaded"].append({ "title": start_after, "time": updated, "url": start_after_url })

    with open(os.path.join(html_dir, "data"), "w") as file:
        json.dump(data, file, indent=4)
    
    os.remove(in_progress_filepath)
    return True

def get_downloaded_item_by_title(tracked_rss, title):
    for item in tracked_rss.json_data["downloaded"]:
        if item.title == title:
            return item
    return None

# Return the title of the newest item
def sync_rss(tracked_rss):
    rss_tracked_dir = os.path.join(rss_config_dir, "tracked")
    feed = feedparser.parse(tracked_rss.link)
    if feed.bozo == 1:
        print("{}: Failed to sync rss for url {}, error: {}".format(str(datetime.today().isoformat()), tracked_rss.link, str(feed.bozo_exception)))
        if not only_show_finished_notification:
            show_notification("RSS Sync failed", "Failed to parse rss for url {}, error: {}".format(tracked_rss.link, str(feed.bozo_exception)), urgency="critical")
        return None

    seen_titles = set()
    seen_urls = set()
    for downloaded_item in tracked_rss.json_data["downloaded"]:
        seen_titles.add(downloaded_item["title"].lower().replace(" ", ""))
        seen_urls.add(downloaded_item.get("url", ""))

    items = []
    for item in feed["items"]:
        title = item["title"].replace("/", "_").strip()
        link = item["link"]
        # TODO: Goto next page in rss if supported, if we cant find our item on the first page
        #if not get_downloaded_item_by_title(tracked_rss, title):
        if title.lower().replace(" ", "") in seen_titles or link in seen_urls:
            break
        items.append(item)

    # Add torrents from the oldest to the newest, and stop when failing to add torrent.
    # If it fails, there will be an attempt to add them again after next sync cycle.
    latest = None
    for item in reversed(items):
        title = item["title"].replace("/", "_").strip()
        link = item["link"]
        rss_update_latest(rss_tracked_dir, tracked_rss, title, link)

        if not add_torrent(link):
            return latest
        latest = title
        if not only_show_finished_notification:
            show_notification("Download started", latest)
    return latest

def plugin_list(plugin_path, url, latest):
    if not latest:
        latest = []

    plugin_name = os.path.basename(plugin_path)
    process = None
    try:
        process = subprocess.Popen([plugin_path, "list", url], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE)
    except FileNotFoundError as e:
        print("{}: Plugin failed: Failed to launch plugin list for plugin {}, error: {}".format(str(datetime.today().isoformat()), plugin_name, str(e)))
        return None

    stdout, stderr = process.communicate(json.dumps(latest).encode())
    if process.returncode != 0:
        print("{}: Plugin failed: Failed to launch plugin list for plugin {} and url {}, error: stdout: {}, stderr: {}".format(str(datetime.today().isoformat()), plugin_name, url, stdout.decode('utf-8'), stderr.decode('utf-8')))
        if not only_show_finished_notification:
            show_notification("Plugin failed", "Failed to launch plugin list for plugin {} and url {}, error: stdout: {}, stderr: {}".format(plugin_name, url, stdout.decode('utf-8'), stderr.decode('utf-8')), urgency="critical")
        return None

    try:
        return json.loads(stdout.decode('utf-8'))
    except json.decoder.JSONDecodeError as e:
        if not only_show_finished_notification:
            show_notification("Plugin failed", "Failed to json decode response of plugin {}, error: {}".format(plugin_name, str(e)), urgency="critical")
        return None

def plugin_download(plugin_path, url, download_dir):
    process = subprocess.Popen([plugin_path, "download", url, download_dir], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    process.communicate()
    return process.returncode == 0

def resume_tracked_html(plugin_entry, download_dir, tracked_html, session_id):
    # TODO: Instead of redownloading, add resuming. This could be done by adding the files that have been downloaded to a file.
    # Redownload items we can detect have stopped. This can happen if the computer crashes or loses connection while downloading.
    title_dir = os.path.join(download_dir, tracked_html.title)
    try:
        for item in os.listdir(title_dir):
            item_dir = os.path.join(title_dir, item)
            if os.path.isfile(os.path.join(item_dir, ".finished")):
                continue
            
            in_progress_path = os.path.join(item_dir, ".in_progress")
            url = get_file_content_or_none(in_progress_path)
            # Item has finished downloading
            if not url:
                continue

            invalid_session = False
            try:
                with open(os.path.join(item_dir, ".session_id"), "r") as file:
                    item_session_id = file.read()
                    if item_session_id != session_id:
                        invalid_session = True
            except FileNotFoundError as e:
                invalid_session = True
            
            if invalid_session:
                #if not only_show_finished_notification:
                show_notification("Resuming", "Resuming download for item {} with plugin {}".format(os.path.join(tracked_html.title, item), tracked_html.plugin))
                with open(os.path.join(item_dir, ".session_id"), "w") as file:
                    file.write(session_id)
                plugin_download(plugin_entry, url, item_dir)

    except FileNotFoundError as e:
        pass

def build_plugin_list_input(tracked_html):
    result = []
    for downloaded_item in tracked_html.json_data["downloaded"]:
        result.append({ "title": downloaded_item["title"], "url": downloaded_item.get("url", "") })
    return result

# Return the title of the newest item
def sync_html(tracked_html, download_dir, session_id):
    plugin_entry = os.path.join(script_dir, "plugins", tracked_html.plugin)
    resume_tracked_html(plugin_entry, download_dir, tracked_html, session_id)
    html_tracked_dir = os.path.join(html_config_dir, "tracked")

    # The program takes and index starting from 1, which is the chapter number

    # Program should print the names of each item (chapter for manga) after "latest", sorted by newest to oldest
    # along with the urls to them.
    # Only get the items before the one called @latest. The printed data should be in this json format:
    #   [
    #     {
    #       "name": "Example name",
    #       "url": "https://example.com"
    #     },
    #     {
    #       "name": "Another item",
    #       "url": "https://another.url.com"
    #     }
    #   ]
    # ./program list url latest
    # Note: @latest argument here is optional
    items = plugin_list(plugin_entry, tracked_html.link, build_plugin_list_input(tracked_html))
    if not items:
        return None

    # Start downloading asynchronously using url.
    # A file called ".in_progress" should be added to the download directory when the download is in progress.
    # The ".in_progress" file should contain the url that was used to download the item.
    # A file called ".finished" should be added to the download directory when the download has finished.
    # ./program download url download_dir
    latest = None
    for item in reversed(items):
        url = item["url"]
        name = item["name"].replace("/", "_").strip()
        item_dir = os.path.join(download_dir, tracked_html.title, name)
        os.makedirs(item_dir, exist_ok=True)

        with open(os.path.join(item_dir, ".session_id"), "w") as file:
            file.write(session_id)

        html_update_latest(html_tracked_dir, tracked_html, name, url)

        if not plugin_download(plugin_entry, url, item_dir):
            return latest

        latest = name
        if not only_show_finished_notification:
            show_notification("Download started", "{}/{}".format(tracked_html.title, name))
    return latest

def sync(rss_config_dir, html_config_dir, download_dir, sync_rate_sec):
    os.makedirs(download_dir, exist_ok=True)
    if not is_torrent_daemon_running():
        if not start_torrent_daemon(download_dir):
            print("Failed to start torrent daemon")
            exit(2)
        print("Started torrent daemon with download directory {}".format(download_dir))

    rss_tracked_dir = os.path.join(rss_config_dir, "tracked")
    html_tracked_dir = os.path.join(html_config_dir, "tracked")
    # This is also check rate for html items
    check_torrent_status_rate_sec = 15
    unfinished_torrents = []
    unfinished_html_items = []

    # TODO: Remove this and keep a list of "in progress" html items in memory instead.
    session_id = uuid.uuid4().hex

    tc = transmissionrpc.Client("127.0.0.1")
    
    running = True
    tracked_rss = []
    while running:
        tracked_rss = get_tracked_rss(rss_tracked_dir, tracked_rss)
        for rss in tracked_rss:
            print("{}: rss: Syncing {}".format(str(datetime.today().isoformat()), rss.title))
            sync_rss(rss)
            # Add last synced timestamp. This together with "updated" file is used to remove series
            # that haven't updated in a long time (either finished series or axes series)
            with open(os.path.join(rss_tracked_dir, rss.title, "synced"), "w") as file:
                file.write(str(time.time()))
            #else:
            #    print("No 'latest' item found for rss (maybe we already have the latest item?) %s" % rss.title)
            #time.sleep(0.5) # Sleep between fetching rss so we don't get banned for spamming

        tracked_html = get_tracked_html(html_tracked_dir)
        for html in tracked_html:
            print("{}: html({}): Syncing {}".format(str(datetime.today().isoformat()), html.plugin, html.title))
            sync_html(html, download_dir, session_id)
            # Add last synced timestamp. This together with "updated" file is used to remove series
            # that haven't updated in a long time (either finished series or axes series)
            with open(os.path.join(html_tracked_dir, html.title, "synced"), "w") as file:
                file.write(str(time.time()))
            #else:
            #    print("No 'latest' item found for html (maybe we already have the latest item?) %s" % html.title)
            #time.sleep(0.5) # Sleep between fetching html so we don't get banned for spamming
        
        # Check torrent status with sleeping until it's time to sync rss
        count = 0
        while count < sync_rate_sec/check_torrent_status_rate_sec:
            html_items = get_html_items_progress(download_dir, tracked_html)
            finished_html_items = [html_item for html_item in html_items if html_item.finished]
            newly_finished_html_items = get_matching_html_items_by_name(finished_html_items, unfinished_html_items)
            for newly_finished_html_item in newly_finished_html_items:
                show_notification("Download finished", newly_finished_html_item)
            unfinished_html_items = [html_item for html_item in html_items if not html_item.finished]

            torrents = get_torrent_progress(tc)
            finished_torrents = get_finished_torrents(torrents)
            newly_finished_torrents = get_matching_torrents_by_name(finished_torrents, unfinished_torrents)
            for newly_finished_torrent in newly_finished_torrents:
                show_notification("Download finished", newly_finished_torrent)
            unfinished_torrents = get_unfinished_torrents(torrents)

            time.sleep(check_torrent_status_rate_sec)
            count += 1

def usage():
    print("usage: automedia.py COMMAND")
    print("")
    print("COMMANDS")
    print("  add\tAdd media to track")
    print("  sync\tStart syncing tracked media")
    exit(1)

def usage_add():
    print("usage: automedia.py add <type> <url> [--name name] [--start-after start_after]")
    print("OPTIONS")
    print("  type\t\tThe type should be either rss or html")
    print("  url\t\tThe url to the rss or html")
    print("  --name\t\tThe display name to be used for the media. Optional for rss, in which case the name will be retries from rss TITLE, required for html")
    print("  --start-after\t\tThe sync should start downloading media after this item (Optional, default is to start from the first item)")
    print("EXAMPLES")
    print("  automedia.py add rss 'https://nyaa.si/?page=rss&q=Tejina-senpai+1080p&c=0_0&f=0&u=HorribleSubs'")
    print("  automedia.py add html 'https://manganelo.com/manga/read_naruto_manga_online_free3' --name Naruto")
    exit(1)

def usage_sync():
    print("usage: automedia.py sync <download_dir>")
    print("OPTIONS")
    print("  download_dir\tThe path where media should be downloaded to")
    print("EXAMPLES")
    print("  automedia.py sync /home/adam/Downloads/automedia")
    exit(1)

def command_add(args):
    if len(args) < 2:
        usage_add()

    media_type = args[0]
    media_url = args[1]
    media_name = None
    start_after = None

    option = None
    for arg in args[2:]:
        if arg in [ "--name", "--start-after"]:
            if option:
                usage_add()
            option = arg
        else:
            if not option:
                usage_add()

            if option == "--name":
                media_name = arg
            elif option == "--start-after":
                start_after = arg
            else:
                print("Invalid option %s" % option)
                usage_add()
            option = None

    if start_after:
        start_after = start_after.replace("/", "_").strip()

    if media_type == "rss":
        os.makedirs(rss_config_dir, exist_ok=True)
        result = add_rss(media_name, media_url, rss_config_dir, start_after)
        if not result:
            exit(2)
    elif media_type == "html":
        if not media_name:
            print("missing --name for media of type 'html'")
            usage_add()

        os.makedirs(html_config_dir, exist_ok=True)
        result = add_html(media_name, media_url, html_config_dir, start_after)
        if not result:
            exit(2)
    else:
        print("type should be either rss or html")
        usage_add()

def command_sync(args):
    if len(args) < 1:
        usage_sync()

    download_dir = args[0]
    if not download_dir:
        usage_sync()

    pid_file = None
    while True:
        try:
            pid_file = os.open(automedia_pid_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise

            running_automedia_pid = get_file_content_or_none(automedia_pid_path)
            if running_automedia_pid:
                cmdline = get_file_content_or_none("/proc/%s/cmdline" % running_automedia_pid)
                if cmdline and "automedia.py" in cmdline and "sync" in cmdline:
                    print("AutoMedia is already running with sync")
                    exit(0)
            os.remove(automedia_pid_path)

    def signal_handler(signum, frame):
        os.unlink(automedia_pid_path)
        exit(1)
    signal.signal(signal.SIGINT, signal_handler)

    os.write(pid_file, ("%s" % os.getpid()).encode())
    os.close(pid_file)

    os.makedirs(rss_config_dir, exist_ok=True)
    os.makedirs(html_config_dir, exist_ok=True)

    sync_rate_sec = 15 * 60 # every 15 min
    sync(rss_config_dir, html_config_dir, download_dir, sync_rate_sec)

def data_file_get_downloaded(data_filepath):
    downloaded = []
    try:
        with open(data_filepath, "r") as file:
            for item in json.loads(file.read())["downloaded"]:
                downloaded.append(item)
    except OSError:
        pass
    return downloaded

def get_downloaded_items(tracked_dir, is_html):
    downloaded_items = []
    try:
        downloaded_items = []
        for name in os.listdir(tracked_dir):
            data_filepath = os.path.join(tracked_dir, name, "data")
            downloaded = data_file_get_downloaded(data_filepath)
            for item in downloaded:
                if item.get("time"):
                    if is_html:
                        item["title"] = os.path.join(name, item["title"])
                    downloaded_items.append(item)
    except OSError:
        pass
    return downloaded_items

def command_downloaded():
    downloaded_items = []
    downloaded_items.extend(get_downloaded_items(os.path.join(rss_config_dir, "tracked"), False))
    downloaded_items.extend(get_downloaded_items(os.path.join(html_config_dir, "tracked"), True))
    downloaded_items = sorted(downloaded_items, key=lambda item: float(item["time"]))
    for item in downloaded_items:
        print(item["title"])

def main():
    if len(sys.argv) < 2:
        usage()

    command = sys.argv[1]
    if command == "add":
        command_add(sys.argv[2:])
    elif command == "sync":
        command_sync(sys.argv[2:])
    elif command == "downloaded":
        command_downloaded()
    else:
        usage()

if __name__ == "__main__":
    main()
