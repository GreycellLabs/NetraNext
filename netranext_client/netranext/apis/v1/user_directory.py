"""Versioned Service-to-Client User directory, independent of HR/attendance APIs."""
import hmac
import logging
import traceback
from pathlib import PurePath
from uuid import uuid4

import frappe
from netranext_client import __version__

PROTOCOL_VERSION = 1
logger = logging.getLogger(__name__)


def _error(code, message, status=400, reference=None):
    frappe.local.response['http_status_code'] = status
    result = {'status': 'error', 'error_code': code, 'message': message, 'status_code': status}
    if reference:
        result['reference'] = reference
    return result


@frappe.whitelist(allow_guest=True, methods=['POST'])
def get_mobile_user_candidates(search=None, limit=200, offset=0):
    """Authenticate the integration and site identity before reading any Users.

    NetraNext Settings.tenant_id is established by the existing Service handshake;
    never infer or rewrite it from the incoming request.
    """
    if not getattr(frappe.local, 'request', None):
        return _error('AUTHENTICATION_ERROR', 'An authenticated integration request is required.', 401)
    incoming = frappe.get_request_header('X-NetraNext-Token') or ''
    if not incoming:
        return _error('AUTHENTICATION_ERROR', 'Missing Integration Token.', 401)
    try:
        settings = frappe.get_single('NetraNext Settings')
        stored = settings.get_password('api_key', raise_exception=False) or ''
        if not stored or not hmac.compare_digest(str(incoming).encode(), str(stored).encode()):
            return _error('AUTHENTICATION_ERROR', 'Invalid Integration Token', 401)
        configured_tenant = (settings.tenant_id or '').strip()
        if not configured_tenant:
            return _error('TENANT_IDENTITY_NOT_CONFIGURED',
                          'Complete the Client Settings connection handshake with the Service.', 409)
        if (frappe.get_request_header('X-Tenant-ID') or '').strip() != configured_tenant:
            return _error('TENANT_IDENTITY_MISMATCH', 'The requested tenant does not match this Client site.', 403)
        try:
            limit, offset = int(limit), int(offset)
            if not 1 <= limit <= 200 or offset < 0:
                raise ValueError
        except (ValueError, TypeError):
            return _error('VALIDATION_ERROR', 'Use limit 1–200 and a nonnegative offset.')
        needle = str(search or '').strip()
        if len(needle) > 320:
            return _error('VALIDATION_ERROR', 'Search is too long.')
        or_filters = None
        if needle:
            or_filters = [['User', field, 'like', f'%{needle}%']
                          for field in ('name', 'full_name', 'email')]
        users = frappe.get_all('User',
            filters={'enabled': 1, 'name': ['not in', ['Administrator', 'Guest']]},
            or_filters=or_filters, fields=['name', 'email', 'full_name', 'enabled', 'user_type'],
            order_by='name asc', limit_start=offset, limit_page_length=limit)
        return {'status': 'success', 'message': 'Tenant users', 'data': {
            'protocol_version': PROTOCOL_VERSION, 'client_version': __version__,
            'tenant_id': configured_tenant,
            'users': [{'user': user['name'], 'email': user.get('email'),
                       'full_name': user.get('full_name'), 'enabled': bool(user.get('enabled')),
                       'user_type': user.get('user_type')} for user in users],
            'offset': offset, 'limit': limit, 'count': len(users)}}
    except Exception as error:
        reference = uuid4().hex
        # Preserve diagnostic locations and type, never exception values, SQL,
        # request headers, user identities, or traceback locals.
        frames = [{'file': PurePath(frame.filename).name, 'line': frame.lineno,
                   'function': frame.name} for frame in traceback.extract_tb(error.__traceback__)]
        logger.error('tenant_directory_failure reference=%s exception_type=%s frames=%s',
                     reference, type(error).__name__, frames)
        return _error('TENANT_DIRECTORY_QUERY_FAILED', 'The Client user directory query failed.', 500, reference)
