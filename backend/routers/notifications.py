from fastapi import APIRouter, Depends, HTTPException
from backend.routers.auth import require_admin
from backend.models.user import AdminUser

router = APIRouter()

JOB_MAP = {
    "daily_summary": "daily_summary_job",
    "checkin_reminder": "checkin_reminder_job",
    "payment_timeout": "payment_timeout_job",
    "checkout_review": "checkout_review_job",
}


@router.post("/trigger/{job_id}")
async def trigger_job(
    job_id: str,
    _: AdminUser = Depends(require_admin),
):
    if job_id not in JOB_MAP:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    from backend.services import notification_service as ns
    func_name = JOB_MAP[job_id]
    func = getattr(ns, func_name, None)
    if func is None:
        raise HTTPException(status_code=500, detail="Job function not found")

    await func()
    return {"message": f"Job '{job_id}' executed successfully"}
