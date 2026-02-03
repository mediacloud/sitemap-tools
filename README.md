# Simple tools for consuming news sitemap files

Goals:
* Simple
* Composable
* Parser process a single page without recursion
* Crawler class has "visit_one" method to allow background crawling
* For internal use (not adding to PyPI, at this time, anyway)

*NOTE* Mediacloud is currently only interested in
[Google News Sitemaps](https://www.google.com/schemas/sitemap-news/0.9/)!
Any additional utility is incidental.

## TO CREATE DEVELOPMENT ENVIRONMENT

`make` installs development environment, pre-commit hook, runs pre-commit

`make clean` removes development and pre-commit environments
