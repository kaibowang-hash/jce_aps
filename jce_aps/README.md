# JCE APS

A Frappe/ERPNext custom app for injection molding APS (Advanced Planning and Scheduling).

## Scope of this starter app
- Injection-machine capability matrix
- Color / halogen / eco transition rules
- APS Planning Run doctype with embedded demand lines
- Heuristic finite-capacity planner
- Schedule detail and exception log output
- Desk page skeleton for future board / gantt view

## Designed for
- Frappe Framework / ERPNext v15 style app layout
- Injection molding scheduling with sequence-dependent changeover scoring

## Install
```bash
bench get-app /path/to/jce_aps
bench --site yoursite install-app jce_aps
bench --site yoursite migrate
bench build
```

## Current design choices
This first version keeps demand lines inside `APS Planning Run` so you can test scheduling without first finishing all ERPNext integration work. Later you can add pull-from `Sales Order`, `Production Plan`, `Work Order`, or custom demand tables.

## Main doctypes
- APS Settings (Single)
- Injection Machine Capability
- Color Transition Rule
- APS Planning Run
  - child: APS Planning Demand
  - child: APS Schedule Detail
  - child: APS Exception Log

## Planner method
`jce_aps.api.run_planning_run`

## Next recommended steps
1. Add custom fields on Item / Workstation / Mold as needed.
2. Add ERPNext demand extraction.
3. Add mold constraints.
4. Add freeze-window logic.
5. Add board / gantt UI.
