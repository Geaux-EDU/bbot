#!/usr/bin/python
# -*- coding: utf-8 -*-

import requests
from bs4 import BeautifulSoup
import hashlib
from urllib.parse import urlparse
import threading
import time
import os
import string
import random

LOCK = threading.Lock()
LINK_SEARCH_DEPTH = 1

def remove_values_from_list(the_list, val):
    return [value for value in the_list if value != val]

clicked_links = []
data = {}

def value_in_list(the_list, val):
    s = set(the_list)
    if s in the_list:
        return True
    return False

def get_backlinks(response):
    # Parse the response for all the <a> tags
    soup = BeautifulSoup(response.text, 'lxml')
    elems = soup.find_all("a")

    # Then, get the href for the a tags
    links = []
    for elem in elems:
        links.append(elem.get("href"))

    # Now, go through every single link and format it
    # properly
    count = 0
    for link in links:
        if link == None:
            remove_values_from_list(links, link)
            continue
        if link[0] == "#":
            remove_values_from_list(links, link)
            continue
        if link[0] + link[1] == "./":
            domain = urlparse(response.url).netloc
            links[count] = "https://" + domain + link[1:]
        if link[0] == "/":
            domain = urlparse(response.url).netloc
            links[count] = "https://" + domain + link
        count += 1

    return list(set(links))

# This scrapes up every link, including images
# video, audio, stylesheets, javascript, etc.
def get_all_backlinks(response):
    # Parse the response for all the <a> tags
    soup = BeautifulSoup(response.text, 'lxml')
    link_elems = soup.find_all("a")
    img_elems = soup.find_all("img")
    style_elems = soup.find_all("link")
    script_elems = soup.find_all("script")
    video_and_audio_elems = soup.find_all("source")

    # Then, aggregate all these elems and put them
    # into a single list
    links = []
    for link_elem in link_elems:
        links.append(link_elem.get("href"))
    for img_elem in img_elems:
        links.append(img_elem.get("src"))
    for style_elem in style_elems:
        links.append(style_elem.get("href"))
    for script_elem in script_elems:
        links.append(script_elem.get("src"))
    for video_and_audio_elem in video_and_audio_elems:
        links.append(video_and_audio_elem.get("src"))

    # Now, go through every single link and format it
    # properly
    count = 0
    for link in links:
        if link == None:
            remove_values_from_list(links, link)
            continue
        if link == "":
            del links[count]
            continue
        if link[0] == "#":
            remove_values_from_list(links, link)
            continue
        if link[0] + link[1] == "./":
            domain = urlparse(response.url).netloc
            links[count] = "https://" + domain + link[1:]
        if link[0] == "/":
            domain = urlparse(response.url).netloc
            links[count] = "https://" + domain + link
        count += 1

    return list(set(links))


# Downloads the data and puts it in the data list.
# Then, returns all the backlinks in the text
def download_data_from_link_list(links, more_than_text_or_no):
    backlinks = []
    for link in links:
        if value_in_list(links, link) == False:
            try:
                r = requests.get(link)
                backlinks_tmp = []
                if more_than_text_or_no == "n":
                    backlinks_tmp = get_backlinks(r)
                else:
                    backlinks_tmp = get_all_backlinks(r)
                print("[ + ]" + link)
                with LOCK:
                    domain = urlparse(r.url).netloc
                    path = urlparse(r.url).path
                    data[domain + path] = r.content
                    for backlink in backlinks_tmp:
                        backlinks.append(backlink)
                    clicked_links.append(link)
            except Exception as e:
                print("[Error] Unable to reach {}".format(link))
    return backlinks

def sanitize_folder_path(fpath):
    domain = str(urlparse(fpath).netloc).replace(".", "-")
    path = str(urlparse(fpath).path)
    fpath_correct = domain + path

    return fpath_correct

def make_dir_if_not_exists(d):
    print("Data-Dump/" + d)
    if not os.path.exists("Data-Dump/" + d):
        os.makedirs("Data-Dump/" + d, exist_ok=True)

def file_writer_daemon():
    # Check to see if the data-dump folder exists. if not,
    # create it
    if not os.path.exists("Data-Dump"):
        os.makedirs("Data-Dump", exist_ok=True)

    # Establish a safe directory. No path
    # should go behind this path
    safe_dir = os.getcwd()
    while True:
        try:
            keys_to_delete = []
            for k in data:
                # Get rid of the slash in front of the folder path
                k_safe = sanitize_folder_path(k)

                # Check for directory traversal attacks
                if os.path.commonprefix((os.path.realpath(k_safe),safe_dir)) != safe_dir: 
                    #Bad user!
                    print("[Yay] Thwarted directory traversal attack!")
                    keys_to_delete.append(k)
                    continue
                
                if k == "/":
                    fpath = "Data-Dump/index.html"
                    f = open(fpath, "wb")
                    f.write(data[k])
                    f.close()
                    keys_to_delete.append(k)
                else:
                    make_dir_if_not_exists(os.path.split(k_safe)[0])
                    fpath = "Data-Dump/" + os.path.split(k_safe)[0] + "/" + os.path.split(k_safe)[1]
                    if "." in os.path.split(k_safe)[1]:
                        print(fpath)
                        f = open(fpath, "wb")
                        f.write(data[k])
                        f.close()
                        keys_to_delete.append(k)
                    else:
                        fpath = fpath + ".file"
                        print(fpath)
                        f = open(fpath, "wb")
                        f.write(data[k])
                        f.close()
                        keys_to_delete.append(k)
            with LOCK:
                for key in keys_to_delete:
                    del data[key]
        except Exception as e:
            print("[Error] {}".format(e))
            with LOCK:
                for key in keys_to_delete:
                    del data[key]
        time.sleep(3)

# Downloads the data and puts it in the data list.
# Then, returns all the backlinks in the text
# This uses a proxy
def proxy_download_data_from_link_list(links, the_proxies, more_than_text_or_no):
    backlinks = []
    for link in links:
        if value_in_list(links, link) == False:
            try:
                r = requests.get(link, proxies=the_proxies)
                backlinks_tmp = []
                if more_than_text_or_no == "n":
                    backlinks_tmp = get_backlinks(r)
                else:
                    backlinks_tmp = get_all_backlinks(r)
                print("[ + ]" + link)
                with LOCK:
                    path = urlparse(r.url).path
                    domain = urlparse(r.url).netloc
                    data[domain + path] = r.content
                    for backlink in backlinks_tmp:
                        backlinks.append(backlink)
                    clicked_links.append(link)
            except Exception as e:
                print("[Error] Unable to reach {}".format(link))
    return backlinks

if __name__ == "__main__":
    website = input("What is the target website: ")
    search_depth = int(input("Type in the recursion depth for which you want to traverse links: "))
    proxy_or_no = input("Would you like to use a proxy (y/n): ")
    more_than_text_or_no = input("Would you like to download all data from the site other than just text (y/n): ")
    if proxy_or_no == "n":
        LINK_SEARCH_DEPTH = search_depth
        threading.Thread(target=file_writer_daemon, args=[]).start()
        resp = requests.get(website)
        backlinks = []
        if more_than_text_or_no == "n":
            backlinks = get_backlinks(resp)
        else:
            backlinks = get_all_backlinks(resp)
        backlinks_new = download_data_from_link_list(backlinks, more_than_text_or_no)
        for x in range(LINK_SEARCH_DEPTH):
            backlinks_new = download_data_from_link_list(backlinks_new, more_than_text_or_no)
        print("[ * ] Completed download... You may exit with Ctrl+C")
    else:
        http_proxy = input("Type in the address of your http proxy (ie: socks5h://127.0.0.1:9150): ")
        https_proxy = input("Type in the address of your https proxy (ie: socks5h://127.0.0.1:9150): ")
        the_proxies = {
            'http': http_proxy,
            'https': https_proxy,
        }
        LINK_SEARCH_DEPTH = search_depth
        threading.Thread(target=file_writer_daemon, args=[]).start()
        r = requests.get("https://ipecho.net/plain", proxies=the_proxies)
        print("My IP: " + r.text)
        print(r.headers)
        resp = requests.get(website, proxies=the_proxies)
        backlinks = []
        if more_than_text_or_no == "n":
            backlinks = get_backlinks(resp)
        else:
            backlinks = get_all_backlinks(resp)
        backlinks_new = proxy_download_data_from_link_list(backlinks, the_proxies, more_than_text_or_no)
        for x in range(LINK_SEARCH_DEPTH):
            backlinks_new = proxy_download_data_from_link_list(backlinks_new, the_proxies, more_than_text_or_no)
