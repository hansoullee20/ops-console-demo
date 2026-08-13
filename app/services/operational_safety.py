"""Phase 4.25 deterministic evidence, exception, schedule and correction services."""
from __future__ import annotations
import hashlib, json, sqlite3
from datetime import date, datetime, timezone

class SafetyError(ValueError): pass
def now(): return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00","Z")
def rowdict(row): return dict(row) if row else None
def audit(conn, action, entity, entity_id, before, after, reason, actor):
    conn.execute("INSERT INTO audit_log(actor_type,actor_id,action,entity_type,entity_id,before_json,after_json,reason) VALUES('user',?,?,?,?,?,?,?)",
                 (actor,action,entity,entity_id,json.dumps(before,ensure_ascii=False,sort_keys=True) if before is not None else None,json.dumps(after,ensure_ascii=False,sort_keys=True) if after is not None else None,reason))

def occurrence_key(code,scope,employee_id=None,work_date=None,source_ref=None):
    return "|".join(map(str,[code,scope,employee_id or "-",work_date or "-",source_ref or "-"]))

def evidence_key(ev):
    return ev.get("evidence_key") or "|".join(map(str,[ev["evidence_type"],ev["entity_type"],ev.get("entity_id") or "-",ev.get("import_run_id") or "-",ev.get("punch_event_id") or "-",ev.get("reference_text") or "-"]))

def observation_fingerprint(code,scope,employee_id,work_date,source_ref,evidence):
    material={"code":code,"scope":scope,"employeeId":employee_id,"workDate":work_date,"sourceRef":source_ref,"evidence":sorted(evidence_key(ev) for ev in evidence)}
    return hashlib.sha256(json.dumps(material,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()

def ensure_exception(conn,*,code,severity,scope,summary,detail=None,employee_id=None,work_date=None,import_run_id=None,source_ref=None,evidence=(),actor="system"):
    evidence=tuple(evidence)
    key=occurrence_key(code,scope,employee_id,work_date,source_ref)
    fingerprint=observation_fingerprint(code,scope,employee_id,work_date,source_ref,evidence)
    current=conn.execute("SELECT * FROM operational_exceptions WHERE occurrence_key=? AND status IN ('open','acknowledged')",(key,)).fetchone()
    created=False
    if current is None:
        previous=conn.execute("SELECT id,status,observation_fingerprint FROM operational_exceptions WHERE occurrence_key=? ORDER BY id DESC LIMIT 1",(key,)).fetchone()
        if previous and previous["status"] in {"resolved","waived"} and previous["observation_fingerprint"]==fingerprint:
            return exception_detail(conn,previous["id"])
        eid=conn.execute("INSERT INTO operational_exceptions(exception_code,severity,scope,employee_id,work_date,import_run_id,occurrence_key,observation_fingerprint,summary,detail,previous_occurrence_id,created_by) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
          (code,severity,scope,employee_id,work_date,import_run_id,key,fingerprint,summary,detail,previous["id"] if previous else None,actor)).lastrowid
        conn.execute("INSERT INTO exception_events(exception_id,event_type,to_status,actor) VALUES(?,'created','open',?)",(eid,actor));created=True
    else:eid=current["id"]
    added=0
    for ev in evidence:
        ekey=evidence_key(ev)
        cur=conn.execute("INSERT OR IGNORE INTO exception_evidence_links(exception_id,evidence_type,entity_type,entity_id,import_run_id,punch_event_id,reference_text,evidence_key,created_by) VALUES(?,?,?,?,?,?,?,?,?)",
          (eid,ev["evidence_type"],ev["entity_type"],ev.get("entity_id"),ev.get("import_run_id"),ev.get("punch_event_id"),ev.get("reference_text"),ekey,actor))
        added+=cur.rowcount
    if added and not created:
        conn.execute("UPDATE operational_exceptions SET observation_fingerprint=? WHERE id=?",(fingerprint,eid))
        conn.execute("INSERT INTO exception_events(exception_id,event_type,note,actor) VALUES(?,'evidence_linked',?,?)",(eid,f"{added} new evidence link(s)",actor))
    return exception_detail(conn,eid)

def transition_exception(conn,exception_id,to_status,note,actor="operator"):
    if to_status not in {"acknowledged","resolved","waived"}: raise SafetyError("invalid exception transition")
    row=conn.execute("SELECT * FROM operational_exceptions WHERE id=?",(exception_id,)).fetchone()
    if not row: raise SafetyError("exception not found")
    from app.services.month_close import MonthCloseError,assert_exception_open
    try: assert_exception_open(conn,exception_id)
    except MonthCloseError as exc: raise SafetyError(str(exc)) from exc
    allowed={"open":{"acknowledged","resolved","waived"},"acknowledged":{"resolved","waived"}}
    if to_status not in allowed.get(row["status"],set()): raise SafetyError("exception transition is not allowed")
    if to_status in {"resolved","waived"} and not (note or "").strip(): raise SafetyError("resolution note is required")
    stamp=now(); fields={"acknowledged":("acknowledged_at","acknowledged_by"),"resolved":("resolved_at","resolved_by"),"waived":("waived_at","waived_by")}[to_status]
    conn.execute(f"UPDATE operational_exceptions SET status=?,{fields[0]}=?,{fields[1]}=?,resolution_note=CASE WHEN ? IN ('resolved','waived') THEN ? ELSE resolution_note END WHERE id=?",(to_status,stamp,actor,to_status,note,exception_id))
    conn.execute("INSERT INTO exception_events(exception_id,event_type,from_status,to_status,note,actor) VALUES(?,?,?,?,?,?)",(exception_id,to_status,row["status"],to_status,note,actor))
    audit(conn,f"exception.{to_status}","operational_exceptions",exception_id,dict(row),rowdict(conn.execute("SELECT * FROM operational_exceptions WHERE id=?",(exception_id,)).fetchone()),note,actor)
    return exception_detail(conn,exception_id)

def list_exceptions(conn,*,status=None,employee_id=None,start=None,end=None,code=None,severity=None,source_only=False):
    sql="SELECT x.*,e.name employee_name FROM operational_exceptions x LEFT JOIN employees e ON e.id=x.employee_id WHERE 1=1"; args=[]
    for clause,value in [("x.status=?",status),("x.employee_id=?",employee_id),("x.work_date>=?",start),("x.work_date<=?",end),("x.exception_code=?",code),("x.severity=?",severity)]:
        if value is not None:sql+=" AND "+clause;args.append(value)
    if source_only:sql+=" AND x.scope IN ('site','source')"
    sql+=" ORDER BY CASE x.severity WHEN 'critical' THEN 0 WHEN 'review' THEN 1 ELSE 2 END,x.work_date,x.id"
    return [dict(r) for r in conn.execute(sql,args)]

def exception_detail(conn,exception_id):
    item=rowdict(conn.execute("SELECT x.*,e.name employee_name FROM operational_exceptions x LEFT JOIN employees e ON e.id=x.employee_id WHERE x.id=?",(exception_id,)).fetchone())
    if not item: raise SafetyError("exception not found")
    item["events"]=[dict(r) for r in conn.execute("SELECT * FROM exception_events WHERE exception_id=? ORDER BY id",(exception_id,))]
    item["evidence"]=[dict(r) for r in conn.execute("SELECT * FROM exception_evidence_links WHERE exception_id=? ORDER BY id",(exception_id,))]
    return item

def _validate_employee_date(conn,employee_id,work_date):
    e=conn.execute("SELECT * FROM employees WHERE id=?",(employee_id,)).fetchone()
    if not e: raise SafetyError("employee not found")
    if work_date<e["hire_date"] or (e["end_date"] and work_date>e["end_date"]): raise SafetyError("date is outside employment period")

def create_adjustment(conn,*,employee_id,work_date,recognized_in_at=None,recognized_out_at=None,resulting_status="normal",reason,reference_note=None,actor="operator",supersedes_id=None):
    from app.services.month_close import MonthCloseError,assert_range_open
    try: assert_range_open(conn,work_date,work_date)
    except MonthCloseError as exc: raise SafetyError(str(exc)) from exc
    _validate_employee_date(conn,employee_id,work_date)
    if not reason.strip(): raise SafetyError("reason is required")
    active=conn.execute("SELECT * FROM manual_attendance_adjustments WHERE employee_id=? AND work_date=? AND status='active'",(employee_id,work_date)).fetchone()
    if active and active["id"]!=supersedes_id: raise SafetyError("an active manual adjustment already exists")
    if supersedes_id and (not active or active["id"]!=supersedes_id): raise SafetyError("only the active adjustment may be superseded")
    old_att=conn.execute("SELECT * FROM attendance_days WHERE employee_id=? AND work_date=?",(employee_id,work_date)).fetchone()
    if old_att and old_att["confirmed_at"] and not active: raise SafetyError("unrelated confirmed attendance already exists")
    if active: conn.execute("UPDATE manual_attendance_adjustments SET status='superseded',ended_at=?,ended_by=?,end_reason=? WHERE id=?",(now(),actor,reason,active["id"]))
    stamp=now()
    conn.execute("INSERT INTO attendance_days(employee_id,work_date,status,actual_in_at,actual_out_at,source,confirmed_at,confirmed_by,review_flag,review_note) VALUES(?,?,?,?,?,'manual',?,?,NULL,?) ON CONFLICT(employee_id,work_date) DO UPDATE SET status=excluded.status,actual_in_at=excluded.actual_in_at,actual_out_at=excluded.actual_out_at,source='manual',confirmed_at=excluded.confirmed_at,confirmed_by=excluded.confirmed_by,review_flag=NULL,review_note=excluded.review_note,last_import_run_id=NULL",
      (employee_id,work_date,resulting_status,recognized_in_at,recognized_out_at,stamp,actor,reason))
    attendance_id=conn.execute("SELECT id FROM attendance_days WHERE employee_id=? AND work_date=?",(employee_id,work_date)).fetchone()[0]
    aid=conn.execute("INSERT INTO manual_attendance_adjustments(employee_id,work_date,recognized_in_at,recognized_out_at,resulting_status,reason,reference_note,supersedes_adjustment_id,attendance_id,created_by) VALUES(?,?,?,?,?,?,?,?,?,?)",
      (employee_id,work_date,recognized_in_at,recognized_out_at,resulting_status,reason,reference_note,supersedes_id,attendance_id,actor)).lastrowid
    if active:conn.execute("UPDATE manual_attendance_adjustments SET superseded_by_adjustment_id=? WHERE id=?",(aid,active["id"]))
    after=rowdict(conn.execute("SELECT * FROM manual_attendance_adjustments WHERE id=?",(aid,)).fetchone());audit(conn,"attendance.manual_adjust", "manual_attendance_adjustments",aid,dict(active) if active else None,after,reason,actor);return after

def end_adjustment(conn,adjustment_id,status,reason,actor="operator"):
    if status not in {"cancelled","voided"}: raise SafetyError("invalid adjustment end status")
    row=conn.execute("SELECT * FROM manual_attendance_adjustments WHERE id=? AND status='active'",(adjustment_id,)).fetchone()
    if not row: raise SafetyError("active adjustment not found")
    from app.services.month_close import MonthCloseError,assert_range_open
    try: assert_range_open(conn,row["work_date"],row["work_date"])
    except MonthCloseError as exc: raise SafetyError(str(exc)) from exc
    attendance=conn.execute("SELECT * FROM attendance_days WHERE id=?",(row["attendance_id"],)).fetchone()
    # Ownership guard: only remove this adjustment's exact manual projection.
    owned=attendance and attendance["employee_id"]==row["employee_id"] and attendance["work_date"]==row["work_date"] and attendance["source"]=="manual" and attendance["confirmed_by"]==row["created_by"] and attendance["status"]==row["resulting_status"] and attendance["actual_in_at"]==row["recognized_in_at"] and attendance["actual_out_at"]==row["recognized_out_at"]
    conn.execute("UPDATE manual_attendance_adjustments SET status=?,ended_at=?,ended_by=?,end_reason=? WHERE id=?",(status,now(),actor,reason,adjustment_id))
    if owned:
        punches=conn.execute("SELECT COUNT(*) FROM punch_events WHERE employee_id=? AND work_date=? AND rolled_back_at IS NULL",(row["employee_id"],row["work_date"])).fetchone()[0]
        conn.execute("UPDATE attendance_days SET confirmed_at=NULL,confirmed_by=NULL WHERE id=?",(attendance["id"],))
        if punches:
            from app.services.xls_pipeline import derive_attendance
            derive_attendance(conn,[(row["employee_id"],row["work_date"])])
        else: conn.execute("UPDATE attendance_days SET status='unknown',actual_in_at=NULL,actual_out_at=NULL,source='manual',review_flag='manual_review',review_note=?,last_import_run_id=NULL WHERE id=?",("수동 근무 인정이 종료되어 확인이 필요합니다.",attendance["id"]))
    updated=rowdict(conn.execute("SELECT * FROM manual_attendance_adjustments WHERE id=?",(adjustment_id,)).fetchone());audit(conn,f"attendance.manual_{status}","manual_attendance_adjustments",adjustment_id,dict(row),updated,reason,actor);return updated

def create_schedule(conn,*,employee_id,effective_from,effective_to,weekday_mask,expected_start_time=None,expected_end_time=None,actor="operator"):
    from app.services.month_close import MonthCloseError,assert_range_open
    try: assert_range_open(conn,effective_from,effective_to)
    except MonthCloseError as exc: raise SafetyError(str(exc)) from exc
    _validate_employee_date(conn,employee_id,effective_from)
    if effective_to:
        _validate_employee_date(conn,employee_id,effective_to)
    if effective_to and effective_from>effective_to: raise SafetyError("schedule start must not follow end")
    overlap=conn.execute("SELECT id FROM employee_work_schedules WHERE employee_id=? AND status='active' AND effective_from<=COALESCE(?, '9999-12-31') AND COALESCE(effective_to,'9999-12-31')>=?",(employee_id,effective_to,effective_from)).fetchone()
    if overlap: raise SafetyError("schedule period overlaps an active schedule")
    sid=conn.execute("INSERT INTO employee_work_schedules(employee_id,effective_from,effective_to,weekday_mask,expected_start_time,expected_end_time,created_by) VALUES(?,?,?,?,?,?,?)",(employee_id,effective_from,effective_to,weekday_mask,expected_start_time,expected_end_time,actor)).lastrowid
    result=rowdict(conn.execute("SELECT * FROM employee_work_schedules WHERE id=?",(sid,)).fetchone());audit(conn,"schedule.create","employee_work_schedules",sid,None,result,"schedule created",actor);return result

def retire_schedule(conn,schedule_id,reason,actor="operator"):
    if not (reason or "").strip(): raise SafetyError("reason is required")
    row=conn.execute("SELECT * FROM employee_work_schedules WHERE id=? AND status='active'",(schedule_id,)).fetchone()
    if not row: raise SafetyError("active schedule not found")
    from app.services.month_close import MonthCloseError,assert_range_open
    try: assert_range_open(conn,row["effective_from"],row["effective_to"])
    except MonthCloseError as exc: raise SafetyError(str(exc)) from exc
    conn.execute("UPDATE employee_work_schedules SET status='retired',retired_at=?,retired_by=? WHERE id=?",(now(),actor,schedule_id))
    updated=rowdict(conn.execute("SELECT * FROM employee_work_schedules WHERE id=?",(schedule_id,)).fetchone())
    audit(conn,"schedule.retire","employee_work_schedules",schedule_id,dict(row),updated,reason,actor)
    return updated

def set_schedule_date(conn,*,employee_id,work_date,is_scheduled,expected_start_time=None,expected_end_time=None,label=None,actor="operator",supersedes_id=None):
    from app.services.month_close import MonthCloseError,assert_range_open
    try: assert_range_open(conn,work_date,work_date)
    except MonthCloseError as exc: raise SafetyError(str(exc)) from exc
    _validate_employee_date(conn,employee_id,work_date)
    active=conn.execute("SELECT * FROM employee_schedule_dates WHERE employee_id=? AND work_date=? AND status='active'",(employee_id,work_date)).fetchone()
    if active and active["id"]!=supersedes_id: raise SafetyError("an active date override already exists")
    if supersedes_id and (not active or active["id"]!=supersedes_id): raise SafetyError("only active override may be superseded")
    if active:conn.execute("UPDATE employee_schedule_dates SET status='superseded' WHERE id=?",(active["id"],))
    oid=conn.execute("INSERT INTO employee_schedule_dates(employee_id,work_date,is_scheduled,expected_start_time,expected_end_time,label,supersedes_date_id,created_by) VALUES(?,?,?,?,?,?,?,?)",(employee_id,work_date,int(is_scheduled),expected_start_time,expected_end_time,label,supersedes_id,actor)).lastrowid
    result=rowdict(conn.execute("SELECT * FROM employee_schedule_dates WHERE id=?",(oid,)).fetchone());audit(conn,"schedule.override","employee_schedule_dates",oid,dict(active) if active else None,result,"date override",actor);return result

def cancel_schedule_date(conn,override_id,reason,actor="operator"):
    if not (reason or "").strip(): raise SafetyError("reason is required")
    row=conn.execute("SELECT * FROM employee_schedule_dates WHERE id=? AND status='active'",(override_id,)).fetchone()
    if not row: raise SafetyError("active date override not found")
    from app.services.month_close import MonthCloseError,assert_range_open
    try: assert_range_open(conn,row["work_date"],row["work_date"])
    except MonthCloseError as exc: raise SafetyError(str(exc)) from exc
    conn.execute("UPDATE employee_schedule_dates SET status='cancelled' WHERE id=?",(override_id,))
    updated=rowdict(conn.execute("SELECT * FROM employee_schedule_dates WHERE id=?",(override_id,)).fetchone())
    audit(conn,"schedule.override_cancel","employee_schedule_dates",override_id,dict(row),updated,reason,actor)
    return updated

def resolve_schedule(conn,employee_id,work_date):
    employee=conn.execute("SELECT hire_date,end_date FROM employees WHERE id=?",(employee_id,)).fetchone()
    if not employee: raise SafetyError("employee not found")
    if work_date<employee["hire_date"] or (employee["end_date"] and work_date>employee["end_date"]):
        return {"isScheduled":False,"source":"employment_period","expectedStart":None,"expectedEnd":None,"evidenceId":None}
    override=conn.execute("SELECT * FROM employee_schedule_dates WHERE employee_id=? AND work_date=? AND status='active' ORDER BY id DESC LIMIT 1",(employee_id,work_date)).fetchone()
    if override:return {"isScheduled":bool(override["is_scheduled"]),"source":"employee_date_override","expectedStart":override["expected_start_time"],"expectedEnd":override["expected_end_time"],"evidenceId":override["id"]}
    schedule=conn.execute("SELECT * FROM employee_work_schedules WHERE employee_id=? AND status='active' AND effective_from<=? AND (effective_to IS NULL OR effective_to>=?) ORDER BY effective_from DESC,id DESC LIMIT 1",(employee_id,work_date,work_date)).fetchone()
    if schedule:
        scheduled=str(date.fromisoformat(work_date).weekday()) in set(schedule["weekday_mask"].split(","))
        return {"isScheduled":scheduled,"source":"employee_schedule","expectedStart":schedule["expected_start_time"],"expectedEnd":schedule["expected_end_time"],"evidenceId":schedule["id"]}
    calendar=conn.execute("SELECT * FROM site_calendar WHERE calendar_date=?",(work_date,)).fetchone()
    is_working=bool(calendar["is_working"]) if calendar else date.fromisoformat(work_date).weekday()<5
    return {"isScheduled":is_working,"source":"site_calendar","expectedStart":None,"expectedEnd":None,"evidenceId":calendar["id"] if calendar else None}

def _source_observation(conn,code,work_date,import_run_id,observed,expected,scheduled,measurement):
    conn.execute("INSERT OR IGNORE INTO source_quality_observations(observation_code,work_date,import_run_id,observed_value,expected_value,scheduled_worker_count,rule_version,measurement_json) VALUES(?,?,?,?,?,?,'1',?)",
      (code,work_date,import_run_id,observed,expected,scheduled,json.dumps(measurement,sort_keys=True)))
    return conn.execute("SELECT id FROM source_quality_observations WHERE observation_code=? AND work_date=? AND IFNULL(import_run_id,-1)=IFNULL(?,-1) AND rule_version='1'",(code,work_date,import_run_id)).fetchone()[0]

def reconcile(conn,start,end,actor="system"):
    created=[]
    employees=conn.execute("SELECT * FROM employees WHERE hire_date<=? AND (end_date IS NULL OR end_date>=?)",(end,start)).fetchall()
    day=date.fromisoformat(start);last=date.fromisoformat(end)
    while day<=last:
        iso=day.isoformat(); scheduled=[]
        for e in employees:
            if resolve_schedule(conn,e["id"],iso)["isScheduled"]:scheduled.append(e)
        punches=conn.execute("SELECT * FROM punch_events WHERE work_date=? AND rolled_back_at IS NULL ORDER BY id",(iso,)).fetchall()
        coverage=conn.execute("SELECT d.*,r.source_filename FROM import_run_days d JOIN import_runs r ON r.id=d.import_run_id WHERE d.work_date=? AND r.status='applied' ORDER BY d.id DESC LIMIT 1",(iso,)).fetchone()
        expected_run=conn.execute("SELECT * FROM import_runs WHERE status='applied' AND period_start<=? AND period_end>=? ORDER BY id DESC LIMIT 1",(iso,iso)).fetchone()
        source_wide_problem=False
        if scheduled and coverage and coverage["raw_punch_count"]==0:
            source_wide_problem=True
            oid=_source_observation(conn,"covered_but_zero_events",iso,coverage["import_run_id"],0,len(scheduled),len(scheduled),{"coverageStatus":coverage["coverage_status"]})
            created.append(ensure_exception(conn,code="covered_but_zero_events",severity="review",scope="source",work_date=iso,import_run_id=coverage["import_run_id"],summary="가져온 자료에 전체 지문 기록이 없습니다",source_ref=f"coverage:{coverage['import_run_id']}",evidence=[{"evidence_type":"fingerprint_import","entity_type":"import_runs","entity_id":coverage["import_run_id"],"import_run_id":coverage["import_run_id"]},{"evidence_type":"source_quality_measurement","entity_type":"source_quality_observations","entity_id":oid}],actor=actor))
        elif scheduled and expected_run and not coverage:
            source_wide_problem=True
            oid=_source_observation(conn,"expected_period_not_covered",iso,expected_run["id"],None,len(scheduled),len(scheduled),{"periodStart":expected_run["period_start"],"periodEnd":expected_run["period_end"]})
            created.append(ensure_exception(conn,code="expected_period_not_covered",severity="review",scope="source",work_date=iso,import_run_id=expected_run["id"],summary="예상된 근무일이 가져온 자료 범위에 포함되지 않았습니다",source_ref=f"coverage:{expected_run['id']}",evidence=[{"evidence_type":"fingerprint_import","entity_type":"import_runs","entity_id":expected_run["id"],"import_run_id":expected_run["id"]},{"evidence_type":"source_quality_measurement","entity_type":"source_quality_observations","entity_id":oid}],actor=actor))
        observed_workers={p["employee_id"] for p in punches if p["employee_id"] is not None}
        if coverage and len(scheduled)>=4 and 0<len(observed_workers)*2<len(scheduled):
            oid=_source_observation(conn,"source_quality_drop",iso,coverage["import_run_id"],len(observed_workers),len(scheduled),len(scheduled),{"activePunches":len(punches),"observedWorkers":len(observed_workers)})
            created.append(ensure_exception(conn,code="source_quality_drop",severity="review",scope="source",work_date=iso,import_run_id=coverage["import_run_id"],summary="예정 인원에 비해 지문 기록 인원이 크게 적습니다",source_ref=f"coverage:{coverage['import_run_id']}",evidence=[{"evidence_type":"fingerprint_import","entity_type":"import_runs","entity_id":coverage["import_run_id"],"import_run_id":coverage["import_run_id"]},{"evidence_type":"source_quality_measurement","entity_type":"source_quality_observations","entity_id":oid}],actor=actor))
        for e in scheduled:
            ep=[p for p in punches if p["employee_id"]==e["id"]]
            if not ep and not source_wide_problem:
                schedule=resolve_schedule(conn,e["id"],iso)
                evidence=[{"evidence_type":"employee_work_schedule","entity_type":schedule["source"],"entity_id":schedule["evidenceId"],"reference_text":f"{schedule['source']}:{schedule['evidenceId'] or iso}"}]
                if coverage:evidence.append({"evidence_type":"fingerprint_import","entity_type":"import_runs","entity_id":coverage["import_run_id"],"import_run_id":coverage["import_run_id"]})
                created.append(ensure_exception(conn,code="scheduled_no_punch",severity="review",scope="employee",employee_id=e["id"],work_date=iso,summary="예정 근무일에 기록된 지문이 없습니다",detail="결근으로 판정하지 않으며 관리자 확인이 필요합니다.",evidence=evidence,actor=actor))
            elif len(ep)==1:
                created.append(ensure_exception(conn,code="incomplete_day",severity="review",scope="employee",employee_id=e["id"],work_date=iso,import_run_id=ep[0]["active_import_run_id"],summary="지문 기록이 한 건뿐입니다",evidence=[{"evidence_type":"fingerprint_punch","entity_type":"punch_events","entity_id":ep[0]["id"],"punch_event_id":ep[0]["id"]}],actor=actor))
        day=date.fromordinal(day.toordinal()+1)
    # Promote leave findings without losing the actual employee/date evidence.
    from app.services import leave_operations, work_calendar
    for leave in leave_operations.list_leave(conn,None,start,end):
        for code in leave.get("findings",[]):
            if code=="leave_attendance_conflict":
                period_start=max(start,leave["startDate"]);period_end=min(end,leave["endDate"])
                for iso in work_calendar.working_dates(conn,period_start,period_end):
                    if leave_operations.approved_leave_coverage(conn,leave["employeeId"],iso)["coverage"]!="full":continue
                    punches=conn.execute("SELECT id,active_import_run_id FROM punch_events WHERE employee_id=? AND work_date=? AND rolled_back_at IS NULL ORDER BY id",(leave["employeeId"],iso)).fetchall()
                    if not punches:continue
                    evidence=[{"evidence_type":"approved_leave","entity_type":"leave_requests","entity_id":leave["id"]}]+[{"evidence_type":"fingerprint_punch","entity_type":"punch_events","entity_id":p["id"],"punch_event_id":p["id"],"import_run_id":p["active_import_run_id"]} for p in punches]
                    created.append(ensure_exception(conn,code=code,severity="review",scope="employee",employee_id=leave["employeeId"],work_date=iso,summary=code,evidence=evidence,actor=actor))
            else:
                created.append(ensure_exception(conn,code=code,severity="review",scope="employee",employee_id=leave["employeeId"],work_date=leave["startDate"],summary=code,evidence=[{"evidence_type":"approved_leave","entity_type":"leave_requests","entity_id":leave["id"]}],actor=actor))
    return created

def operations_read_model(conn,start,end,**filters):
    reconcile(conn,start,end)
    return {"startDate":start,"endDate":end,"exceptions":list_exceptions(conn,start=start,end=end,**filters),"sourceQuality":[dict(r) for r in conn.execute("SELECT * FROM source_quality_observations WHERE work_date BETWEEN ? AND ? ORDER BY id",(start,end))],"manualAdjustments":[dict(r) for r in conn.execute("SELECT * FROM manual_attendance_adjustments WHERE work_date BETWEEN ? AND ? ORDER BY id",(start,end))]}
