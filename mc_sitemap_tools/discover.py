"""
tools for discovering *news* sitemaps from a home page URL

when invoked from command line, takes a home page URL
"""

import logging
from typing import cast

# PyPI
import requests
from mcmetadata.webpages import MEDIA_CLOUD_USER_AGENT  # TEMP

# local package:
from . import parser
# from requests_arcana import legacy_ssl_session

logger = logging.getLogger(__name__)

# from usp/tree.py _UNPUBLISHED_SITEMAP_PATHS
_UNPUBLISHED_SITEMAP_INDEX_PATHS = [
    'sitemap.xml',
    'sitemap.xml.gz',
    'sitemap_index.xml',
    'sitemap-index.xml',
    'sitemap_index.xml.gz',
    'sitemap-index.xml.gz',
    '.sitemap.xml',
    'sitemap',
    'admin/config/search/xmlsitemap',
    'sitemap/sitemap-index.xml',

    # not in usp, seen at (AJC, inquirer, elnuevdia, reuters).com (among others)
    'arc/outboundfeeds/sitemap-index/?outputType=xml',
    'arc/outboundfeeds/news-sitemap-index/?outputType=xml',
]
"""Paths which are not exposed in robots.txt but might still contain a sitemap index page."""

_UNPUBLISHED_GNEWS_SITEMAP_PATHS = [
    "arc/outboundfeeds/news-sitemap/?outputType=xml", # AJC, inquirer, reuters
    'arc/outboundfeeds/sitemap/latest/?outputType=xml', # dallasnews (current, no gtags)

    'feeds/sitemap_news.xml',  # bloomberg
    'google-news-sitemap.xml',  # ew.com, people.com
    'googlenewssitemap.xml',  # axs.com, accesshollywood.com
    'news-sitemap.xml',  # gannett-cdn.com (many cities), parade
    'news-sitemap-content.xml',  # scrippsnews.com
    'news/sitemap_news.xml',  # buzzfeed, NPR
    'sitemap_news.xml',  # bloomberg, bizjournals, cnbc
    'sitemap/news.xml',  # cnn
    'sitemaps/news.xml',  # cnet
    'sitemaps/new/news.xml.gz',  # NYT
    'sitemaps/sitemap-google-news.xml',  # huffpost.com
    'tncms/sitemap/news.xml',  # berkshireeagle, omaha, postandcourier, rutlandherald
    # 'sitemaps/news',     # thetimes
    # 'feed/google-news-sitemap-feed/sitemap-google-news', # newyorker
]
"""Paths which are not exposed in robots.txt but might still contain a google news sitemap page."""


class PageType:
    """
    bitmasks for different page types
    """
    INDEX = 0x1
    URLSET = 0x2                # urlset w/o google <news:news>
    GNEWS = 0x4                 # urlset w/ google <news:news>
    ALL = 0xFFF


def legacy_ssl_session() -> requests.Session:
    """
    place holder for function to return requests Session
    object that talks to older TLS sites
    """
    sess = requests.Session()
    sess.headers["User-Agent"] = MEDIA_CLOUD_USER_AGENT
    return sess


def page_exists(url: str) -> bool:
    sess = legacy_ssl_session()
    try:
        resp = sess.head(url, allow_redirects=True)
        ret = bool(resp)
    except Exception:
        resp = None
        ret = False
    # print(f"{url} {resp!r} {ret}")    # XXX logger.debug
    return ret


def page_get(url: str) -> requests.Response:
    sess = legacy_ssl_session()
    resp = sess.get(url, allow_redirects=True, timeout=(30, 30))
    return resp


def sitemap_get(url: str) -> parser.BaseSitemap | None:
    try:
        resp = page_get(url)
        text = resp.text        # should always be UTF-8!
        logger.info("%s: got %d chars", url, len(text))
        p = parser.XMLSitemapParser(url, text)
        return p.sitemap()
    except Exception as e:
        logger.info("%s %r", url, e)
        return None


def check_sitemap_type(url: str, sm: parser.BaseSitemap, accept: int) -> bool:
    smtype = sm.get("type")
    logger.info("%s (%s) %#x", url, smtype, accept)

    if smtype == "index":
        return (accept & PageType.INDEX) != 0

    if smtype != "urlset":
        return False
    us = cast(parser.Urlset, sm)
    if us.get("google_news_tags"):
        return (accept & PageType.GNEWS) != 0
    return (accept & PageType.URLSET) != 0


def sitemap_get_and_check_type(url: str, accept: int = PageType.ALL) -> parser.BaseSitemap | None:
    sm = sitemap_get(url)
    if not sm:
        return None
    if check_sitemap_type(url, sm, accept):
        return sm
    return None


def robots_sitemaps(url: str, homepage: bool = True) -> list[str]:
    """
    fetch robots.txt and return URLs of sitemap pages
    (may include RSS URLs!)
    """
    robots_txt_url = url
    if homepage:
        if not robots_txt_url.endswith('/'):
            robots_txt_url += '/'
        robots_txt_url += 'robots.txt'

    resp = page_get(robots_txt_url)
    if not resp or not resp.text:
        return []

    # https://developers.google.com/search/docs/crawling-indexing/robots/robots_txt#file-format
    # says:
    #
    # The robots.txt file must be a UTF-8 encoded plain text file and
    # the lines must be separated by CR, CR/LF, or LF.
    #
    # Google ignores invalid lines in robots.txt files, including the
    # Unicode Byte Order Mark (BOM) at the beginning of the robots.txt
    # file, and use only valid lines. For example, if the content
    # downloaded is HTML instead of robots.txt rules, Google will try
    # to parse the content and extract rules, and ignore everything
    # else.
    #
    # Similarly, if the character encoding of the robots.txt file
    # isn't UTF-8, Google may ignore characters that are not part of
    # the UTF-8 range, potentially rendering robots.txt rules invalid.
    #
    # Google currently enforces a robots.txt file size limit of 500
    # kibibytes (KiB). Content which is after the maximum file size is
    # ignored. You can reduce the size of the robots.txt file by
    # consolidating rules that would result in an oversized robots.txt
    # file. For example, place excluded material in a separate
    # directory.
    text = resp.text

    urls = []
    for line in text.splitlines():  # handle \n \r \r\n
        if ':' not in line:
            continue

        tok, rest = line.split(':', 1)
        if tok.lower() == "sitemap":
            url = rest.strip()
            urls.append(url)
    return urls


def robots_gnews_sitemaps(url: str, homepage: bool = True) -> list[str]:
    """
    if homepage is True, use as base for robots.txt,
    else use as full URL without modification
    """
    urls = []
    for url in robots_sitemaps(url, homepage):
        sm = sitemap_get_and_check_type(url, PageType.GNEWS)
        if sm:
            urls.append(url)
    return urls


def unpublished_gnews_sitemaps(homepage_url: str) -> list[str]:
    """
    check locations where google news urlsets have been seen
    """
    if not homepage_url.endswith("/"):
        homepage_url += "/"

    urls = []
    for p in _UNPUBLISHED_GNEWS_SITEMAP_PATHS:
        url = homepage_url + p
        sm = sitemap_get_and_check_type(url, PageType.GNEWS)
        if sm:
            urls.append(url)
    return urls


def _unpub_path(url: str) -> bool:
    """
    helper: return True if url has a "well known" path

    npr.org robots.txt has feeds with WKPs in domain googlecrawl.npr.org
    """
    for p in _UNPUBLISHED_GNEWS_SITEMAP_PATHS:
        if url.endswith(p):
            return True
    return False


def find_gnews_fast(homepage_url: str, max_robots_pages: int = 2) -> list[str]:
    """
    quickly scan a source for urlsets with google news tags
    (without following sitemap index page links)
    """

    # originally returned just robots_urls if reasonable length, but
    # reuters.com has a feed in robots.txt, but the BEST sitemap is
    # found using well-known paths.
    robots_urls = robots_gnews_sitemaps(homepage_url)
    if len(robots_urls) > max_robots_pages:
        # here if too many urls in robots.txt
        # see if a subset have "well known" paths
        robots_urls = [url for url in robots_urls if _unpub_path(url)]
        # XXX check length now?? do what???
    unpub_urls = unpublished_gnews_sitemaps(homepage_url)

    # return list of union of both robots_urls & unpub_urls (avoid dups)
    return list(set(robots_urls).union(set(unpub_urls)))


if __name__ == '__main__':
    import sys
    logging.basicConfig(level=logging.INFO)

    # XXX complain about startswith "www."?
    if len(sys.argv) != 2 or '.' not in sys.argv[1]:
        sys.stderr.write(f"Usage: {sys.argv[0]} DOMAIN\n")
        sys.exit(1)

    domain = sys.argv[1]
    homepage = "https://www." + domain

    # handle options for which method(s) to try!!! types to accept!!!
    if False:
        print("-- robots.txt")
        for url in robots_gnews_sitemaps(homepage):
            print(url)

        print("-- unpublished")
        for url in unpublished_gnews_sitemaps(homepage):
            print(url)

    print("-- find_gnews_fast")
    for url in find_gnews_fast(homepage):
        print(url)
