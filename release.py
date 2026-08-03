"""
An mc-deploy based script to tag and push a release!
"""

from mc_deploy.base import BaseDeploy
from mc_deploy.pyproject import PyProjectMixin
from mc_deploy.release import ReleaseMixin


class MCSitemapToolsDeploy(PyProjectMixin, ReleaseMixin, BaseDeploy):
    """
    All ingredients in Mixins!!
    """

    PROJECT_REPO = "sitemap-tools"


mcstd = MCSitemapToolsDeploy()
mcstd.run()
