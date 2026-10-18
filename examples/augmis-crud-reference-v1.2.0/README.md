# AUGMIS CRUD Reference 1.2.0

Development-only AAPS sample application with PostgreSQL CRUD and secure AUGMIS gateway integration. **Do not expose this app directly on a host or internet port.** The runtime expects an isolated instance database, read-only file-backed runtime DB password, matched public Ed25519 signing key, trusted tenant/application/instance IDs, and a signed AUGMIS gateway for all API requests.

The app does not create tables at runtime. AUGMIS's allowlisted trusted `application_database_schema.py` provides schema and RLS. The runtime user has SELECT/INSERT/UPDATE only; delete is implemented as a soft-delete UPDATE.

The app does not use or import any source Techtango data. This source is intended for the C1-B4 development pilot, not general customer production.

When uploaded to Publisher Center, choose **AAPS / Containerized**. The ZIP must contain `augmis-app.yaml` at its root. Start the application only after the C1-B4 control-plane launch integration and private relay are configured and enabled.
