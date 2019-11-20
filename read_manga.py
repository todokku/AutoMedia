#!/usr/bin/env python3

import sys
import os
import re
import subprocess

def usage():
    print("read_manga.py manga_directory [start_at_chapter] [--list-reverse]")
    print("examples:")
    print("  read_manga.py /home/adam/Manga/Naruto \"Chapter 10\"")
    print("  read_manga.py /home/adam/Manga/Naruto --list-reverse")
    exit(1)

if len(sys.argv) < 2:
    usage()

def chapter_sort_func(ch):
    match1 = re.search(r"Chapter ([0-9.]+)", ch)
    if match1 and len(match1.groups()) >= 1:
        return float(match1.groups()[0])
    match2 = re.search(r"^([0-9.]+)", ch)
    if match2 and len(match2.groups()) >= 1:
        return float(match2.groups()[0])
    raise Exception("Failed to sort. Unexpected chapter name format: {}".format(ch))

def image_sort_func(ch):
    return int(ch[0:ch.rfind(".")])

start_at_chapter = None
if len(sys.argv) >= 3:
    start_at_chapter = sys.argv[2]

manga_directory = sys.argv[1]
chapters = []
for chapter in os.listdir(manga_directory):
    chapters.append(chapter)

chapters_by_oldest = []
try:
    chapters_by_oldest = sorted(chapters, key=chapter_sort_func)
except Exception as e:
    print("Failed to sord chapters using custom sorting method, using default sorting method. Reason for failure: %s" % str(e), file=sys.stderr)
    chapters_by_oldest = sorted(chapters)

for argv in sys.argv:
    if argv == "--list-reverse":
        chapters_by_oldest.reverse()
        print("\n".join(chapters_by_oldest))
        exit(0)

start_index = 0
if start_at_chapter:
    found_chapter = False
    index = 0
    for chapter in chapters_by_oldest:
        if chapter == start_at_chapter:
            start_index = index
            found_chapter = True
            break
        index += 1
    
    if not found_chapter:
        print("Failed to find chapter %s in list of chapters: %s" % (start_at_chapter, str(chapters_by_oldest)), file=sys.stderr)

images_str = []
for chapter in chapters_by_oldest[start_index:]:
    images = []
    image_dir = os.path.join(manga_directory, chapter)
    for image in os.listdir(image_dir):
        # Ignore ".in_progress", ".finished" and ".session_id". We only want image files.
        if image.find(".") != -1:
            images.append(image)
    
    images = sorted(images, key=image_sort_func)
    for image in images:
        images_str.append(os.path.join(image_dir, image))
    index += 1

process = subprocess.Popen(["sxiv", "-i", "-f"], stdin=subprocess.PIPE)
process.communicate("\n".join(images_str).encode())
