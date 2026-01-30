"""
tools for performing crawls of sitemap files

Created in 2024, performing full site crawls. Mashed in Jan 2026 to do
more limited crawling, adding depth and preference/weight to the work
queue, and adding max_results to allow quitting early to see if we can
do better than discover.NewsDiscoverer.find_gnews_fast in reasonable time.

Author's note:

This is a work in progress; I've flipped back and forth between the
ordering of depth and pref in the PageTuple (and hence the work queue
ordering).

The page "preference" value is serving double duty; for lower values
it controls which pages are visited first, values at/above DISCARD
remove the URL from consideration (prune the tree).
"""

import heapq
import logging
import re
import time
from enum import Enum
from typing import NamedTuple, cast
from urllib.parse import urlsplit

# PyPI
from mcmetadata.feeds import normalize_url
from requests.exceptions import RequestException

# local package
from . import discover, parser

logger = logging.getLogger(__name__)


class PageTuple(NamedTuple):  # for heap
    pref: float  # for sort (lowest first)
    depth: int  # for sort
    url: str
    origin: str  # discovery path


class VisitResult(Enum):
    DONE = "done"
    MORE = "more"
    FIN = "fin"


DISCARD = 10


class BaseCrawler:
    """
    enscapsulate state for crawling a site.
    meant to be pickleable (no open files/sessions)

    visits pages breadth first.
    """

    FETCH_EXCEPTIONS = (RequestException,)
    UNPUBLISHED_INDEX_PREF = 1  # after robots.txt
    TRY_UNPUBLISHED_INDEX_PATHS = False
    DISCARD_PREF = DISCARD
    UNPUB_DEPTH = 1  # 0 to prefer to files in robots.txt

    def __init__(
        self, home_page: str, user_agent: str, max_depth: int, max_results: int
    ):
        if not home_page.endswith("/"):
            home_page += "/"
        self.home_page = home_page
        self.user_agent = user_agent
        self.max_depth = max_depth
        self.max_results = max_results

        self.results: list[parser.Urlset] = []
        self.news_discoverer = discover.NewsDiscoverer(user_agent)
        self.to_visit: list[PageTuple] = []  # managed by heapq
        self.seen: set[str] = set()
        self.get_robots = True  # starting state
        self.robots_urls: list[str] = []
        self.pages_visited = 0

    def page_pref(self, url: str) -> float:
        return 0.0

    def _add_url(
        self, depth: int, url: str, origin: str, pref: float | None = None
    ) -> None:
        """
        `url` MUST be complete URL
        checks if already seen before adding to `to_visit` heapq
        """
        nurl = normalize_url(url)
        if nurl not in self.seen:
            self.seen.add(nurl)
            if pref is None:
                pref = self.page_pref(url)
                if pref >= self.DISCARD_PREF:
                    logger.info("skipping %s %d %g %s", url, depth, pref, origin)
                else:
                    logger.info("adding %s %g %d %s", url, pref, depth, origin)
                    page = PageTuple(url=url, depth=depth, pref=pref, origin=origin)
                    heapq.heappush(self.to_visit, page)

    def _add_list(
        self,
        depth: int,
        url_list: list[str],
        add_home_page: bool,
        origin: str,
        pref: float | None = None,
    ) -> None:
        """
        add list of urls to visit
        if `add_home_page` is True, prepend `home_page` to each url
        """
        for url in url_list:
            if add_home_page:
                url = self.home_page + url
            self._add_url(depth, url, pref=pref, origin=origin)

    def add_unpublished_paths(self) -> None:
        if self.TRY_UNPUBLISHED_INDEX_PATHS:
            logger.info("====> add UNPUBLISHED_SITEMAP_INDEX_PATHS")
            self._add_list(
                depth=self.UNPUB_DEPTH,
                url_list=discover._UNPUBLISHED_SITEMAP_INDEX_PATHS,
                add_home_page=True,
                pref=self.UNPUBLISHED_INDEX_PREF + 0.1,  # worse than organic
                origin="unpub-index-paths",
            )

    def visit_one(self) -> VisitResult:
        """
        visit one page, returns True while more work to be done
        to allow running as a background activity
        """
        self.pages_visited += 1
        if self.get_robots:  # starting?
            # initial state: seed visit list with pages in robots.txt
            # and "well known" paths
            logger.info("===== getting robots.txt")
            try:
                self.robots_urls = self.news_discoverer.robots_sitemaps(self.home_page)
                # XXX get/honor Crawl-Delay??
                # sitemap lines in robots.txt _should_ be complete urls!!
                self._add_list(
                    depth=0,
                    url_list=self.robots_urls,
                    add_home_page=False,
                    origin="robots.txt",
                )
            except self.FETCH_EXCEPTIONS:
                pass

            # maybe only add these AFTER robots.txt paths exhausted?
            self.add_unpublished_paths()

            self.get_robots = False  # initialized
            # robots.txt counts as a visit
            # so don't visit any pages
        else:
            page = heapq.heappop(self.to_visit)
            url = page.url
            logger.info("getting %s %g %d %s", url, page.pref, page.depth, page.origin)
            # fetch and parse page:
            try:
                sitemap = self.news_discoverer.sitemap_get(url)
            except self.FETCH_EXCEPTIONS:
                sitemap = None

            if sitemap:  # fetched and parsed ok
                smt = sitemap["type"]
                if smt == "index":
                    logger.info("%s: index", url)
                    index = cast(parser.Index, sitemap)
                    if page.depth + 1 <= self.max_depth:
                        for suburl in index["sub_sitemap_urls"]:
                            self._add_url(
                                page.depth + 1, suburl, origin=f"{page.origin} -> {url}"
                            )
                    else:
                        logger.info("%s too deep", url)
                elif smt == "urlset":
                    logger.info("%s: urlset", url)
                    urlset = cast(parser.Urlset, sitemap)
                    if self.save(urlset, page.pref):
                        return VisitResult.DONE
                else:
                    logger.warning("%s: unknown sitemap type %s", url, smt)
            # end not _get_robots

        if len(self.to_visit) > 0:
            return VisitResult.MORE
        return VisitResult.FIN

    def save(self, urls: parser.Urlset, pref: float) -> bool:
        """
        return True to cause visit_one to return DONE
        """
        logger.info("saving %s %g", urls["url"], pref)
        self.results.append(urls)
        return len(self.results) >= self.max_results


class GNewsCrawlerFull(BaseCrawler):
    """
    crawl full site, returning only google news sitemaps,
    without pruning, for time/quality comparison to pruned/heuristic version.
    """

    UNPUBLISHED_GNEWS_SITEMAP_PREF = 0.0

    def add_unpublished_paths(self) -> None:
        logger.info("====> add UNPUBLISHED_GNEWS_SITEMAP_PATHS")
        self._add_list(
            depth=self.UNPUB_DEPTH,
            url_list=discover._UNPUBLISHED_GNEWS_SITEMAP_PATHS,
            add_home_page=True,
            pref=self.UNPUBLISHED_GNEWS_SITEMAP_PREF + 0.1,  # worse than organic
            origin="unpub-gnews-paths",
        )
        super().add_unpublished_paths()

    def save(self, urls: parser.Urlset, pref: float) -> bool:
        """
        return True to cause visit_one to return DONE
        """
        if urls["google_news_tags"]:
            return super().save(urls, pref)
        return False


class GNewsCrawler(GNewsCrawlerFull):
    """
    google news sitemap specific site crawler,
    with heuristics/pruning
    """

    # DATE_RE and YEAR_RE are class members to allow override;
    # applied to case-flattened {path}?{query}
    # matching either causes page_pref to return DISCARD.

    # https://www.nytimes.com/sitemaps/new/cooking-1982-09.xml.gz
    # https://nypost.com/sitemap-1865.xml
    # https://nypost.com/sitemap-1999.xml?mm=12&dd=31
    YEAR_RE = re.compile(r"(^|\D)(1[89]|20)\d\d($|\D|[01]\d)|year=")

    # npr.org has dd-Mon-yy, bershireeagle has date=YYYY-MM-DD
    DATE_RE = re.compile(r"\d\d-[a-z][a-z][a-z]-\d\d|date=|[12]\d\d\d-[01]\d-[0-3]\d")

    # weights for words in URL path (lower is better)
    # for larger values of max_results, weighting probably
    # matters less (more sitemaps will be traversed looking
    # for more matches)
    PREF_TOKENS: list[tuple[str, float]] = [
        ("google-news", -2),
        ("googlenews", -2),
        ("news", -1),
        ("xml", -0.5),
        (".html", DISCARD),
    ]

    # things in URL path to weight against
    # (looking for single, whole site index)
    SECTIONS = [
        "athlet",  # NYT
        "authors",  # NYT
        "best-sell",  # NYT
        "books",
        "cities",  # NYT
        "city",  # NYT
        "cooking",  # NYT
        "games",  # NYT
        "local",
        "market-data",  # WSJ
        "recipe",  # NYT
        "region"  # NYT
        "roster",  # NYT
        "schedule",  # NYT
        "section",  # NYT
        "sports",  # NYT
        "tags",  # NYT
        "taxonomy",  # NYT
        "teams",  # NYT
        "vertical",  # NYT
        "video",  # NYT
        "weather",  # NYT
        "wirecutter",  # NYT
    ]
    SECTION_PREF = DISCARD / 2

    # Preference for canned paths; Since they're not "organic" (seen
    # in a sitemap from the site), they're slightly preferable to a
    # URL without ANY matching tokens, but less preferable to a URL
    # WITH matching tokens:
    UNPUBLISHED_GNEWS_SITEMAP_PREF = -0.25

    def page_pref(self, url: str) -> float:
        u = urlsplit(url)  # leaves query params in .path

        # check unflattened path for known paths
        # of good files:
        if u.path in discover._UNPUBLISHED_GNEWS_SITEMAP_PATHS:
            return self.UNPUBLISHED_GNEWS_SITEMAP_PREF

        # check unflattened path for known paths of index files
        # (prefer index files to urlset files that don't
        # have any token matches or match a well known path)
        if u.path in discover._UNPUBLISHED_SITEMAP_INDEX_PATHS:
            return self.UNPUBLISHED_INDEX_PREF

        path = u.path.lower()
        if u.query:
            path += f"?{u.query.lower()}"

        # don't want full year, per month or per-day files!
        if self.YEAR_RE.search(path) or self.DATE_RE.search(path):
            return self.DISCARD_PREF

        pref = 0.0
        for section in self.SECTIONS:
            if section in path:
                pref += self.SECTION_PREF
        if pref >= self.DISCARD_PREF:
            return pref

        for tok, weight in self.PREF_TOKENS:
            if tok in path:
                pref += weight
        return pref


if __name__ == "__main__":
    import argparse

    from mcmetadata.webpages import MEDIA_CLOUD_USER_AGENT

    classes = {"quick": GNewsCrawler, "gnews-full": GNewsCrawler, "full": BaseCrawler}

    ap = argparse.ArgumentParser("sitemap crawl test program")
    ap.add_argument("--max-depth", type=int, default=1, help="maximum traversal depth")
    ap.add_argument(
        "--max-results",
        type=int,
        default=3,
        help="maximum number of results to iterate for",
    )
    ap.add_argument("--quiet", action="store_true", help="disable logger output")
    ap.add_argument(
        "--sleep", type=float, default=0.1, help="sleep time between page visits"
    )
    ap.add_argument(
        "--type",
        choices=classes.keys(),
        default=next(iter(classes.keys())),  # first key
        help="type of crawl",
    )
    ap.add_argument("home_page", help="base url (home page) for crawl")
    args = ap.parse_args()

    if not args.quiet:
        logging.basicConfig(level=logging.INFO)

    # http://www.ap.com has a small map, www.npr.org and www.nytimes.com are large!
    # record so far is univision.com w/ three news sitemaps

    cls = classes[args.type]

    # The first site examined (csmonitor.com) turned out to have a google
    # news sitemap URL in a sitemap file referenced by robots.txt.
    crawler = cls(
        home_page=args.home_page,
        user_agent=MEDIA_CLOUD_USER_AGENT,
        max_depth=args.max_depth,
        max_results=args.max_results,
    )

    sleep_time = args.sleep
    while crawler.visit_one() == VisitResult.MORE:
        time.sleep(sleep_time)
    for res in crawler.results:
        print(res["url"])
