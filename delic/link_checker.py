'''This module handles the actual link checking'''

import logging
import queue
import threading
from html.parser import HTMLParser
from urllib.parse import urljoin

import requests
from pydantic import BaseModel

LINK_TAGS = {
    'a': ['href'],
    'img': ['src', 'srcset'],
    'link': ['href'],
    'script': ['src'],
    'source': ['srcset'],
}


class Link(BaseModel):
    '''Represents a single link with its attributes'''
    url: str
    parent_url: str


class DelicHTMLParser(HTMLParser):
    def __init__(self, link_queue, checked_urls, base_url, parent_url):
        super().__init__()
        self.link_queue = link_queue
        self.checked_urls = checked_urls
        self.base_url = base_url
        self.parent_url = parent_url

    def handle_starttag(self, tag, attrs):
        if tag in LINK_TAGS:
            attr_values = (attr[1]
                           for attr
                           in attrs
                           if attr[0] in LINK_TAGS[tag])
            for attr_value in attr_values:
                # Extract url
                target_url = urljoin(self.base_url, attr_value)
                cleaned_url = target_url.split('#')[0]

                # Add url to queue
                if cleaned_url not in self.checked_urls:
                    new_link = Link(
                        url=cleaned_url,
                        parent_url=self.parent_url,
                    )
                    self.link_queue.put(new_link)


def check_site(base_url, workers_count):
    '''Check all links of a single site'''
    # Init
    checked_urls = []
    broken_urls = []
    link_queue = queue.Queue()

    # Log start
    msg = "Start link checking with %s workers for %s"
    logging.info(msg, workers_count, base_url)

    # Define worker
    def check_link_worker():
        while True:
            link = link_queue.get()
            if link.url not in checked_urls:
                checked_urls.append(link.url)
                check_link(link_queue,
                           checked_urls,
                           broken_urls,
                           base_url,
                           link)
            link_queue.task_done()

    # Start worker thread
    for _ in range(workers_count):
        threading.Thread(target=check_link_worker, daemon=True).start()

    # Queue base URL
    base_link = Link(
        url=base_url,
        parent_url='',
    )
    link_queue.put(base_link)

    # Wait until the queue fully processed
    link_queue.join()

    # Return results
    return {
        'summary': {
            'urls_checked': len(checked_urls),
            'urls_broken': len(broken_urls),
        },
        'details': {
            'broken': broken_urls
        }
    }


def check_link(link_queue, checked_urls, broken_links, base_url, link: Link):
    '''Check a single link'''
    # Create parser
    parser = DelicHTMLParser(link_queue, checked_urls,
                             base_url, link.url)

    # Fetch header
    logging.info('Checking URL: %s', link.url)
    req = requests.head(link.url)
    if req.status_code >= 400:
        report = {
            'page': link.parent_url,
            'broken_url': link.url,
            'status': req.status_code,
        }
        broken_links.append(report)

    # Link is HTML page and is internal
    # Fetch and parse page
    if req.headers['content-type'].startswith('text/html') and link.url.startswith(base_url):
        req_html = requests.get(link.url)
        parser.feed(req_html.text)
