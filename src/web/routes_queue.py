#  OneShot-Extended (WPS penetration testing utility) is a fork of the tool with extra features
#  Copyright (C) 2026 chkndrp
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.

"""Queue API routes: enqueueing targets and driving the Orchestrator's
unattended auto-chain sweep via the shared QueueRunner."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from src import presenters

router = APIRouter()


class EnqueueRequest(BaseModel):
    bssid: str
    essid: str | None = None


@router.get("/api/queue/targets")
def get_targets(request: Request) -> dict:
    orchestrator = request.app.state.orchestrator
    queue_runner = request.app.state.queue_runner

    targets = []
    for record in orchestrator.get_queue_snapshot():
        row = presenters.format_queue_row(record)
        row["bssid"] = record.bssid
        targets.append(row)

    return {"running": queue_runner.is_running(), "targets": targets}


@router.post("/api/queue/targets", status_code=201)
def post_target(body: EnqueueRequest, request: Request) -> dict:
    request.app.state.orchestrator.enqueue(body.bssid, body.essid)
    return {"status": "enqueued"}


@router.post("/api/queue/start", status_code=202)
def post_start(request: Request) -> dict:
    request.app.state.queue_runner.start()
    return {"status": "started"}


@router.post("/api/queue/stop", status_code=202)
def post_stop(request: Request) -> dict:
    request.app.state.queue_runner.stop()
    return {"status": "stopped"}
