"""Celery worker package for isolated background job registries."""



from app.workers.crm_tasks import (

    capture_lead_task,

    process_crm_action_task,

    process_crm_automation_action,

    run_automation_task,

)

from app.workers.crm_webhook_tasks import dispatch_webhook_task



__all__ = [

    "capture_lead_task",

    "dispatch_webhook_task",

    "process_crm_automation_action",

    "process_crm_action_task",

    "run_automation_task",

]


