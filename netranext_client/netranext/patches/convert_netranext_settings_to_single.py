import frappe

def execute():
	"""
	Convert NetraNext Settings to a Single DocType for SaaS multi-tenant setup.
	This patch converts the regular DocType to a Single DocType and ensures
	proper configuration for tenant bench settings.
	"""

	# Check if the DocType exists and get current configuration
	doctype = frappe.get_doc("DocType", "NetraNext Settings")

	# Update to Single DocType if not already set
	if not doctype.issingle:
		frappe.db.set_value("DocType", "NetraNext Settings", "issingle", 1)

		# Remove settings that are incompatible with Single DocType
		frappe.db.set_value("DocType", "NetraNext Settings", "autoname", None)
		frappe.db.set_value("DocType", "NetraNext Settings", "naming_rule", None)
		frappe.db.set_value("DocType", "NetraNext Settings", "allow_import", 0)
		frappe.db.set_value("DocType", "NetraNext Settings", "allow_rename", 0)
		frappe.db.set_value("DocType", "NetraNext Settings", "title_field", None)

		# Update field definition to remove unique constraint from tenant_name
		frappe.db.sql("""
			UPDATE `tabDocField`
			SET `unique` = 0
			WHERE `parent` = 'NetraNext Settings'
			AND `fieldname` = 'tenant_name'
		""")

		# Update permissions to remove create and delete
		frappe.db.sql("""
			UPDATE `tabDocPerm`
			SET `create` = 0, `delete` = 0
			WHERE `parent` = 'NetraNext Settings'
		""")

		frappe.msgprint("NetraNext Settings has been converted to a Single DocType.")

	# Clear cache to ensure changes take effect
	frappe.clear_cache()

	# Verify the conversion
	if frappe.get_meta("NetraNext Settings").issingle:
		frappe.msgprint("NetraNext Settings successfully converted to Single DocType!")
	else:
		frappe.msgprint("Warning: NetraNext Settings conversion may not have completed properly.")
