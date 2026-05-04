"""
New thin entry point.
After verifying this works, rename app_new.py → app.py.
"""
from werkzeug.routing import BaseConverter as _BaseConverter
from werkzeug.routing import ValidationError as _RoutingValidationError
from extensions import app, supabase          # noqa: F401 – re-export for gunicorn

# ----- URL converters (must be registered before routes) -----
from core.helpers import (
    _decode_school_ref, _encode_school_ref,
    _decode_signed_id, _encode_signed_id,
)


class _SchoolRefConverter(_BaseConverter):
    regex = r"[^/]+"

    def to_python(self, value):
        result = _decode_school_ref(value)
        if result is None:
            raise _RoutingValidationError()
        return result

    def to_url(self, value):
        encoded = _encode_school_ref(value)
        return encoded if encoded else str(value)


class _SignedIdConverter(_BaseConverter):
    regex = r"[^/]+"

    def to_python(self, value):
        result = _decode_signed_id(value)
        if result is None:
            raise _RoutingValidationError()
        return result

    def to_url(self, value):
        encoded = _encode_signed_id(value)
        return encoded if encoded else str(value)


app.url_map.converters["school_ref"] = _SchoolRefConverter
app.url_map.converters["signed_id"] = _SignedIdConverter

# ----- httpx error handler (optional) -----
try:
    import httpx as _httpx

    @app.errorhandler(_httpx.ReadError)
    def handle_httpx_read_error(exc):
        from flask import request as _req, redirect, url_for, flash, jsonify
        app.logger.warning("Transient network read error: %s", exc)
        if _req.path.startswith("/api/") or _req.path.startswith("/ai/"):
            return jsonify({"error": "Network read error. Please retry."}), 502
        flash("Network error while contacting an external service. Please try again.", "error")
        return redirect(_req.referrer or url_for("home"))
except ImportError:
    pass

# ----- register all route modules -----
import routes.public
import routes.admin_global
import routes.school
import routes.auth
import routes.school_admin
import routes.dashboards
import routes.classroom
import routes.portal
import routes.apply
import routes.ai
import routes.api

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7000, debug=True)
