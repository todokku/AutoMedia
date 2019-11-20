#!/usr/bin/env python

def url_extract_domain(url):
    index = 0
    if url.startswith("http://"):
        index += 7
    elif url.startswith("https://"):
        index += 8

    if url.startswith("www.", index):
        index += 4

    end = url.find(".", index)
    if end == -1:
        return url[index:]
    else:
        return url[index:end]
