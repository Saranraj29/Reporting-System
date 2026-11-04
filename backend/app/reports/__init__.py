"""Report registry. A new report is one new module that calls register(); add it to this list."""

from . import monthly, performance, visibility, weekly
from .base import REGISTRY, ReportContext, ReportDef  # noqa: F401

ALL = [weekly.REPORT, monthly.REPORT, performance.REPORT, visibility.REPORT]
