# Simple tools for consuming sitemap files

Goals:
* Simple
* Composable
* Parser process a single page without recursion
* Crawler class has "visit_one" method to allow background crawling
* For internal use (not adding to PyPI, at this time, anyway)

## TO CREATE DEVELOPMENT ENVIRONMENT

run `make` (installs pre-commit hook to run formatting and mypy checks)

to run pre-commit checks at any time: `make lint`
