#!/usr/bin/env python3

import feedparser
import subprocess
import argparse
import os
import sys
import time
import json
import uuid
# TODO: Remove this shit. It gives warning and it's slow
import tldextract
import transmissionrpc

from lxml import etree
from datetime import datetime

script_dir = os.path.dirname(os.path.realpath(sys.argv[0]))

config_dir = os.path.expanduser("~/.config/automedia")

class TrackedRss:
    title = None
    latest = None
    link = None

    def __init__(self, title, latest, link):
        self.title = title
        self.latest = latest
        self.link = link

class TrackedHtml:
    title = None
    latest = None
    link = None
    plugin = None

    def __init__(self, title, latest, link, plugin):
        self.title = title
        self.latest = latest
        self.link = link
        self.plugin = plugin

class TorrentProgress:
    name = None
    progress = None

    def __init__(self, name, progress):
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
    except FileNotFoundError as e:
        return None

def get_tracked_rss(rss_tracked_dir):
    try:
        tracked_rss = []
        for title in os.listdir(rss_tracked_dir):
            in_progress = get_file_content_or_none(os.path.join(rss_tracked_dir, title, "in_progress"))
            if in_progress:
                print("Skipping in-progress rss %s" % title)
                continue
            latest = get_file_content_or_none(os.path.join(rss_tracked_dir, title, "latest"))
            link = get_file_content_or_none(os.path.join(rss_tracked_dir, title, "link"))
            if not link:
                print("Rss corrupt, link missing for rss %s" % title)
                continue
            tracked_rss.append(TrackedRss(title, latest, link))
        return tracked_rss
    except FileNotFoundError as e:
        return []

def rss_update_latest(rss_tracked_dir, rss, latest):
    with open(os.path.join(rss_tracked_dir, rss.title, "latest"), "w") as file:
        file.write(latest)

def html_update_latest(html_tracked_dir, html, latest):
    with open(os.path.join(html_tracked_dir, html.title, "latest"), "w") as file:
        file.write(latest)

def get_tracked_html(html_tracked_dir):
    try:
        tracked_html = []
        for title in os.listdir(html_tracked_dir):
            in_progress = get_file_content_or_none(os.path.join(html_tracked_dir, title, "in_progress"))
            if in_progress:
                print("Skipping in-progress html %s" % title)
                continue
            latest = get_file_content_or_none(os.path.join(html_tracked_dir, title, "latest"))
            link = get_file_content_or_none(os.path.join(html_tracked_dir, title, "link"))
            if not link:
                print("html corrupt, link missing for html %s" % title)
                continue
            plugin = get_file_content_or_none(os.path.join(html_tracked_dir, title, "plugin"))
            if not link:
                print("html corrupt, plugin missing for html %s" % title)
                continue
            tracked_html.append(TrackedHtml(title, latest, link, plugin))
        return tracked_html
    except FileNotFoundError as e:
        return []

# @urgency should either be "low", "normal" or "critical"
def show_notification(title, body, urgency="normal"):
    process = subprocess.Popen(["notify-send", "-u", urgency, title, body])
    #process.communicate()

def fetch_page(url):
    process = subprocess.Popen(["curl", "-s", "-L", "--output", "-", url], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        # TODO: Add file to list of failed files, so the user knows which they should manually download
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
        show_notification("Download failed", "Failed to download torrent: {}, error: {}".format(torrent_link, stderr.decode('utf-8')), urgency="critical")
    return process.returncode == 0

def get_torrent_progress(tc):
    torrent_progress = []
    for torrent in tc.get_torrents():
        torrent_progress.append(TorrentProgress(torrent.name, torrent.progress))
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
            if torrent1.name == torrent2.name:
                matching_torrents.append(torrent1.name)
    return matching_torrents

def get_html_items_progress(download_dir, tracked_html):
    items = []
    for html in tracked_html:
        item_dir = os.path.join(download_dir, html.title)
        try:
            for item in os.listdir(item_dir):
                finished = os.path.isfile(os.path.join(item_dir, item, "finished"))
                items.append(HtmlItemProgress(html.title + "/" + item, finished))
        except FileNotFoundError as e:
            pass
    return items

def get_matching_html_items_by_name(html_items1, html_items2):
    matching_items = []
    for html_item1 in html_items1:
        for html_item2 in html_items2:
            if html_item1.name == html_item2.name:
                matching_items.append(html_item1.name)
    return matching_items

def update_downloaded_item_list(downloaded_item):
    with open(os.path.join(config_dir, "downloaded"), "a") as file:
        file.write("{}\n".format(downloaded_item))

def add_rss(url, rss_config_dir, start_after):
    feed = feedparser.parse(url)
    if 'bozo_exception' in feed:
        print("Failed to add rss, error: {}".format(str(feed.bozo_exception)))
        return False
        
    rss_name = feed["channel"]["title"].strip().replace("/", "_")
    rss_dir = os.path.join(rss_config_dir, "tracked", rss_name)
    os.makedirs(rss_dir)

    found_start_after = False
    for item in feed["items"]:
        title = item["title"].strip()
        if start_after and title == start_after:
            found_start_after = True
            break
    
    if start_after and not found_start_after:
        print("Failed to find %s in rss %s" % (start_after, url))
        return False

    # Create an "in_progress" file to prevent periodic sync from reading rss data
    # before we have finished adding all the data.
    # Timestamp is added to it to make it possible to automatically cleanup rss that is corrupted
    # (for example if the computer crashes before the in_progress file is removed).
    in_progress_filepath = os.path.join(rss_dir, "in_progress")
    with open(in_progress_filepath, "w") as file:
        file.write(str(time.time()))

    with open(os.path.join(rss_dir, "link"), "w") as file:
        file.write(url)
    
    if start_after:
        with open(os.path.join(rss_dir, "latest"), "w") as file:
            file.write(start_after)
    
    os.remove(in_progress_filepath)
    return True

def add_html(name, url, html_config_dir, start_after):
    domain = tldextract.extract(url).domain
    domain_plugin_file_exists = os.path.isfile(os.path.join(script_dir, "plugins", domain))
    domain_plugin_file_py_exists = os.path.isfile(os.path.join(script_dir, "plugins", domain + ".py"))
    if not domain_plugin_file_exists and not domain_plugin_file_py_exists:
        print("Plugin doesn't exist: {}".format(domain))
        exit(2)

    name = name.replace("/", "_")
    html_dir = os.path.join(html_config_dir, "tracked", name)
    os.makedirs(html_dir)

    # Create an "in_progress" file to prevent periodic sync from reading rss data
    # before we have finished adding all the data.
    # Timestamp is added to it to make it possible to automatically cleanup rss that is corrupted
    # (for example if the computer crashes before the in_progress file is removed).
    in_progress_filepath = os.path.join(html_dir, "in_progress")
    with open(in_progress_filepath, "w") as file:
        file.write(str(int(time.time())))

    with open(os.path.join(html_dir, "link"), "w") as file:
        file.write(url)

    with open(os.path.join(html_dir, "plugin"), "w") as file:
        if domain_plugin_file_exists:
            file.write(domain)
        elif domain_plugin_file_py_exists:
            file.write(domain + ".py")
    
    if start_after:
        with open(os.path.join(html_dir, "latest"), "w") as file:
            file.write(start_after)
    
    os.remove(in_progress_filepath)
    return True


# Return the title of the newest item
def sync_rss(tracked_rss):
    feed = feedparser.parse(tracked_rss.link)
    if 'bozo_exception' in feed:
        print("{}: Failed to add rss, error: {}".format(str(datetime.today().isoformat()), str(feed.bozo_exception)))
        show_notification("RSS Sync failed", "Failed to parse rss for url {}, error: {}".format(tracked_rss.link, str(feed.bozo_exception)))
        return None

    items = []
    for item in feed["items"]:
        title = item["title"].strip()
        if tracked_rss.latest and title == tracked_rss.latest:
            break
        items.append(item)

    # Add torrents from the oldest to the newest, and stop when failing to add torrent.
    # If it fails, there will be an attempt to add them again after next sync cycle.
    latest = None
    for item in reversed(items):
        link = item["link"]
        if not add_torrent(link):
            return latest
        latest = item["title"].strip()
        show_notification("Download started", latest)
    return latest

def plugin_list(plugin_path, url, latest):
    if not latest:
        latest = ""
    process = subprocess.Popen([plugin_path, "list", url, latest], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        plugin_name = os.path.basename(plugin_path)
        print("{}: Plugin failed: Failed to launch plugin list for plugin {}, error: stdout: {}, stderr: {}".format(str(datetime.today().isoformat()), plugin_name, stdout.decode('utf-8'), stderr.decode('utf-8')))
        show_notification("Plugin failed", "Failed to launch plugin list for plugin {}, error: stdout: {}, stderr: {}".format(plugin_name, stdout.decode('utf-8'), stderr.decode('utf-8')), urgency="critical")
        return None

    try:
        return json.loads(stdout.decode('utf-8'))
    except json.decoder.JSONDecodeError as e:
        plugin_name = os.path.basename(plugin_path)
        show_notification("Plugin failed", "Failed to json decode response of plugin {}, error: {}".format(plugin_name, str(e)), urgency="critical")
        return None

def plugin_download(plugin_path, url, download_dir):
    subprocess.Popen([plugin_path, "download", url, download_dir], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return True

def resume_tracked_html(plugin_entry, download_dir, tracked_html, session_id):
    # TODO: Instead of redownloading, add resuming. This could be done by adding the files that have been downloaded to a file.
    # Redownload items we can detect have stopped. This can happen if the computer crashes or loses connection while downloading.
    title_dir = os.path.join(download_dir, tracked_html.title)
    try:
        for item in os.listdir(title_dir):
            item_dir = os.path.join(title_dir, item)
            if os.path.isfile(os.path.join(item_dir, "finished")):
                continue
            
            in_progress_path = os.path.join(item_dir, "in_progress")
            url = get_file_content_or_none(in_progress_path)
            # Item has finished downloading
            if not url:
                continue

            invalid_session = False
            try:
                with open(os.path.join(item_dir, "session_id"), "r") as file:
                    item_session_id = file.read()
                    if item_session_id != session_id:
                        invalid_session = True
            except FileNotFoundError as e:
                invalid_session = True
            
            if invalid_session:
                plugin_download(plugin_entry, url, item_dir)
                show_notification("Resuming", "Resuming download for item {} with plugin {}".format(item, tracked_html.plugin))
                with open(os.path.join(item_dir, "session_id"), "w") as file:
                    file.write(session_id)
    except FileNotFoundError as e:
        pass

# Return the title of the newest item
def sync_html(tracked_html, download_dir, session_id):
    plugin_entry = os.path.join(script_dir, "plugins", tracked_html.plugin)
    resume_tracked_html(plugin_entry, download_dir, tracked_html, session_id)

    # TODO: Instead of using item name to track which ones to download newer item than,
    # use a number which should be the number of items that have already been downloaded.
    # The reason being that some sites may rename items that we are tracking, for example
    # when tracking chapter names and the chapter doesn't have a name yet.

    # Program should print the names of each item (chapter for manga) after "latest", sorted by newest to oldest
    # along with the urls to them.
    # Only get the items before the one called @latest. The printed data should be in json format:
    # {
    #   "items": [
    #     {
    #       "name": "Example name",
    #       "url": "https://example.com"
    #     },
    #     {
    #       "name": "Another item",
    #       "url": "https://another.url.com"
    #     }
    #   ]
    # }
    # ./program list url latest
    # Note: @latest argument here is optional
    items = plugin_list(plugin_entry, tracked_html.link, tracked_html.latest)
    if not items:
        return None

    # Start downloading asynchronously using url.
    # A file called "in_progress" should be added to the download directory when the download is in progress.
    # The "in_progress" file should contain the url that was used to download the item.
    # A file called "finished" should be added to the download directory when the download has finished.
    # ./program download url download_dir
    latest = None
    for item in reversed(items["items"]):
        url = item["url"]
        name = item["name"].replace("/", "_")
        item_dir = os.path.join(download_dir, tracked_html.title, name)
        os.makedirs(item_dir, exist_ok=True)

        with open(os.path.join(item_dir, "session_id"), "w") as file:
            file.write(session_id)

        if not plugin_download(plugin_entry, url, item_dir):
            return latest

        latest = name
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

    tc = transmissionrpc.Client("localhost")
    
    running = True
    while running:
        tracked_rss = get_tracked_rss(rss_tracked_dir)
        for rss in tracked_rss:
            print("{}: rss: Syncing {}".format(str(datetime.today().isoformat()), rss.title))
            latest = sync_rss(rss)
            if latest:
                rss_update_latest(rss_tracked_dir, rss, latest)
            #else:
            #    print("No 'latest' item found for rss (maybe we already have the latest item?) %s" % rss.title)
            #time.sleep(0.5) # Sleep between fetching rss so we don't get banned for spamming

        tracked_html = get_tracked_html(html_tracked_dir)
        for html in tracked_html:
            print("{}: html({}): Syncing {}".format(str(datetime.today().isoformat()), html.plugin, html.title))
            latest = sync_html(html, download_dir, session_id)
            if latest:
                html_update_latest(html_tracked_dir, html, latest)
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
                update_downloaded_item_list(newly_finished_html_item)
            unfinished_html_items = [html_item for html_item in html_items if not html_item.finished]

            torrents = get_torrent_progress(tc)
            finished_torrents = get_finished_torrents(torrents)
            newly_finished_torrents = get_matching_torrents_by_name(finished_torrents, unfinished_torrents)
            for newly_finished_torrent in newly_finished_torrents:
                show_notification("Download finished", newly_finished_torrent)
                update_downloaded_item_list(newly_finished_torrent)
            unfinished_torrents = get_unfinished_torrents(torrents)

            time.sleep(check_torrent_status_rate_sec)
            count += 1

def main():
    parser = argparse.ArgumentParser(description="Automatic download of media (rss feed, tracking html)")
    action_group = parser.add_mutually_exclusive_group(required=True)
    action_group.add_argument("-a", "--add", action="store_true")
    action_group.add_argument("-s", "--sync", action="store_true")

    parser.add_argument("-t", "--type", choices=["rss", "html"], required=False)
    parser.add_argument("-u", "--url", required=False)
    parser.add_argument("--start-after", required=False)
    parser.add_argument("-d", "--download-dir", required=False)
    parser.add_argument("-n", "--name", required=False)
    args = parser.parse_args()

    rss_config_dir = os.path.join(config_dir, "rss")
    html_config_dir = os.path.join(config_dir, "html")

    if args.add:
        if not args.url:
            print("-u/--url argument is required when using 'add' command")
            exit(1)
        if not args.type:
            print("-t/--type argument is required when using 'add' command")
            exit(1)
        if args.type == "rss":
            os.makedirs(rss_config_dir, exist_ok=True)
            result = add_rss(args.url, rss_config_dir, args.start_after)
            if not result:
                exit(1)
        elif args.type == "html":
            if not args.name:
                print("-n/--name argument is required when using '--add --type html' command")
                exit(1)

            os.makedirs(html_config_dir, exist_ok=True)
            result = add_html(args.name, args.url, html_config_dir, args.start_after)
            if not result:
                exit(1)
    elif args.sync:
        if not args.download_dir:
            print("-d/--download-dir argument is required when using 'sync' command")
            exit(1)

        os.makedirs(rss_config_dir, exist_ok=True)
        os.makedirs(html_config_dir, exist_ok=True)

        sync_rate_sec = 15 * 60 # every 15 min
        sync(rss_config_dir, html_config_dir, args.download_dir, sync_rate_sec)
        pass

if __name__ == "__main__":
    main()
