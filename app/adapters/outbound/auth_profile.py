"""The client for auth-profile-service's internal user directory.

Modeled on order-service's `HttpCatalogGateway` (`app/adapters/outbound/catalog.py` there):
same short-lived symmetric-JWT service token, same fail-soft posture for a synchronous
cross-service call. The one difference is what "failure" means here. Order-service's call
sits in front of a purchase and has to fail the purchase if the catalog cannot be reached.
This call sits in front of a notification fan-out: the festival itself has already started
by the time this runs (see `FestivalService.start`), so a directory lookup that fails should
not undo that — it should log loudly and let the event go out with an empty audience,
which is exactly the gap this used to be silently stuck in.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx
import jwt

logger = logging.getLogger(__name__)


class HttpAuthProfileDirectory:
    """Talks to auth-profile-service's internal `/v1/admin/users/ids` route."""

    def __init__(
        self,
        *,
        base_url: str,
        jwt_secret: str,
        jwt_algorithm: str = "HS256",
        jwt_issuer: str = "",
        jwt_audience: str = "",
        service_name: str = "festival-service",
        timeout: float = 3.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._jwt_secret = jwt_secret
        self._jwt_algorithm = jwt_algorithm
        self._jwt_issuer = jwt_issuer
        self._jwt_audience = jwt_audience
        self._service_name = service_name
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _service_token(self) -> str:
        """Mint a short-lived token for this service.

        `role: SUPPORT` is the narrowest role the target route accepts — the same route
        SUPPORT/ADMIN humans use to list the user directory (see
        `auth-profile-service/app/presentation/rest/role_admin_controller.py`). Symmetric
        signing is only safe because the platform's JWT secret is shared; any service that
        can verify a token can also mint one.
        """
        now = datetime.now(UTC)
        claims: dict[str, object] = {
            "sub": self._service_name,
            "role": "SUPPORT",
            "typ": "access",
            "scopes": ["users:read"],
            "iat": now,
            "exp": now + timedelta(minutes=2),
        }
        if self._jwt_issuer:
            claims["iss"] = self._jwt_issuer
        if self._jwt_audience:
            claims["aud"] = self._jwt_audience
        return jwt.encode(claims, self._jwt_secret, algorithm=self._jwt_algorithm)

    async def active_user_ids(self) -> list[str]:
        try:
            response = await self._client.get(
                "/v1/admin/users/ids",
                params={"status": "ACTIVE"},
                headers={"Authorization": f"Bearer {self._service_token()}"},
            )
        except httpx.TimeoutException:
            logger.warning(
                "auth-profile-service did not respond in time; "
                "publishing FestivalStarted with an empty audience"
            )
            return []
        except httpx.HTTPError:
            logger.warning(
                "auth-profile-service could not be reached; "
                "publishing FestivalStarted with an empty audience"
            )
            return []

        if response.status_code >= 400:
            logger.warning(
                "auth-profile-service rejected the user-directory lookup; "
                "publishing FestivalStarted with an empty audience",
                extra={"status": response.status_code, "body": response.text[:500]},
            )
            return []

        body = response.json()
        if not isinstance(body, list):
            logger.warning(
                "auth-profile-service returned an unexpected shape for the user directory; "
                "publishing FestivalStarted with an empty audience",
                extra={"body_type": type(body).__name__},
            )
            return []
        return [str(user_id) for user_id in body]
