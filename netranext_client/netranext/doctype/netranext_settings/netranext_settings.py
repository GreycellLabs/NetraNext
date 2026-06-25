# Copyright (c) 2024, NetraNext and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
import requests
import json
from datetime import datetime
from netranext_client.constants import DEFAULT_CENTRAL_SERVER_URL


class NetraNextSettings(Document):
    def validate(self):
        """Validate settings before saving"""
        if not self.central_server_url:
            self.central_server_url = DEFAULT_CENTRAL_SERVER_URL
        self.validate_connection_details()
        self.prevent_central_server_url_change()
        self.make_business_logo_public()

    def make_business_logo_public(self):
        """Ensure the business logo is public so the mobile app can load it without credentials"""
        if self.business_logo and "/private/" in self.business_logo:
            file_docs = frappe.get_all("File", filters={"file_url": self.business_logo}, limit=1)
            if file_docs:
                try:
                    file_doc = frappe.get_doc("File", file_docs[0].name)
                    if file_doc.is_private:
                        file_doc.is_private = 0
                        file_doc.save(ignore_permissions=True)
                        self.business_logo = file_doc.file_url
                except Exception as e:
                    frappe.log_error(f"Failed to make business logo public: {str(e)}")

    def validate_connection_details(self):
        if not self.api_key:
            frappe.throw(_("API Key is required"))

        if not self.central_server_url:
            frappe.throw(_("Central Server URL is required"))

    def prevent_central_server_url_change(self):
        # Prevent editing Central Server URL once it has been saved
        db_val = frappe.db.get_single_value("NetraNext Settings", "central_server_url")
        if db_val and self.central_server_url != db_val:
            frappe.throw(_("Central Server URL is fixed and cannot be modified once set."))

    def test_connection(self):
        """Test connection to central NetraNext server"""
        try:
            if not self.central_server_url:
                self.central_server_url = DEFAULT_CENTRAL_SERVER_URL
            url = f"{self.central_server_url.rstrip('/')}/api/method/netranext.apis.v1.tenant_onboarding.activate_tenant_from_client"
            headers = {
                "X-NetraNext-Token": self.get_password("api_key")
            }

            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                try:
                    res_json = response.json()
                    msg = res_json.get("message", {})
                    if msg.get("status") == "success":
                        data = msg.get("data", {})
                        
                        self.db_set("connection_status", "Connected")
                        if data.get("tenant_id"):
                            self.db_set("tenant_id", data.get("tenant_id"))
                        if data.get("status"):
                            self.db_set("status", data.get("status"))
                        if data.get("tenant_name"):
                            self.db_set("tenant_name", data.get("tenant_name"))
                            
                        frappe.db.commit()
                        frappe.msgprint(_("Connection successful!"))
                        return True
                    else:
                        err = msg.get("message", "Unknown error from server")
                        self.db_set("connection_status", "Error")
                        frappe.db.commit()
                        
                        if "invalid" in err.lower() or "expired" in err.lower() or "token" in err.lower():
                            frappe.throw(_("Wrong API Key. Please contact support."))
                        else:
                            frappe.throw(_("{0}. Please contact support.").format(err))
                except ValueError:
                    self.db_set("connection_status", "Error")
                    frappe.db.commit()
                    frappe.throw(_("Connection failed: Invalid response format from server"))
            else:
                self.db_set("connection_status", "Error")
                frappe.db.commit()
                frappe.throw(_("Connection failed with HTTP status code: {0}").format(response.status_code))

        except requests.RequestException as e:
            self.db_set("connection_status", "Disconnected")
            frappe.db.commit()
            frappe.throw(_("Connection failed: {0}").format(str(e)))

    @frappe.whitelist()
    def sync_now(self):
        """Manually trigger sync with central server"""
        try:
            from netranext_client.netranext.utils.sync_helper import manual_sync
            return manual_sync()
        except ImportError:
            frappe.msgprint(_("Sync functionality not yet implemented"))
            return None

    def get_api_credentials(self):
        """Get API credentials for making requests"""
        return {
            "integration_token": self.get_password("api_key"),
            "central_server_url": self.central_server_url
        }

    def reveal_api_key(self):
        """Reveal the integration token (decrypted api_key)"""
        if "System Manager" not in frappe.get_roles():
            frappe.throw(_("Not authorized to reveal integration token"))
        return self.get_password("api_key")

    def validate_business_logo(self):
        if not self.business_logo:
            return

        # Check if logo has changed
        old_logo = frappe.db.get_single_value("NetraNext Settings", "business_logo")
        if self.business_logo == old_logo:
            return

        # Find the File document matching this file URL
        file_docs = frappe.get_all(
            "File",
            filters={"file_url": self.business_logo},
            fields=["name", "file_name", "file_size"],
            order_by="creation desc",
            limit=1
        )
        if not file_docs:
            self.business_logo = None
            frappe.throw(
                _(
                    "The attached logo file does not exist or was deleted because it failed validation. "
                    "Please upload a valid PNG, SVG, or WebP logo."
                )
            )

        file_info = file_docs[0]
        
        try:
            file_doc = frappe.get_doc("File", file_info.name)
            file_content = file_doc.get_content()
        except Exception as e:
            frappe.throw(_("Failed to load business logo file: {0}").format(str(e)))

        if not file_content:
            try:
                frappe.delete_doc("File", file_info.name, ignore_permissions=True, force=True)
                frappe.db.commit()
            except Exception:
                pass
            self.business_logo = None
            frappe.throw(_("The uploaded business logo is empty."))

        # 1. Size Validation (Max 512 KB)
        file_size = file_info.file_size or len(file_content)
        if file_size > 512 * 1024:
            try:
                frappe.delete_doc("File", file_info.name, ignore_permissions=True, force=True)
                frappe.db.commit()
            except Exception:
                pass
            self.business_logo = None
            frappe.throw(
                _("Logo file size must be less than 512 KB. Uploaded size: {0:.1f} KB.")
                .format(file_size / 1024.0)
            )

        # 2. Format Validation
        original_filename = file_info.file_name or ""
        file_ext = original_filename.split(".")[-1].lower() if "." in original_filename else ""

        if file_ext not in ("png", "svg", "webp"):
            try:
                frappe.delete_doc("File", file_info.name, ignore_permissions=True, force=True)
                frappe.db.commit()
            except Exception:
                pass
            self.business_logo = None
            frappe.throw(
                _(
                    "Only PNG, SVG, and WebP formats are allowed for the business logo. "
                    "JPEGs and other formats do not support transparent backgrounds."
                )
            )

        # 3. Dimensions & Transparency (only for PNG and WebP)
        if file_ext in ("png", "webp"):
            from PIL import Image
            import io

            try:
                img = Image.open(io.BytesIO(file_content))
                width, height = img.size

                # Dimensions Check
                if width > 1024 or height > 1024:
                    try:
                        frappe.delete_doc("File", file_info.name, ignore_permissions=True, force=True)
                        frappe.db.commit()
                    except Exception:
                        pass
                    self.business_logo = None
                    frappe.throw(
                        _("Logo dimensions cannot exceed 1024x1024 pixels. Uploaded image is {0}x{1} pixels.")
                        .format(width, height)
                    )
                if width < 128 or height < 128:
                    try:
                        frappe.delete_doc("File", file_info.name, ignore_permissions=True, force=True)
                        frappe.db.commit()
                    except Exception:
                        pass
                    self.business_logo = None
                    frappe.throw(
                        _("Logo dimensions must be at least 128x128 pixels. Uploaded image is {0}x{1} pixels.")
                        .format(width, height)
                    )

                # Transparency Check
                has_transparency = False
                if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                    alpha = img.convert("RGBA").split()[-1]
                    min_alpha, max_alpha = alpha.getextrema()
                    if min_alpha < 255:
                        has_transparency = True

                if not has_transparency:
                    try:
                        frappe.delete_doc("File", file_info.name, ignore_permissions=True, force=True)
                        frappe.db.commit()
                    except Exception:
                        pass
                    self.business_logo = None
                    frappe.throw(
                        _(
                            "The logo must have a transparent background. "
                            "Please upload a PNG or WebP with transparency support."
                        )
                    )

            except frappe.ValidationError:
                raise
            except Exception as e:
                try:
                    frappe.delete_doc("File", file_info.name, ignore_permissions=True, force=True)
                    frappe.db.commit()
                except Exception:
                    pass
                self.business_logo = None
                frappe.throw(_("Failed to process logo image: {0}").format(str(e)))

    def on_update(self):
        """Sync status changes to orchestrator if status has changed"""
        if self.has_value_changed("status"):
            self.sync_status_to_orchestrator()

    def sync_status_to_orchestrator(self):
        """Send status update payload to Central Orchestrator"""
        if not self.central_server_url or not self.api_key:
            return

        import requests
        try:
            url = f"{self.central_server_url.rstrip('/')}/api/method/netranext.apis.v1.tenant_onboarding.update_tenant_status_from_client"
            headers = {
                "X-NetraNext-Token": self.get_password("api_key"),
                "Content-Type": "application/json"
            }
            payload = {
                "status": self.status
            }
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            if response.status_code != 200:
                frappe.logger().warning(
                    f"Failed to sync status change to orchestrator. HTTP Status: {response.status_code}"
                )
        except Exception as e:
            frappe.logger().warning(
                f"Failed to sync status change to orchestrator: {str(e)}"
            )


@frappe.whitelist()
def test_connection():
    """Global endpoint to test connection without passing document from client"""
    settings = frappe.get_single("NetraNext Settings")
    return settings.test_connection()


@frappe.whitelist()
def reveal_api_key():
    """Global endpoint to reveal API key without passing document from client"""
    settings = frappe.get_single("NetraNext Settings")
    return settings.reveal_api_key()


@frappe.whitelist()
def validate_uploaded_logo(file_url):
    return {"status": "success"}