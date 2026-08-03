# to create development environment: `make`
# to run pre-commit linting/formatting: `make lint`

VENVDIR=venv
VENVBIN=$(VENVDIR)/bin
VENVDONE=$(VENVDIR)/.done

help:
	@echo Usage:
	@echo "make install -- installs dev environment w/ pre-commit"
	@echo "make lint -- runs formatting, type checks"
	@echo "make release -- add tag and push to github"
	@echo "make clean -- remove development environment"
	@echo "make help -- this message!"

install: $(VENVDONE)

## run pre-commit checks on all files
lint:	$(VENVDONE)
	$(VENVBIN)/pre-commit run --all-files

# tag and push using mc-deploy itself!
release: lint
	venv/bin/python release.py release

# create venv with project dependencies
# --editable skips installing project sources in venv
# pre-commit is in dev optional-requirements
$(VENVDONE): $(VENVDIR) Makefile pyproject.toml
	$(VENVBIN)/python3 -m pip install --editable '.[dev,release]'
	$(VENVBIN)/pre-commit install
	touch $(VENVDONE)

$(VENVDIR):
	python3 -m venv $(VENVDIR)

## update .pre-commit-config.yaml
update:	$(VENVDONE)
	$(VENVBIN)/pre-commit autoupdate

## clean up development environment
clean:
	-$(VENVBIN)/pre-commit clean
	rm -rf $(VENVDIR) build sitemap_tools.egg-info .pre-commit-run.sh.log \
		mc_sitemap_tools/__pycache__ .mypy_cache
