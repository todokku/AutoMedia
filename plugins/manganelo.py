#!/usr/bin/env python3

import os
import time
import sys
import requests
import json
import subprocess

from lxml import etree

def usage():
    print("manganelo.py command")
    print("commands:")
    print("  download")
    print("  list")
    exit(1)

def usage_list():
    print("manganelo.py list <url> [latest]")
    print("examples:")
    print("  manganelo.py list \"https://mangakakalot.com/manga/assassins_pride\"")
    print("  manganelo.py list \"https://mangakakalot.com/manga/assassins_pride\" \"Chapter 13\"")
    exit(1)

def usage_download():
    print("manganelo.py download <url> <download_dir>")
    print("examples:")
    print("  manganelo.py download \"https://mangakakalot.com/chapter/vy918232/chapter_16\" /home/adam/Manga/MangaName")
    print("")
    print("Note: The manga directory has to exist.")
    exit(1)

if len(sys.argv) < 2:
    usage()

def download_file(url, save_path):
    process = subprocess.Popen(["wget", "-q", "-o", "/dev/null", "-O", save_path, url], stderr=subprocess.PIPE)
    _, stderr = process.communicate()
    if process.returncode != 0:
        print("Failed to download file: {}, error: {}".format(url, stderr.decode('utf-8')))
        return False
    return True

def list_chapters(url, latest):
    response = requests.get(url)
    if response.status_code != 200:
        print("Failed to list chapters, server responded with status code %d" % response.status_code)
        exit(2)

    tree = etree.HTML(response.text)
    chapters = []
    for element in tree.xpath('//div[@class="chapter-list"]//a'):
        element_text = element.text.strip()
        if latest and element_text == latest:
            break
        chapters.append({ "name": element_text, "url": element.attrib.get("href").strip() })
    print(json.dumps({ "items": chapters }))

def download_chapter(url, download_dir):
    response = requests.get(url)
    if response.status_code != 200:
        print("Failed to list chapters, server responded with status code %d" % response.status_code)
        exit(2)

    in_progress_filepath = os.path.join(download_dir, "in_progress")
    with open(in_progress_filepath, "w") as file:
        file.write(url)

    tree = etree.HTML(response.text)
    img_number = 1
    for image_source in tree.xpath('//div[@id="vungdoc"]/img/@src'):
        ext = image_source[image_source.rfind("."):]
        image_name = str(img_number) + ext
        image_path = os.path.join(download_dir, image_name)
        print("Downloading {} to {}".format(image_source, image_path))
        if not download_file(image_source, image_path):
            exit(1)
        img_number += 1

    with open(os.path.join(download_dir, "finished"), "w") as file:
        file.write("1")

    os.remove(in_progress_filepath)

command = sys.argv[1]
if command == "list":
    if len(sys.argv) < 3:
        usage_list()
    
    url = sys.argv[2]
    latest = ""
    if len(sys.argv) >= 4:
        latest = sys.argv[3]
    list_chapters(url, latest)
elif command == "download":
    if len(sys.argv) < 4:
        usage_download()
    url = sys.argv[2]
    download_dir = sys.argv[3]
    download_chapter(url, download_dir)
else:
    usage()
