# AUGMIS Runtime Lab — AAPS service-type correction

All four test applications have been updated to conform to the validation errors shown by your platform.

Correction in the root `augmis-app.yaml` of each ZIP:

```yaml
apiVersion: apps.augmis.com/v1alpha1
runtime:
  deploymentMode: dedicated
services:
  web:
    type: web       # valid enum: web, api, worker
    public: true
    port: 8080
    health:
      path: /health
```

No Python server, Dockerfile, HTML, CSS, or JavaScript content was changed from the previous corrected archives. The individual ZIPs should be uploaded via **Publisher Center > Upload Application > AAPS / Containerized**. Do not upload the outer suite ZIP to AUGMIS.

Suggested test sequence:

1. Upload **1.0.0**, validate, build and publish; establish test entitlement and deploy.
2. Upload **1.1.0** as a new version of the same application; build/publish and test upgrade.
3. Upload **1.2.0** to test failed health validation and safe upgrade rollback; it deliberately makes `/health` return 503.
4. Upload **2.0.0** to check `same_major`/`pinned` policy blocking as applicable.

**Validation notes:** Files passed ZIP integrity and consistency checks, but the private project's full AAPS schema validator could not be run in this environment. If further schema errors appear, use the exact validation message to update the sample package; do not relax platform validation or change backend code.
