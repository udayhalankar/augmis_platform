AUGMIS R07 — Delivery checkpoint, 27 October 2026
Delivered and verified in development
- Three versions registered under one immutable application identity.
- Development relay now forwards manifest-authorized authenticated PATCH; live Edit/Save succeeds.
- Existing instance upgraded from 1.0.0 to 1.1.1; then under an authorized any policy to 2.0.1.
- SQLAlchemy query confirms the existing instance 03821732-84fd-4ca6-92ce-e6db0c5a6f67 is running 2.0.1, subscription 1fb4b0aa-3cff-4e87-b7f7-0ee534014131 is active, version policy any, automatic upgrades off.
- same_major policy correctly rejected a qualified/published cross-major candidate.
- Change Offer UI, existing audited backend workflow, and any coordinated release support implemented; focused automated tests passed.
- Original Warehouse, Visitor Desk and Equipment Inspection applications remain outside the R07 test lineage.
Acceptance not yet established (must not be marked passed)
1. Data continuity: show that one known record created before the upgrade is still accessible, editable and saved after 2.0.1. Live app create/edit alone is insufficient.
2. Controlled rollback: confirm UI indicates rollback available, run rollback on the isolated R07 test instance only, inspect audit, health, active version and unchanged DB resource; return to 2.0.1 if approved.
3. Pinned contract: read-only synthetic-policy negative test is a useful code check, but a live pinned-offer denial is not yet proven.
4. Automatic upgrade: opt-in off has been observed. An opt-in on unattended upgrade and durable worker recovery remain to be tested with an approved future target in staging; don't create more versions simply to claim progress.
5. Failed candidate: separate health-failure/rollback proof is not the same as manual rollback. Requires staging fault-injection on disposable data.
Delivery rule
No more R07 test application creation, generic collectors or policy patches unless a reproduced defect requires one. Preserve source changes in the approved release process; CI gates R09–R11 and Linux staging/R14–R15 remain separate. Continue independent R08 and R09 work in parallel rather than letting staging-only R07 scenarios idle the roadmap. Production startup gate remains closed.