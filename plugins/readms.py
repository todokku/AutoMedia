#!/usr/bin/env python3

import os
import time
import sys
import requests
import json
import subprocess

from lxml import etree

def usage():
    print("readms.py command")
    print("commands:")
    print("  download")
    print("  list")
    exit(1)

def usage_list():
    print("readms.py list <url> [latest]")
    print("examples:")
    print("  readms.py list \"https://readms.net/manga/a_trail_of_blood\"")
    print("  readms.py list \"https://readms.net/manga/a_trail_of_blood\" \"48 - Blood oath\"")
    exit(1)

def usage_download():
    print("readms.py download <url> <download_dir>")
    print("examples:")
    print("  readms.py download \"https://readms.net/manga/a_trail_of_blood\" /home/adam/Manga/MangaName")
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
    for element in tree.xpath('//table//tr//a'):
        element_text = element.text.strip()
        if latest and element_text == latest:
            break
        chapters.append({ "name": element_text, "url": "https://readms.net" + element.attrib.get("href").strip() })
    print(json.dumps(chapters))

def download_chapter(url, download_dir):
    in_progress_filepath = os.path.join(download_dir, ".in_progress")
    with open(in_progress_filepath, "w") as file:
        file.write(url)
        
    img_number = 1
    while True:
        response = requests.get(url)
        if response.status_code != 200:
            print("Failed to list chapters, server responded with status code %d" % response.status_code)
            exit(2)

        tree = etree.HTML(response.text)
        
        image_sources = tree.xpath('//img[@id="manga-page"]/@src')
        if len(image_sources) != 1:
            break

        image_source = "https:" + image_sources[0]
        ext = image_source[image_source.rfind("."):]
        image_name = str(img_number) + ext
        image_path = os.path.join(download_dir, image_name)
        print("Downloading {} to {}".format(image_source, image_path))
        if not download_file(image_source, image_path):
            exit(1)

        next_pages = tree.xpath('//div[@class="page"]//a/@href')
        if len(next_pages) != 1:
            break

        next_page = next_pages[0]
        last_slash = next_page.rfind('/')
        try:
            if last_slash != -1 and int(next_page[last_slash+1:]) <= img_number:
                break
        except ValueError:
            pass

        url = "https://readms.net" + next_page
        img_number += 1

    with open(os.path.join(download_dir, ".finished"), "w") as file:
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
