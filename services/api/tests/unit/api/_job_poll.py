"""`GET /admin/jobs/{jobId}` as `create_app` mounts it; its guard records into a spy of its own."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from candleviewer.admin.http import AdminAreaRefused, admin_area_refused_handler
from candleviewer.api.admin_jobs import make_admin_jobs_router
from candleviewer.api.recorder_admin import AdminJobStore
from tests.unit.admin._admin_fakes import AuditSpy


def mount_job_poll(app: FastAPI, jobs: AdminJobStore, resolver: Any, audit: Any = None) -> None:
    app.add_exception_handler(AdminAreaRefused, admin_area_refused_handler)
    app.include_router(make_admin_jobs_router(jobs, resolver=resolver, audit=audit or AuditSpy()))
