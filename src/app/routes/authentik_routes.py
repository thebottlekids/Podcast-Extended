from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from flask import Blueprint, Response, current_app, jsonify, request, session

from app.auth.authentik_service import (
    AuthentikAuthError,
    NoAdminUserError,
    build_authorization_url,
    exchange_code_for_token,
    generate_oauth_state,
    generate_pkce_pair,
    get_admin_user,
    get_userinfo,
)

if TYPE_CHECKING:
    from app.auth.authentik_settings import AuthentikSettings

logger = logging.getLogger("global_logger")

authentik_bp = Blueprint("authentik", __name__)

SESSION_OAUTH_STATE_KEY = "authentik_oauth_state"
SESSION_PKCE_VERIFIER_KEY = "authentik_pkce_verifier"
SESSION_USER_KEY = "user_id"


def _get_authentik_settings() -> "AuthentikSettings | None":
    return current_app.config.get("AUTHENTIK_SETTINGS")


@authentik_bp.route("/api/auth/authentik/status", methods=["GET"])
def authentik_status() -> Response:
    """Return whether Authentik SSO is enabled."""
    settings = _get_authentik_settings()
    return jsonify({"enabled": bool(settings and settings.enabled)})


@authentik_bp.route("/api/auth/authentik/login", methods=["GET"])
def authentik_login() -> Response | tuple[Response, int]:
    """Start the Authentik OIDC flow by returning the authorization URL."""
    settings = _get_authentik_settings()
    if not settings or not settings.enabled:
        return jsonify({"error": "Authentik SSO is not configured."}), 404

    state = generate_oauth_state()
    pkce = generate_pkce_pair()
    session[SESSION_OAUTH_STATE_KEY] = state
    session[SESSION_PKCE_VERIFIER_KEY] = pkce.verifier

    auth_url = build_authorization_url(settings, state, pkce.challenge)
    return jsonify({"authorization_url": auth_url})


@authentik_bp.route("/api/auth/authentik/callback", methods=["GET"])
def authentik_callback() -> Response:
    """Handle the OIDC callback from Authentik."""
    settings = _get_authentik_settings()
    if not settings or not settings.enabled:
        return Response(
            response="",
            status=302,
            headers={"Location": "/?error=authentik_not_configured"},
        )

    # Verify state to prevent CSRF
    state = request.args.get("state")
    expected_state = session.pop(SESSION_OAUTH_STATE_KEY, None)
    code_verifier = session.pop(SESSION_PKCE_VERIFIER_KEY, None)
    if not state or state != expected_state or not code_verifier:
        return Response(
            response="", status=302, headers={"Location": "/?error=invalid_state"}
        )

    error = request.args.get("error")
    if error:
        return Response(
            response="", status=302, headers={"Location": f"/?error={error}"}
        )

    code = request.args.get("code")
    if not code:
        return Response(
            response="", status=302, headers={"Location": "/?error=missing_code"}
        )

    try:
        token_data = exchange_code_for_token(settings, code, code_verifier)
        access_token = token_data["access_token"]

        userinfo = get_userinfo(settings, access_token)
        user = get_admin_user()

        session.clear()
        session[SESSION_USER_KEY] = user.id
        session.permanent = True

        logger.info(
            "Authentik SSO login successful for admin user %s (authentik sub=%s, "
            "email=%s)",
            user.username,
            userinfo.get("sub"),
            userinfo.get("email"),
        )
        return Response(response="", status=302, headers={"Location": "/"})

    except NoAdminUserError:
        logger.error("Authentik SSO login succeeded but no local admin user exists")
        return Response(
            response="", status=302, headers={"Location": "/?error=no_admin_user"}
        )
    except AuthentikAuthError as e:
        logger.warning("Authentik auth error: %s", e)
        return Response(
            response="", status=302, headers={"Location": "/?error=auth_failed"}
        )
    except Exception as e:  # pylint: disable=broad-except
        logger.exception("Authentik auth failed unexpectedly: %s", e)
        return Response(
            response="", status=302, headers={"Location": "/?error=auth_failed"}
        )
