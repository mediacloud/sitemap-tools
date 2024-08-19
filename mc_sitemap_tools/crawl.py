"""
tools to perform a full crawl of a site
"""

import logging
import time
from enum import Enum
from typing import Callable, NamedTuple, cast

# PyPI
from requests.exceptions import RequestException

# local package
from . import discover
from . import parser

logger = logging.getLogger(__name__)


def _canurl(url: str) -> str:
    """
    replace with URL canonicalization?
    """
    return url


FETCH_EXCEPTIONS = (RequestException,)
Saver = Callable[[parser.Urlset], None]


class Crawler:
    """
    enscapsulate state for crawling a site.
    meant to be pickleable (no open files/sessions)

    visits pages breadth first.
    """

    def __init__(self, home_page: str, saver: Saver):
        if not home_page.endswith("/"):
            home_page += "/"
        self.home_page = home_page
        self.saver = saver
        self.to_visit: list[str] = []
        self.seen: set[str] = set()
        self.state_processor = None
        self.get_robots = True

    def _add_url(self, url: str, home_page: str | None = None) -> None:
        if home_page:
            url = home_page + url
        canurl = _canurl(url)
        if canurl not in self.seen:
            logger.info("adding %s", url)
            self.seen.add(canurl)
            self.to_visit.append(url)

    def _add_list(self, url_list: list[str], add_home_page: bool) -> None:
        for url in url_list:
            if add_home_page:
                url = self.home_page + url
            self._add_url(url)

    def visit_one(self) -> bool:
        """
        visit one page, returns True while more work to be done
        """
        if self.get_robots:
            logger.info("getting robots.txt")
            try:
                self._add_list(discover.robots_sitemaps(self.home_page), False)
            except FETCH_EXCEPTIONS:
                pass
            self._add_list(discover._UNPUBLISHED_SITEMAP_INDEX_PATHS, True)
            self._add_list(discover._UNPUBLISHED_GNEWS_SITEMAP_PATHS, True)

            self.get_robots = False
            # robots.txt counts as a visit
            # so don't visit any pages
        else:
            url = self.to_visit.pop(0)
            logger.info("getting %s", url)
            # fetch and parse page:
            try:
                sitemap = discover.sitemap_get(url)
            except FETCH_EXCEPTIONS:
                sitemap = None

            if sitemap:         # fetched and parsed ok
                smt = sitemap["type"]
                if smt == "index":
                    logger.info("%s: index", url)
                    index = cast(parser.Index, sitemap)
                    for suburl in index["sub_sitemap_urls"]:
                        self._add_url(suburl)
                elif smt == "urlset":
                    logger.info("%s: urlset", url)
                    urlset = cast(parser.Urlset, sitemap)
                    self.saver(urlset)
                else:
                    logger.warning("%s: unknown sitemap type %s", url, smt)
            # end not _get_robots
        return len(self.to_visit) > 0


def full_crawl_gnews_urls(home_page: str, sleep_time: float = 1.0) -> list[str]:
    results = []

    def saver(urlset: parser.Urlset) -> None:
        if urlset["google_news_tags"]:
            url = urlset["url"]
            logger.info("*** SAVING %s ***", url)
            results.append(url)

    crawler = Crawler(home_page, saver)
    while crawler.visit_one():
        time.sleep(1)

    return results


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    for url in full_crawl_gnews_urls(sys.argv[1], 0.1):
        print(url)
