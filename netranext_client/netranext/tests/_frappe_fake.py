"""Minimal in-memory Frappe double for attendance-tracking unit tests.

Implements just enough of the Frappe API surface used by
netranext_client.netranext.apis.v1.attendance_tracking (and the journey
doctype module) to exercise the state machine end-to-end without a bench:

- frappe.db.get_value / get_all / exists / set_value over an in-memory store
- frappe.get_doc(dict | doctype, name) with insert()/save()/set()
- frappe.get_single + db.get_single_value over a settings dict
- a controllable clock for now_datetime()/nowdate()
"""
import re
from datetime import datetime, timedelta


def parse_dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip().replace("T", " ")
    if text.endswith("Z"):
        text = text[:-1]
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:26] if "." in text else text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


class FakeDoc(dict):
    def __init__(self, store, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._store = store

    @property
    def name(self):
        return self.get("name")

    @name.setter
    def name(self, value):
        self["name"] = value

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError:
            return None

    def __setattr__(self, item, value):
        # Mirror frappe Document semantics: non-private attribute writes are
        # doctype fields, so they must live in the dict (what _touch persists).
        if item.startswith("_"):
            super().__setattr__(item, value)
        else:
            self[item] = value

    def set(self, field, value):
        self[field] = value

    def get(self, field, default=None):
        return super().get(field, default)

    def as_dict(self):
        return dict(self)

    def _autoname(self, doctype):
        prefix = {
            "NetraNext Attendance Trip Session": "ATS",
            "NetraNext Trip Odometer Requirement": "ODO-REQ",
            "NetraNext Trip Odometer Evidence": "ODO-EVD",
            "NetraNext Attendance Trip Event": "ATE",
            "NetraNext Journey": "JOURNEY",
        }.get(doctype, "DOC")
        return f"{prefix}-{len(self._store.get(doctype)) + 1:05d}"

    def insert(self, ignore_permissions=False):
        doctype = self["doctype"]
        if not self.name:
            self.name = self._autoname(doctype)
        self.setdefault("owner", "Administrator")
        self._store._touch(doctype, self)
        return self

    def save(self, ignore_permissions=False):
        self._store._touch(self["doctype"], self)
        return self


class AttrDict(dict):
    """frappe._dict stand-in: dict rows that also allow attribute access."""

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError:
            return None


def _matches(row, filters):
    if isinstance(filters, (str, int)):
        return row.get("name") == filters
    for field, expected in (filters or {}).items():
        actual = row.get(field)
        if isinstance(expected, (list, tuple)) and expected and expected[0] == "in":
            if actual not in expected[1]:
                return False
        elif isinstance(expected, (list, tuple)) and expected and expected[0] == "<=":
            if actual is None or parse_dt(actual) > parse_dt(expected[1]):
                return False
        elif actual != expected:
            return False
    return True


class FakeDB:
    def __init__(self, store):
        self._store = store

    def get_single_value(self, doctype, field):
        return self._store.settings.get(field)

    def get_value(self, doctype, filters=None, field=None, as_dict=False,
                  order_by=None):
        rows = [row for row in self._store.get(doctype) if _matches(row, filters)]
        if not rows:
            return None
        if order_by and "desc" in order_by:
            rows = list(reversed(rows))
        row = rows[0]
        if isinstance(field, (list, tuple)):
            if as_dict:
                return AttrDict({f: row.get(f) for f in field})
            return tuple(row.get(f) for f in field)
        return row.get(field)

    def get_all(self, doctype, filters=None, fields=None, pluck=None,
                order_by=None, ignore_permissions=False, **kwargs):
        rows = [row for row in self._store.get(doctype) if _matches(row, filters)]
        if order_by and "desc" in order_by:
            rows = list(reversed(rows))
        if pluck:
            return [row.get(pluck) for row in rows]
        if fields:
            return [AttrDict({f: row.get(f) for f in fields}) for row in rows]
        return [AttrDict(row) for row in rows]

    def exists(self, doctype, filters=None):
        return bool(self.get_value(doctype, filters, "name"))

    def set_value(self, doctype, target, *args):
        # frappe supports both set_value(dt, name, {fields}) and the legacy
        # set_value(dt, name, field, value) 4-arg form.
        if len(args) == 2:
            values = {args[0]: args[1]}
        else:
            values = args[0]
        if isinstance(target, dict):
            rows = [row for row in self._store.get(doctype) if _matches(row, target)]
        else:
            rows = [row for row in self._store.get(doctype)
                    if row.get("name") == target]
        for row in rows:
            row.update(values)
        return rows

    def has_column(self, doctype, field):
        return True

    def commit(self):
        pass


class FakeStore:
    def __init__(self, settings=None, clock=None):
        self.tables = {}
        self.settings = dict(settings or {})
        self.clock = clock or datetime(2026, 11, 2, 9, 0, 0)
        self.db = FakeDB(self)

    def get(self, doctype):
        return self.tables.setdefault(doctype, [])

    def _touch(self, doctype, doc):
        table = self.get(doctype)
        existing = next((r for r in table if r.get("name") == doc.name), None)
        if existing is None:
            table.append(dict(doc))
        else:
            existing.update(dict(doc))


class FakeFrappe:
    """Attributes double as module-level functions of the frappe package."""

    def __init__(self, store):
        self._store = store
        self.db = store.db
        self.local = None
        self.flags = {}
        self.session = type("Session", (), {"user": "Administrator"})()
        self.whitelist_calls = []

        frappe_self = self

        def whitelist(allow_guest=False, **kwargs):
            def decorator(fn):
                frappe_self.whitelist_calls.append(getattr(fn, "__name__", str(fn)))
                return fn
            return decorator

        self.whitelist = whitelist

    # -- document accessors --------------------------------------------------
    def get_doc(self, *args):
        if len(args) == 1 and isinstance(args[0], dict):
            return FakeDoc(self._store, args[0])
        doctype, name = args
        row = next((r for r in self._store.get(doctype)
                    if r.get("name") == name), None)
        if row is None:
            raise Exception(f"{doctype} {name} not found")
        doc = FakeDoc(self._store, row)
        doc["doctype"] = doctype
        return doc

    def get_single(self, doctype):
        doc = FakeDoc(self._store, {"doctype": doctype,
                                    "name": doctype,
                                    **self._store.settings})
        return doc

    def new_doc(self, doctype):
        return FakeDoc(self._store, {"doctype": doctype})

    def get_all(self, doctype, **kwargs):
        return self._store.db.get_all(doctype, **kwargs)

    def throw(self, message, *args, **kwargs):
        raise Exception(message)

    def log_error(self, *args, **kwargs):
        pass

    def get_traceback(self):
        return ""

    def msgprint(self, *args, **kwargs):
        pass

    def cache(self):
        return _NoopCache()

    def get_request_header(self, name, default=None):
        return default


class _NoopCache:
    def get_value(self, *a, **k):
        return None

    def set_value(self, *a, **k):
        pass

    def delete_value(self, *a, **k):
        pass


class FakeUtils:
    """frappe.utils functions used by the modules under test."""

    flt = staticmethod(lambda value, precision=None: float(value or 0))

    @staticmethod
    def get_datetime(value):
        return parse_dt(value)

    @staticmethod
    def now_datetime():
        return FakeUtils._clock[0]

    @staticmethod
    def nowdate():
        return FakeUtils._clock[0].strftime("%Y-%m-%d")

    @staticmethod
    def get_system_timezone():
        return "UTC"

    @staticmethod
    def getdate(value):
        parsed = parse_dt(value)
        return parsed.date() if parsed else FakeUtils._clock[0].date()

    @staticmethod
    def today():
        return FakeUtils.nowdate()

    @staticmethod
    def strip_html(text):
        return re.sub(r"<[^>]+>", "", str(text or ""))

    _clock = [datetime(2026, 11, 2, 9, 0, 0)]


def advance_clock(hours=0, minutes=0):
    FakeUtils._clock[0] = FakeUtils._clock[0] + timedelta(
        hours=hours, minutes=minutes)


def set_clock(dt):
    FakeUtils._clock[0] = dt


def build_fake(settings=None, clock=None):
    store = FakeStore(settings=settings, clock=clock)
    if clock:
        set_clock(clock)
    frappe = FakeFrappe(store)
    return frappe, FakeUtils, store
