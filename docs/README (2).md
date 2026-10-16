# AUGMIS Runtime Lab — AAPS manifest correction

These are corrected containerized application ZIPs for the AUGMIS **AAPS / Containerized** upload option. The only modifications are in `augmis-app.yaml`:

- `apiVersion: apps.augmis.com/v1alpha1`
- `runtime.deploymentMode: dedicated`
- `services.web.type: http`

All four ZIP files preserve `Dockerfile`, `server.py`, and static assets from the initial test suite. Each ZIP has `augmis-app.yaml` at its root.

Upload **AUGMIS_RUNTIME_LAB_1.0.0_AAPS_FIXED.zip** first. Do not upload the outer suite ZIP to the publisher.

**Verification note:** These files have been checked for ZIP integrity and the three errors visible in your screenshot have been corrected. The current local `tools/validate_package.py`/AAPS schema was not included in the files available to us, so passing your full local application validator is still to be confirmed. If AUGMIS reports a new schema error, share its exact message or `packages/contracts/aaps-v1.schema.json`. Do not relax schema rules.

Next versions: 1.1.0 healthy upgrade; 1.2.0-UNHEALTHY intentionally 503 health endpoint; 2.0.0 major-version policy test.

SHA256 files:
- `AUGMIS_RUNTIME_LAB_1.0.0_AAPS_FIXED.zip`: `d2789f697d0ccdaa1a1536702ee2384bdf052298ea53c6d88878866c5bfaf908`
- `AUGMIS_RUNTIME_LAB_1.1.0_AAPS_FIXED.zip`: `b4c054d0345018c6af555bed635a6ce99ba2fe0dcfcb964d00f264fccad2ecf8`
- `AUGMIS_RUNTIME_LAB_1.2.0-UNHEALTHY_AAPS_FIXED.zip`: `adad1d9822fe0371a6ed0f542fdf077a4070679a252ad4a57a8f0abf9ee2aaad`
- `AUGMIS_RUNTIME_LAB_2.0.0_AAPS_FIXED.zip`: `467d2532efbf7a7f2591f18c27e1aa1ec2d67d46bd05463e0bdc6a64479f182c`
