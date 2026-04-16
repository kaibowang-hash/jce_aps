
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

import frappe
from frappe import _
from frappe.utils import get_datetime, add_to_date


@dataclass
class MachineState:
    workstation: str
    available_at: object
    used_minutes: float = 0.0
    sequence_no: int = 0
    previous_attrs: Optional[dict] = None


@dataclass
class Candidate:
    workstation: str
    start_dt: object
    end_dt: object
    process_minutes: float
    setup_minutes: float
    transition_penalty: float
    late_hours: float
    score: float


def _get_settings(doc):
    try:
        settings = frappe.get_cached_doc("APS Settings")
    except Exception:
        settings = frappe._dict(
            daily_machine_hours=22,
            weight_tardiness=100,
            weight_setup_minutes=1,
            weight_transition_penalty=1,
            weight_nonpreferred_machine=50,
        )
    return settings


def _get_capabilities() -> Dict[Tuple[str, str], dict]:
    rows = frappe.get_all(
        "Injection Machine Capability",
        fields=[
            "item_code", "workstation", "output_per_hour", "preferred_machine", "rank",
            "supports_halogen", "supports_eco", "setup_time_same_item_min"
        ],
        limit_page_length=0,
    )
    return {(r.item_code, r.workstation): r for r in rows}


def _get_transition_rules() -> Dict[Tuple[str, str], dict]:
    rows = frappe.get_all(
        "Color Transition Rule",
        fields=["from_color", "to_color", "transition_penalty", "setup_time_min", "is_forbidden"],
        limit_page_length=0,
    )
    return {(r.from_color or "", r.to_color or ""): r for r in rows}


def _machine_states(capabilities, planning_start):
    workstations = sorted({r[1] for r in capabilities.keys()})
    return {ws: MachineState(workstation=ws, available_at=planning_start) for ws in workstations}


def _sort_demands(doc):
    rows = list(doc.demands or [])
    if doc.strategy == "Due Date First":
        return sorted(rows, key=lambda d: (get_datetime(d.due_datetime), d.priority or 999, -(d.qty or 0)))
    if doc.strategy == "Changeover First":
        return sorted(rows, key=lambda d: ((d.color or ""), d.is_halogen or 0, d.is_eco or 0, get_datetime(d.due_datetime)))
    return sorted(rows, key=lambda d: (d.priority or 999, get_datetime(d.due_datetime), -(d.qty or 0)))


def _get_transition(prev_attrs, demand, transition_rules):
    if not prev_attrs:
        return 0.0, 0.0, False

    setup = 0.0
    penalty = 0.0
    forbidden = False

    color_key = (prev_attrs.get("color") or "", demand.color or "")
    rule = transition_rules.get(color_key)
    if rule:
        setup += float(rule.setup_time_min or 0)
        penalty += float(rule.transition_penalty or 0)
        forbidden = forbidden or int(rule.is_forbidden or 0) == 1

    # Soft / hard sequence rules for halogen and eco
    prev_hal = int(prev_attrs.get("is_halogen") or 0)
    cur_hal = int(demand.is_halogen or 0)
    if prev_hal == 1 and cur_hal == 0:
        setup += 90
        penalty += 500
    elif prev_hal == 0 and cur_hal == 1:
        setup += 20
        penalty += 20

    prev_eco = int(prev_attrs.get("is_eco") or 0)
    cur_eco = int(demand.is_eco or 0)
    if prev_eco == 0 and cur_eco == 1:
        setup += 60
        penalty += 300
    elif prev_eco == 1 and cur_eco == 0:
        setup += 15
        penalty += 10

    return setup, penalty, forbidden


def _best_candidate(demand, states, caps, transition_rules, settings):
    due_dt = get_datetime(demand.due_datetime)
    candidates: List[Candidate] = []
    for state in states.values():
        cap = caps.get((demand.item_code, state.workstation))
        if not cap:
            continue
        if int(demand.is_halogen or 0) and not int(cap.supports_halogen or 0):
            continue
        if int(demand.is_eco or 0) and not int(cap.supports_eco or 0):
            continue
        if not cap.output_per_hour or float(cap.output_per_hour) <= 0:
            continue

        setup_minutes, transition_penalty, forbidden = _get_transition(state.previous_attrs, demand, transition_rules)
        if forbidden:
            continue

        process_minutes = (float(demand.qty or 0) / float(cap.output_per_hour)) * 60
        start_dt = state.available_at
        end_dt = start_dt + timedelta(minutes=setup_minutes + process_minutes)
        late_hours = max((end_dt - due_dt).total_seconds() / 3600, 0)
        nonpreferred_penalty = 0 if int(cap.preferred_machine or 0) else float(settings.weight_nonpreferred_machine or 0)
        score = (
            late_hours * float(settings.weight_tardiness or 100)
            + setup_minutes * float(settings.weight_setup_minutes or 1)
            + transition_penalty * float(settings.weight_transition_penalty or 1)
            + nonpreferred_penalty
        )
        candidates.append(Candidate(
            workstation=state.workstation,
            start_dt=start_dt,
            end_dt=end_dt,
            process_minutes=process_minutes,
            setup_minutes=setup_minutes,
            transition_penalty=transition_penalty,
            late_hours=late_hours,
            score=score,
        ))
    if not candidates:
        return None
    return sorted(candidates, key=lambda c: (c.score, c.end_dt, c.workstation))[0]


def plan_run(doc):
    settings = _get_settings(doc)
    planning_start = get_datetime(doc.planning_start_datetime)
    caps = _get_capabilities()
    transition_rules = _get_transition_rules()
    states = _machine_states(caps, planning_start)
    demands = _sort_demands(doc)

    doc.set("schedule_details", [])
    doc.set("exception_logs", [])

    total_score = 0.0
    total_setup_minutes = 0.0
    total_late_hours = 0.0
    scheduled = 0
    unscheduled = 0

    for d in demands:
        best = _best_candidate(d, states, caps, transition_rules, settings)
        if not best:
            unscheduled += 1
            doc.append("exception_logs", {
                "severity": "Error",
                "exception_type": "No Eligible Machine",
                "sales_order": d.sales_order,
                "item_code": d.item_code,
                "message": _("No eligible machine capability found for this demand."),
            })
            continue

        state = states[best.workstation]
        state.sequence_no += 1
        state.available_at = best.end_dt
        state.used_minutes += best.setup_minutes + best.process_minutes
        state.previous_attrs = {
            "color": d.color,
            "is_halogen": d.is_halogen,
            "is_eco": d.is_eco,
        }

        doc.append("schedule_details", {
            "workstation": best.workstation,
            "sequence_no": state.sequence_no,
            "sales_order": d.sales_order,
            "item_code": d.item_code,
            "qty": d.qty,
            "color": d.color,
            "is_halogen": d.is_halogen,
            "is_eco": d.is_eco,
            "setup_time_min": round(best.setup_minutes, 2),
            "transition_penalty": round(best.transition_penalty, 2),
            "start_datetime": best.start_dt,
            "end_datetime": best.end_dt,
            "late_hours": round(best.late_hours, 2),
            "machine_hours_used": round((best.setup_minutes + best.process_minutes) / 60, 2),
        })

        total_score += best.score
        total_setup_minutes += best.setup_minutes
        total_late_hours += best.late_hours
        scheduled += 1

    doc.total_score = round(total_score, 2)
    doc.scheduled_orders = scheduled
    doc.unscheduled_orders = unscheduled
    doc.total_setup_minutes = round(total_setup_minutes, 2)
    doc.total_late_hours = round(total_late_hours, 2)
    doc.status = "Planned"
    doc.save(ignore_permissions=True)

    return {
        "status": "ok",
        "scheduled_orders": scheduled,
        "unscheduled_orders": unscheduled,
        "total_score": doc.total_score,
    }
