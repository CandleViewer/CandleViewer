# A decoy api/csrf.py: only services/api/candleviewer/api/csrf.py may define the writer (ADR-0038 4b).
def write_auth_cookie(response, name, value, attrs):  # ruleid: cookie-flags-writer-location
    response.set_cookie(name, value, secure=True, httponly=True, samesite=attrs.samesite)
