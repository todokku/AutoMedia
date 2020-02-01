# AutoMedia
Automatically track new releases of media and download them. Currently works with rss for torrent sites (nyaa.si) and a few manga websites (see plugins directory).
A notification is shown on the screen when a download finishes (if notify-send is installed).
## Usage
Run automedia with `sync` option and keep it running to track media. You can then use `add` option to add new media to track.
Run automedia without any options to see all options.
## TODO
1. Periodically check and remove in_progress files and their directories. This can happen if the computer crashes while adding rss.
2. Automatically remove torrents that have finished seeding, to reduce memory usage and startup time of transmission.
# Requirements
## System
wget, transmission-cli, notify-send (optional)
## Python
feedparser, transmissionrpc, lxml
# Requirements when using read_manga.py
## System
rofi, sxiv
# Important
Do not move files inside the download directory. If you want to move them, move the whole download directory
when automedia is not running and then set the download directory to the new location when using sync command.
