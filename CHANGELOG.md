# Version History

* add new enries at top!
* update version number in pyproject.toml
* add tag v{major}.{minor}.{patch} and push to github
* adding a new function requires a new minor version
* removing a function or adding a new mandatory arg requires a new major version

## Version 1

### 1.0
	* 1.0.0:
		+ discover.py updates:
			- removed unused `page_exists` (breaking change),
			- add timeout argument to many functions
			- deduplicate find_gnews_fast output
			- ran thru autopep8
		+ pyproject.toml: add mypy settings
		+ ran mypy on all files, fixed missing return type in crawl.py

## Version 0

### 0.2

	* 0.2.1: have find_gnews_fast union robots & "unpublished" URLS
		add requirements to pyproject.toml
	* 0.2.0: add crawl.py with full_crawl_gnews_urls
		parser.py: fixed autopep8 induced mypy error

### 0.1
	* 0.1.0: add discover.py, this file!

### 0.0

	* 0.0.3: added py.typed
	* 0.0.2: fix project name in pyproject.toml
	* 0.0.1: initial checkin

