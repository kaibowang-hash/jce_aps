
app_name = "jce_aps"
app_title = "JCE APS"
app_publisher = "OpenAI"
app_description = "Injection molding APS app for ERPNext/Frappe"
app_email = "noreply@example.com"
app_license = "MIT"

add_to_apps_screen = [
    {
        "name": "jce-aps",
        "title": "JCE APS",
        "route": "/app/aps-planning-board",
        "has_permission": "jce_aps.api.can_access_aps",
    }
]

doctype_js = {
    "APS Planning Run": "public/js/aps_planning_run.js",
}

fixtures = []
