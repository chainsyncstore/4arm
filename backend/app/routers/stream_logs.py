import uuid
import csv
import io
from typing import Optional
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.stream_log import StreamLog, StreamResult
from app.models.instance import Instance
from app.models.account import Account
from app.models.song import Song
from app.schemas.stream_log import StreamLogResponse, StreamLogSummary, PaginatedStreamLogResponse

router = APIRouter(prefix="/api/stream-logs", tags=["stream-logs"])


@router.get("/", response_model=PaginatedStreamLogResponse)
async def list_stream_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    instance_id: Optional[uuid.UUID] = None,
    account_id: Optional[uuid.UUID] = None,
    song_id: Optional[uuid.UUID] = None,
    result_filter: Optional[StreamResult] = Query(None, alias="result"),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: AsyncSession = Depends(get_db)
) -> PaginatedStreamLogResponse:
    """List stream logs with filters."""
    # Build filters
    filters = []
    if instance_id:
        filters.append(StreamLog.instance_id == instance_id)
    if account_id:
        filters.append(StreamLog.account_id == account_id)
    if song_id:
        filters.append(StreamLog.song_id == song_id)
    if result_filter:
        filters.append(StreamLog.result == result_filter)
    if date_from:
        filters.append(StreamLog.started_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        filters.append(StreamLog.started_at <= datetime.combine(date_to, datetime.max.time()))

    # Count query
    count_query = select(func.count(StreamLog.id))
    if filters:
        count_query = count_query.where(and_(*filters))

    count_result = await db.execute(count_query)
    total = count_result.scalar() or 0

    # Data query with joined relationships for enriched fields
    query = select(StreamLog).options(
        selectinload(StreamLog.instance),
        selectinload(StreamLog.account),
        selectinload(StreamLog.song)
    )
    if filters:
        query = query.where(and_(*filters))
    query = query.order_by(StreamLog.started_at.desc()).offset(skip).limit(limit)

    db_result = await db.execute(query)
    logs = db_result.scalars().all()

    # Build enriched responses
    responses = []
    for log in logs:
        resp = StreamLogResponse.model_validate(log)
        # Add enriched display fields
        if log.instance:
            resp.instance_name = log.instance.name
        if log.account:
            resp.account_email = log.account.email
        if log.song:
            resp.song_title = log.song.title
        responses.append(resp)

    return PaginatedStreamLogResponse(
        items=responses,
        total=total,
        skip=skip,
        limit=limit
    )


@router.get("/summary", response_model=StreamLogSummary)
async def get_stream_summary(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: AsyncSession = Depends(get_db)
) -> StreamLogSummary:
    """Get aggregated stream statistics."""
    query = select(StreamLog)

    if date_from:
        query = query.where(StreamLog.started_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        query = query.where(StreamLog.started_at <= datetime.combine(date_to, datetime.max.time()))

    result = await db.execute(query)
    logs = result.scalars().all()

    total = len(logs)
    successful = sum(1 for log in logs if log.result == StreamResult.SUCCESS)
    failed = sum(1 for log in logs if log.result == StreamResult.FAIL)

    success_rate = (successful / total * 100) if total > 0 else 0
    avg_duration = sum(log.duration_sec for log in logs) / total if total > 0 else 0

    # Count today's streams
    today = date.today()
    today_start = datetime.combine(today, datetime.min.time())
    today_end = datetime.combine(today, datetime.max.time())
    today_count = sum(1 for log in logs if today_start <= log.started_at <= today_end)

    return StreamLogSummary(
        total_streams=total,
        success_rate=round(success_rate, 2),
        avg_duration=round(avg_duration, 1),
        streams_today=today_count,
        failed_streams=failed
    )


@router.get("/export")
async def export_stream_logs(
    instance_id: Optional[uuid.UUID] = None,
    account_id: Optional[uuid.UUID] = None,
    song_id: Optional[uuid.UUID] = None,
    result_filter: Optional[StreamResult] = Query(None, alias="result"),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: AsyncSession = Depends(get_db)
) -> StreamingResponse:
    """Export stream logs as CSV with current filters."""
    # Build filters
    filters = []
    if instance_id:
        filters.append(StreamLog.instance_id == instance_id)
    if account_id:
        filters.append(StreamLog.account_id == account_id)
    if song_id:
        filters.append(StreamLog.song_id == song_id)
    if result_filter:
        filters.append(StreamLog.result == result_filter)
    if date_from:
        filters.append(StreamLog.started_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        filters.append(StreamLog.started_at <= datetime.combine(date_to, datetime.max.time()))

    # Query with joins for enriched data
    query = select(StreamLog).options(
        selectinload(StreamLog.instance),
        selectinload(StreamLog.account),
        selectinload(StreamLog.song)
    )
    if filters:
        query = query.where(and_(*filters))
    query = query.order_by(StreamLog.started_at.desc())

    result = await db.execute(query)
    logs = result.scalars().all()

    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        "id", "started_at", "duration_sec", "result", "failure_reason",
        "instance_id", "instance_name", "account_id", "account_email",
        "song_id", "song_title"
    ])

    # Data rows
    for log in logs:
        writer.writerow([
            str(log.id),
            log.started_at.isoformat() if log.started_at else "",
            log.duration_sec,
            log.result.value if log.result else "",
            log.failure_reason or "",
            str(log.instance_id) if log.instance_id else "",
            log.instance.name if log.instance else "",
            str(log.account_id) if log.account_id else "",
            log.account.email if log.account else "",
            str(log.song_id) if log.song_id else "",
            log.song.title if log.song else ""
        ])

    output.seek(0)

    # Generate filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    return StreamingResponse(
        io.BytesIO(output.getvalue().encode('utf-8')),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=stream_logs_{timestamp}.csv"}
    )
