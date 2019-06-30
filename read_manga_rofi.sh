#!/bin/sh

set -e

script_path=$(readlink -f "$0")
script_dir=$(dirname "$script_path")
cd "$script_dir"

download_dir="$1"
manga_list=$(ls -t "$download_dir")
selected_manga=$(echo "$manga_list" | rofi -dmenu -i -p "Select manga")
chapters=$(./read_manga.py "$download_dir/$selected_manga" --list-reverse)
selected_starting_chapter=$(echo "$chapters" | rofi -dmenu -i -p "Select starting chapter")
./read_manga.py "$download_dir/$selected_manga" "$selected_starting_chapter"
