"""
One-time Quick Login URL API for the tenant bench.

Flow:
1. The central server (authenticated via the integration token) calls
   create_quick_login_token() when an employee taps a mapped Quick Link in
   the mobile app. A random 256-bit token bound to ONE user + ONE redirect
   destination is cached in Redis for a short TTL.
2. The mobile app opens the returned URL in the browser. The browser hits
   redeem_quick_login_token() as a guest: the token is consumed
   (single-use), the employee's tenant session is established via
   LoginManager (cookies are set on the response), and the browser is
   302-redirected straight to the destination page — no login screen.

Security:
- Tokens are single-use and expire quickly (default 300s).
- Generation requires the X-NetraNext-Token integration header.
- The redirect target is restricted to THIS tenant site (relative path or
  same-host absolute URL) so the endpoint can never be abused as an open
  redirect; external quick links are never sent here by the central server.
- Every generation / redemption is logged with the requesting IP.
"""
import secrets
from urllib.parse import urlparse

import frappe
from frappe.utils import get_url

from netranext_client.netranext.utils.response_formatter import create_success_response, create_error_response
from netranext_client.netranext.utils.logger import tenant_bench_logger
from netranext_client.netranext.utils.error_handler import (
	handle_api_exception,
	AuthenticationException,
	ValidationException,
	ResourceNotFoundException,
)
from netranext_client.netranext.apis.v1.sync import validate_sync_request

TOKEN_TTL_SECONDS = 300
CACHE_PREFIX = "quick_login_token:"


def _tenant_hostname():
	return (urlparse(get_url()).hostname or "").lower()


def _normalize_destination(destination_url):
	"""
	Reduce the quick link destination to a RELATIVE path on this site.

	Returns "/app/some-page?x=1" for same-host absolute URLs and for paths
	that were already relative. Raises ValidationException for anything that
	points off-site (open-redirect guard) or is not a usable URL.
	"""
	if not destination_url or not str(destination_url).strip():
		raise ValidationException("destination_url is required")

	dest = str(destination_url).strip()
	parsed = urlparse(dest)

	if parsed.scheme in ("http", "https"):
		dest_host = (parsed.hostname or "").lower()
		site_host = _tenant_hostname()
		if not site_host or dest_host != site_host:
			raise ValidationException(
				"Destination URL does not belong to this tenant site. "
				"External links must be opened directly, without a quick login token."
			)
		path = parsed.path or "/"
		if parsed.query:
			path += f"?{parsed.query}"
		return path

	if dest.startswith("/") and not dest.startswith("//"):
		return dest

	raise ValidationException("Destination must be a site-relative path or an absolute URL of this tenant site")


@frappe.whitelist(allow_guest=True)
def create_quick_login_token(user_id=None, employee_id=None, destination_url=None):
	"""
	Mint a temporary, single-use quick login token for ONE employee and ONE
	destination page. Called only by the central server (integration token
	required) when an employee taps a mapped Quick Link in the mobile app.

	Args:
		user_id: The tenant User (email/name) the token will log in
		employee_id: Employee the quick link belongs to (must be linked to user_id)
		destination_url: Quick link destination (site-relative path or same-host URL)

	Returns:
		dict: {url, token, expires_in_seconds, redirect}
	"""
	try:
		validate_sync_request()

		if not user_id or not destination_url:
			raise ValidationException("user_id and destination_url are required")

		user = frappe.db.get_value("User", {"name": user_id}, ["name", "enabled"], as_dict=True)
		if not user:
			raise ResourceNotFoundException(f"User {user_id}")
		if not user.enabled:
			raise ValidationException(f"User {user_id} is disabled")

		# The employee the mobile app claims must be linked to this user.
		employee = None
		if employee_id:
			employee = frappe.db.get_value("Employee", employee_id, ["name", "user_id", "status"], as_dict=True)
			if not employee:
				raise ResourceNotFoundException(f"Employee {employee_id}")
			if employee.status != "Active":
				raise ValidationException(f"Employee {employee_id} is not active")
			if not employee.user_id or employee.user_id.lower() != str(user.name).lower():
				raise AuthenticationException(
					f"Employee {employee_id} is not linked to user {user.name}"
				)

		redirect_path = _normalize_destination(destination_url)

		token = secrets.token_urlsafe(32)
		cache_key = f"{CACHE_PREFIX}{token}"
		frappe.cache().set_value(cache_key, {
			"user": user.name,
			"employee": employee.name if employee else None,
			"redirect": redirect_path,
		}, expires_in_sec=TOKEN_TTL_SECONDS)

		quick_login_url = (
			f"{get_url()}"
			f"/api/method/netranext_client.netranext.apis.v1.quick_login.redeem_quick_login_token"
			f"?token={token}"
		)

		tenant_bench_logger.info(
			f"Quick login token created: user={user.name}, employee={employee_id}, "
			f"redirect={redirect_path}, ttl={TOKEN_TTL_SECONDS}s",
			"QUICK_LOGIN",
		)

		return create_success_response("Quick login URL generated successfully", {
			"url": quick_login_url,
			"token": token,
			"expires_in_seconds": TOKEN_TTL_SECONDS,
			"redirect": redirect_path,
		})

	except Exception as e:
		return handle_api_exception(e, "QUICK_LOGIN")


@frappe.whitelist(allow_guest=True)
def redeem_quick_login_token(token=None):
	"""
	Browser endpoint: consume a single-use quick login token, log the
	employee into their tenant account (session cookies are set on this
	response), and 302-redirect to the destination page. No login screen is
	shown. Invalid / expired / already-used tokens render an error page.
	"""
	if not token and frappe.form_dict:
		token = frappe.form_dict.get("token")

	if not token:
		frappe.respond_as_web_page(
			"Invalid Quick Link",
			"No login token was provided in the link.",
			http_status_code=400,
		)
		return

	cache_key = f"{CACHE_PREFIX}{token}"
	payload = frappe.cache().get_value(cache_key)

	if not payload or not isinstance(payload, dict):
		frappe.respond_as_web_page(
			"Quick Link Expired",
			"This login link is invalid, has expired, or has already been used.",
			http_status_code=403,
		)
		return

	# Consume immediately — single-use enforcement.
	frappe.cache().delete_value(cache_key)

	user = payload.get("user")
	redirect_to = payload.get("redirect") or "/app"

	if not user or not frappe.db.exists("User", user) or not frappe.db.get_value("User", user, "enabled"):
		frappe.respond_as_web_page(
			"User Not Available",
			f"The user account associated with this link could not be found or is disabled.",
			http_status_code=404,
		)
		return

	# The redirect was validated at token-creation time, but re-check now so
	# a config change (site URL) can never turn old tokens into open redirects.
	try:
		redirect_to = _normalize_destination(redirect_to)
	except Exception:
		frappe.respond_as_web_page(
			"Invalid Redirect",
			"The destination of this link is no longer valid.",
			http_status_code=400,
		)
		return

	request_ip = ""
	try:
		request_ip = (frappe.request.environ or {}).get("REMOTE_ADDR", "")
	except Exception:
		pass

	# Establish the tenant session so the browser receives its cookies, then
	# redirect — the destination page loads already authenticated.
	from frappe.auth import LoginManager

	try:
		login_mgr = LoginManager()
		login_mgr.login_as(user)
		login_mgr.set_user_info(resume=True)
	except Exception as e:
		tenant_bench_logger.error(
			f"Quick login session creation failed for {user}: {e}", "QUICK_LOGIN"
		)
		frappe.respond_as_web_page(
			"Login Failed",
			"Could not establish your session. Please try opening the link again.",
			http_status_code=500,
		)
		return

	tenant_bench_logger.info(
		f"Quick login redeemed: user={user}, employee={payload.get('employee')}, "
		f"redirect={redirect_to}, ip={request_ip}",
		"QUICK_LOGIN",
	)

	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = redirect_to
