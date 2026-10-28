"""Undo the former install/migrate routine's persisted NetraNext landing defaults.

One-time data repair, not a login hook: users may subsequently choose any workspace
using native Frappe settings. The migration transaction owns the database commit.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import frappe


def _backup(rows):
    directory = Path(frappe.get_site_path('private', 'backups'))
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f'web-login-workspace-defaults-{uuid4().hex}.json'
    payload = {'schema_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
               'doctype': 'User', 'field': 'default_workspace', 'rows': rows}
    content = json.dumps(payload, indent=2, sort_keys=True).encode('utf-8')
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    saved = path.read_bytes()
    if hashlib.sha256(saved).digest() != hashlib.sha256(content).digest() or json.loads(saved) != payload:
        raise RuntimeError('Web-login workspace backup verification failed; user defaults were not changed.')
    return path


def execute():
    # Legacy setup applied this value to enabled System Users (including the
    # Administrator). Disabled former System Users can still carry it as well.
    # Lock matching rows so a concurrently edited preference is not overwritten.
    rows = frappe.db.sql('''
        select name, default_workspace from `tabUser`
        where user_type = %s and default_workspace = %s and name != %s
        order by name for update
    ''', ('System User', 'NetraNext', 'Guest'), as_dict=True)
    if not rows:
        return
    archive = _backup([dict(row) for row in rows])
    for row in rows:
        # Avoid User.save side effects; change only the legacy navigation value.
        frappe.db.set_value('User', row['name'], 'default_workspace', None, update_modified=False)
        frappe.clear_cache(user=row['name'])
    frappe.logger('netranext_client').info(
        'Cleared %s legacy NetraNext default workspaces; private backup: %s', len(rows), archive.name)
