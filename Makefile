# to create development environment: `make`
# to run pre-commit linting/formatting: `make lint`

VENVDIR=venv
VENVBIN=$(VENVDIR)/bin
VENVDONE=.git/hooks/pre-commit

$(VENVDONE): $(VENVDIR) Makefile pyproject.toml
	$(VENVBIN)/pip install '.[dev]'
	$(VENVBIN)/pre-commit install

$(VENVDIR):
	python3 -mvenv $(VENVDIR)

# run pre-commit on all files
lint:	$(VENVDONE)
	$(VENVBIN)/pre-commit run --all-files

clean:
	-$(VENVBIN)/pre-commit clean
	rm -rf $(VENVDIR) build sitemap_tools.egg-info .pre-commit-run.sh.log \
		mc_sitemap_tools/__pycache__ .mypy_cache
