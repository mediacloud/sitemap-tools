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


class CrawlerException(Exception):
    """
    class for crawler errors
    """


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
        self,
        user_agent: str,
        max_depth: int,
        max_results: int,
        max_non_news_urls: int = 0,
    ):
        self.home_page: str | None = None
        self.user_agent = user_agent
        self.max_depth = max_depth  # required: use very large number to bypass!
        self.max_results = max_results
        self.max_non_news_urls = max_non_news_urls  # zero means don't check

        self.results: list[parser.Urlset] = []
        self.news_discoverer = discover.NewsDiscoverer(user_agent)
        self.to_visit: list[PageTuple] = []  # managed by heapq
        self.seen: set[str] = set()
        self.get_robots = True  # starting state
        self.robots_urls: list[str] = []
        self.pages_visited = 0
        self._started = False

    def page_pref(self, url: str) -> float:
        return 0.0

    def start(self, home_page: str, add_unpublished: bool = True) -> None:
        if not home_page.endswith("/"):
            home_page += "/"
        logger.info("start home_page %s", home_page)
        self.home_page = home_page
        self.add_unpublished = add_unpublished
        self.get_robots = True
        self._started = True

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
                logger.info("discarding %s %d %g %s", url, depth, pref, origin)
            else:
                logger.info("saving %s %g %d %s", url, pref, depth, origin)
                page = PageTuple(url=url, depth=depth, pref=pref, origin=origin)
                heapq.heappush(self.to_visit, page)
        else:
            logger.info("skipping %s %d %s", nurl, depth, origin)

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
        assert self._started
        assert self.home_page
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

    def visit_one(self, timeout: int = discover._TO) -> VisitResult:
        """
        visit one page, returns True while more work to be done
        to allow running as a background activity
        """
        if not self._started:
            raise CrawlerException("need to call start")
        assert self.home_page

        self.pages_visited += 1
        if self.get_robots:  # starting?
            # initial state: seed visit list with pages in robots.txt
            # and "well known" paths
            logger.info("===== getting robots.txt")
            try:
                self.robots_urls = self.news_discoverer.robots_sitemaps(
                    self.home_page, timeout=timeout
                )
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

            if self.add_unpublished:
                self.add_unpublished_paths()

            self.get_robots = False  # initialized
            # robots.txt counts as a visit
            # so don't visit any pages
        else:
            page = heapq.heappop(self.to_visit)
            url = page.url
            logger.info("getting %s %g %d %s", url, page.pref, page.depth, page.origin)
            # fetch and parse page:
            sitemap = None
            try:
                sitemap = self.news_discoverer.sitemap_get(
                    url,
                    timeout,
                    urlset_only=page.depth + 1 > self.max_depth,
                    max_non_news_urls=self.max_non_news_urls,
                )
            except self.FETCH_EXCEPTIONS:
                pass

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
        self._started = False
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

    # If path[?query] from the URL matches (unanchored) against any of
    # the following, the page is skipped.

    # Currently accepting single digits in path names:
    # (https://www.digitaltrends.com/sitemap-google-news-sitemap_1.xml
    # seems to be current), but counting to double digits are right out!

    # examples:
    # https://googlecrawl.npr.org/standard/sitemap_standard_01-Jan-90.xml
    # https://nypost.com/sitemap-1865.xml
    # https://nypost.com/sitemap-1999.xml?mm=12&dd=31
    # https://nypost.com/sitemap-nypost-post_tag.xml?sitemap=57
    # https://www.berkshireeagle.com/tncms/sitemap/editorial.xml?year=1970
    # https://www.chron.com/sitemap/4135000-4140000.xml
    # https://www.foxbusiness.com/sitemap.xml?type=videos&page=54
    # https://www.investors.com/post-sitemap125.xml
    # https://www.mercurynews.com/sitemap.xml?yyyy=0202&mm=03&dd=03
    # https://www.nytimes.com/sitemaps/new/cooking-1982-09.xml.gz
    # https://www.nytimes.com/sitemaps/new/sitemap-1851-09.xml.gz
    # https://www.sfgate.com/sitemap/65000-70000.xml
    # https://www.bartleby.com/static/sitemap-105.xml
    # https://www.bartleby.com/sitemap-papers-950000.xml
    SKIP_RE = re.compile(
        "|".join(
            [
                "date=",
                "year=",
                "yyyy=",
                r"(^|\D)(1[89]|2[012])\d\d($|\D|[01]\d)",
                r"[12]\d\d\d-[01]\d-[0-3]\d",
                r"\d\d-[a-z][a-z][a-z]-\d\d",
                r"high-school-answers",  # bartleby.com
                r"high-school-textbooks",  # bartleby.com
                r"page=\d\d",
                r"post-\d\d",
                r"quotesitemap\d",
                r"sitemap=\d\d",
                r"sitemap\d\d",
                r"sitemap-\d\d",  # bartleby.com
                r"sitemap-papers-\d\d",  # bartleby.com
                r"sitemapall\d",
                r"sitemapvideoall\d",
                r"tag-\d\d",
                r"\d\d\d\d-\d\d\d\d",
                r"\d\d\.xml",  # bartleby.com
            ]
        )
    )

    # weights for words in URL path (lower is better)
    # for larger values of max_results, weighting probably
    # matters less (more sitemaps will be traversed looking
    # for more matches)
    PREF_TOKENS: list[tuple[str, float]] = [
        ("google-news", -10),
        ("googlenews", -10),
        ("news", -5),
        (".html", DISCARD),
    ]

    # things in URL path to weight against
    # (looking for single, whole site index)
    SECTION_PREF = DISCARD / 2  # any two will kill (unless hits from above)
    SECTIONS = [
        "athletic",  # NYT
        "author",  # NYT, investors.com
        "best",  # NYT
        "books",
        "cities",  # NYT
        "category",  # investors.com
        "categories",  # bartleby.com
        "collects",  # NYT
        "companies",  # bloomberg
        "company",  # bloomberg
        "cooking",  # NYT
        "event",  # axs.com
        "high-school-answers",  # bartleby.com
        "games",  # NYT
        "local",
        "market-data",  # WSJ
        "papers",  # bartleby.com
        "people",  # bloomberg
        "performer",  # axs.com
        "profile",  # bloomberg, dailyfreepress.com
        "recipe",  # NYT
        "region",  # NYT
        "review",  # NYT
        "roster",  # NYT
        "schedule",  # NYT
        "section",  # NYT
        "seller",  # NYT
        "sports",  # NYT
        "staff",  # dailyfreepress.com
        "stats",  # NYT
        "tags",  # NYT
        "taxonomy",  # NYT
        "taxonomies",  # dailyfreepress.com
        "teams",  # NYT
        "venue",  # axs.com
        "vertical",  # NYT
        "video",  # NYT, NPR
        "weather",  # NYT
        "wirecutter",  # NYT
    ]

    # Preference for canned paths; Since they're not "organic" (seen
    # in a sitemap from the site), they're slightly preferable to a
    # URL without ANY matching tokens, but less preferable than
    # an organic URL WITH matching tokens:
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

        if self.SKIP_RE.search(path):
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
    import time

    from mcmetadata.webpages import MEDIA_CLOUD_USER_AGENT

    classes = {
        "quick": GNewsCrawler,
        "gnews-full": GNewsCrawlerFull,
        "full": BaseCrawler,
    }

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
        "--timeout", type=int, default=discover._TO, help="page fetch timeout"
    )
    ap.add_argument(
        "--type",
        choices=classes.keys(),
        default=next(iter(classes.keys())),  # first key
        help="type of crawl",
    )
    ap.add_argument("home_page", nargs="+", help="base url (home page) for crawl")
    args = ap.parse_args()

    if not args.quiet:
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
        )

    # http://www.ap.com has a small map, www.npr.org and www.nytimes.com are large!
    # record so far is univision.com w/ three news sitemaps

    cls = classes[args.type]

    # The first site examined (csmonitor.com) turned out to have a google
    # news sitemap URL in a sitemap file referenced by robots.txt.

    # https://developers.google.com/search/docs/crawling-indexing/sitemaps/news-sitemap
    # says "... a sitemap may have up to 1,000 news:news tags", and we're hoping for
    # files with nuthin' but news, so punt "early" if no news tags seen.
    # parsing 5k entries taking about 600ms on ifill.
    crawler = cls(
        user_agent=MEDIA_CLOUD_USER_AGENT,
        max_depth=args.max_depth,
        max_results=args.max_results,
        max_non_news_urls=5000,
    )

    sleep_time = args.sleep
    t0 = time.monotonic()
    for home in args.home_page:
        crawler.start(home)
        while crawler.visit_one(args.timeout) == VisitResult.MORE:
            time.sleep(sleep_time)

    for res in crawler.results:
        print(res["url"])
    t = time.monotonic() - t0
    print(f"{crawler.pages_visited} pages visited in {t:.6g} seconds")
