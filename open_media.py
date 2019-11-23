#!/usr/bin/env python

import os
import sys
import subprocess

script_dir = os.path.dirname(os.path.realpath(sys.argv[0]))

def run_dmenu(input):
    process = subprocess.Popen(["rofi", "-dmenu", "-i", "-p", "Select media"], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    stdout, stderr = process.communicate(input.encode())
    if process.returncode == 0:
        return stdout
    else:
        print("Failed to launch rofi, error: {}".format(stderr))
    return None

def add_seen(seen_filepath, media_name, seen_list):
    if media_name in seen_list:
        return
    with open(seen_filepath, "a") as seen_file:
        seen_file.write(media_name + "\n")

def sort_images(filename):
    idx = filename.find(".")
    if idx != -1:
        return int(filename[0:idx])
    return 0

def get_downloaded_list():
    process = subprocess.Popen([os.path.join(script_dir, "automedia.py"), "downloaded"], stdout=subprocess.PIPE)
    stdout, stderr = process.communicate()
    if process.returncode == 0:
        return stdout.decode().splitlines()
    else:
        print("Failed to list downloaded items, error: {}".format(stderr))
    return []

def main():
    if len(sys.argv) < 2:
        print("usage: open_media.py <download_dir>")
        print("example: open_media.sh /home/user/Downloads/automedia")
        exit(1)

    download_dir = sys.argv[1]
    if not os.path.isdir(download_dir):
        print("No such directory: " % (download_dir))
        exit(2)

    downloaded_list = get_downloaded_list()
    downloaded_list = [item for item in downloaded_list if os.path.exists(os.path.join(download_dir, item))]
    
    seen_filepath = os.path.expanduser("~/.config/automedia/seen")
    seen_list = []
    try:
        with open(seen_filepath, "r") as seen_file:
            seen_list = seen_file.read().splitlines()
    except OSError as e:
        print("Failed to open {}, reason: {}".format(seen_filepath, str(e)))

    for seen in seen_list:
        for i, downloaded in enumerate(downloaded_list):
            if seen == downloaded:
                downloaded_list[i] = "✓ {}".format(downloaded)

    selected_media = run_dmenu("\n".join(downloaded_list[::-1]))
    if not selected_media:
        exit(0)
    selected_media = selected_media.decode().replace("✓ ", "").rstrip()
    
    media_path = os.path.join(download_dir, selected_media)
    if os.path.isdir(media_path):
        add_seen(seen_filepath, selected_media, seen_list)
        files = []
        for filename in os.listdir(media_path):
            if filename not in (".finished", ".session_id"):
                files.append(filename)

        files = sorted(files, key=sort_images)
        process = subprocess.Popen(["sxiv", "-i", "-f"], stdin=subprocess.PIPE)
        files_fullpath = []
        for filename in files:
            files_fullpath.append(os.path.join(media_path, filename))
        process.communicate("\n".join(files_fullpath).encode())
    elif os.path.isfile(media_path):
        add_seen(seen_filepath, selected_media, seen_list)
        subprocess.Popen(["mpv", "--", media_path])

main()
