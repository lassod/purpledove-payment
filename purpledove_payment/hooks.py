app_name = "purpledove_payment"
app_title = "Purpledove Payment"
app_publisher = "Ejiroghene Douglas Dominic"
app_description = "A payment system application"
app_email = "ejise45@gmail.com"
app_license = "MIT"

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/purpledove_payment/css/purpledove_payment.css"
# app_include_js = "/assets/purpledove_payment/js/purpledove_payment.js"

# include js, css files in header of web template
# web_include_css = "/assets/purpledove_payment/css/purpledove_payment.css"
# web_include_js = "/assets/purpledove_payment/js/purpledove_payment.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "purpledove_payment/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "purpledove_payment.utils.jinja_methods",
# 	"filters": "purpledove_payment.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "purpledove_payment.install.before_install"
# after_install = "purpledove_payment.install.after_install"
# after_app_install = "purpledove_payment.utils.fetch_and_save_banks"

after_app_install = "purpledove_payment.utils.fetch_and_save_banks"

# Uninstallation
# ------------

# before_uninstall = "purpledove_payment.uninstall.before_uninstall"
# after_uninstall = "purpledove_payment.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "purpledove_payment.utils.before_app_install"
# after_app_install = "purpledove_payment.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "purpledove_payment.utils.before_app_uninstall"
# after_app_uninstall = "purpledove_payment.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "purpledove_payment.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"purpledove_payment.tasks.all"
# 	],
# 	"daily": [
# 		"purpledove_payment.tasks.daily"
# 	],
# 	"hourly": [
# 		"purpledove_payment.tasks.hourly"
# 	],
# 	"weekly": [
# 		"purpledove_payment.tasks.weekly"
# 	],
# 	"monthly": [
# 		"purpledove_payment.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "purpledove_payment.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "purpledove_payment.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "purpledove_payment.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["purpledove_payment.utils.before_request"]
# after_request = ["purpledove_payment.utils.after_request"]

# Job Events
# ----------
# before_job = ["purpledove_payment.utils.before_job"]
# after_job = ["purpledove_payment.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"purpledove_payment.auth.validate"
# ]