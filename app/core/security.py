"""The bearer scheme, declared so the interactive docs can send a token.

Problem solved: every protected route reads the token with
``authorization: str | None = Header(default=None)``. That works for the mobile
client and for curl, and it leaves the Swagger page at ``/docs`` with no
**Authorize** button — so a browser could not exercise ``/analyze``,
``/optimize`` or ``/analyze/history`` at all without pasting
``Bearer <token>`` into a text box on every single request.

Why a scheme object rather than rewriting the routes to depend on it: the
``Header`` parameters already work and are covered by tests. Attaching this as a
route *dependency* adds the security requirement to the OpenAPI document — which
is what draws the Authorize button and makes Swagger attach the header to every
subsequent call — while the handlers keep reading the value exactly as before.
Nothing about request handling changes.

``auto_error=False`` on purpose. With it on, FastAPI would reject a missing
token with its own 403 before the handler ran, which would change the status
code these endpoints already return and contradict ``/analyze``, where the token
is genuinely optional and only decides whether history is saved. Rejection stays
with ``auth_service.require_user``, which owns it.
"""

from __future__ import annotations

from fastapi.security import HTTPBearer

#: Attach with ``dependencies=[Depends(bearer_scheme)]`` on a protected route.
bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="Bearer token",
    description=(
        "Paste the `token` returned by `/auth/register` or `/auth/login`. "
        "Swagger adds the `Authorization: Bearer <token>` header for you."
    ),
)
