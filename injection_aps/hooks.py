app_name = "injection_aps"
app_title = "Injection APS"
app_publisher = "JCE"
app_description = "Injection planning and scheduling for ERPNext"
app_email = "kaibo_wang@whjichen.cn"
app_license = "mit"

required_apps = ["erpnext", "zelin_pp", "light_mes"]

doctype_js = {
	"APS Planning Run": "public/js/aps_planning_run.js",
	"Customer Delivery Schedule": "public/js/customer_delivery_schedule.js",
}

after_install = "injection_aps.install.after_install"
after_migrate = "injection_aps.install.after_migrate"
before_uninstall = "injection_aps.uninstall.before_uninstall"
