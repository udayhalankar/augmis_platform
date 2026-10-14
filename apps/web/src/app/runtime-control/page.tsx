"use client";
import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import {
  Alert, Box, Button, Chip, CircularProgress, Dialog, DialogActions,
  DialogContent, DialogTitle, Divider, MenuItem, Paper, Table, TableBody,
  TableCell, TableContainer, TableHead, TableRow, TextField, Typography,
} from "@mui/material";
import RefreshOutlined from "@mui/icons-material/RefreshOutlined";
import StopCircleOutlined from "@mui/icons-material/StopCircleOutlined";
// import PlayCircleOutline from "@mui/icons-material/PlayCircleOutline";
import ArticleOutlined from "@mui/icons-material/ArticleOutlined";
import MonitorHeartOutlined from "@mui/icons-material/MonitorHeartOutlined";
import RuntimeUpgradeReadinessPanel from "@/components/runtime-upgrade-readiness-panel";
import RuntimeEnvironmentVariablesEditor from "@/components/runtime-environment-variables-editor";
import RuntimeQuotaManager from "@/components/runtime-quota-manager";
import ProtectedRoute from "@/components/protected-route";
import AppShell from "@/components/app-shell";
import { useTenant } from "@/context/tenant-context";
import {
  listRuntimeInstances, listRuntimeJobs, getRuntimeQuota, getRuntimeConfig, updateRuntimeConfig,
  stopRuntimeInstance, restartRuntimeInstance, listRuntimeDeployments,
  getRuntimeDeploymentHealth, getRuntimeDeploymentLogs,
  type RuntimeInstance, type RuntimeJob, type RuntimeConfig, type RuntimeQuota,
} from "@/lib/runtime-control";

function errorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail: unknown = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string") return detail.message;
    if (err.response?.status === 403) return "Your tenant role does not permit this runtime operation.";
    if (err.response?.status === 409) return "The instance state changed. Refresh and try again.";
  }
  return err instanceof Error ? err.message : "Runtime data could not be loaded.";
}

export default function RuntimeControlPage() {
  const { selectedTenant, selectedTenantId, loading: tenantLoading } = useTenant();
  const [instances, setInstances] = useState<RuntimeInstance[]>([]);
  const [jobs, setJobs] = useState<RuntimeJob[]>([]);
  const [quota, setQuota] = useState<RuntimeQuota | null>(null);
  const [currentId, setCurrentId] = useState("");
  const [config, setConfig] = useState<RuntimeConfig | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [lifecycleBusyId, setLifecycleBusyId] = useState("");
  const [pendingAction, setPendingAction] = useState<{ id: string; name: string; action: "stop" | "restart" } | null>(null);
  const [detailDialog, setDetailDialog] = useState<{ title: string; contents: string } | null>(null);
  const [detailBusyId, setDetailBusyId] = useState("");

  const reload = useCallback(async (tenantId: string) => {
    setLoading(true); setError("");
    try {
      const [items, upgrades, q] = await Promise.all([
        listRuntimeInstances(tenantId), listRuntimeJobs(tenantId), getRuntimeQuota(tenantId),
      ]);
      setInstances(items); setJobs(upgrades); setQuota(q);
      setCurrentId((existing) => items.some((item) => item.id === existing) ? existing : (items[0]?.id ?? ""));
    } catch (err) {
      setInstances([]); setJobs([]); setQuota(null); setCurrentId(""); setError(errorMessage(err));
    } finally { setLoading(false); }
  }, []);

  useEffect(() => {
    setInstances([]); setJobs([]); setQuota(null); setConfig(null); setCurrentId("");
    if (!tenantLoading && selectedTenantId) void reload(selectedTenantId);
  }, [selectedTenantId, tenantLoading, reload]);

  useEffect(() => {
    setConfig(null);
    if (!currentId) return;
    let cancelled = false;
    void getRuntimeConfig(currentId).then((data) => {
      if (!cancelled) setConfig(data);
    }).catch((err) => { if (!cancelled) setError(errorMessage(err)); });
    return () => { cancelled = true; };
  }, [currentId]);

  const save = async (variables: Record<string, string>) => {
    if (!config || !currentId || config.instanceId !== currentId) return;
    setError(""); setMessage(""); setBusy(true);
    try {
      await updateRuntimeConfig(currentId, config.revision, variables);
      const refreshed = await getRuntimeConfig(currentId);
      setConfig(refreshed);
      setMessage("Configuration saved. It will apply on the next container start, restart or upgrade.");
    } catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  };

  const runLifecycle = async () => {
    const action = pendingAction;
    if (!action || !selectedTenantId || lifecycleBusyId) return;
    const matching = instances.find((item) => item.id === action.id);
    if (!matching || (action.action === "stop" && matching.status !== "running") ||
        (action.action === "restart" && matching.status !== "stopped")) {
      setPendingAction(null);
      setError("Instance state has changed. Refresh and try again.");
      return;
    }
    setLifecycleBusyId(action.id);
    setError(""); setMessage("");
    try {
      if (action.action === "stop") {
        await stopRuntimeInstance(action.id);
        setMessage(`${action.name} stopped. Application launch is disabled until an administrator starts it.`);
      } else {
        await restartRuntimeInstance(action.id);
        setMessage(`${action.name} started. Application access is available after successful health checks.`);
      }
      setPendingAction(null);
      await reload(selectedTenantId);
    } catch (err) {
      const failureMessage = errorMessage(err);
      setPendingAction(null);
      await reload(selectedTenantId);
      setError(failureMessage);
    } finally {
      setLifecycleBusyId("");
    }
  };

  const inspectRuntime = async (instance: RuntimeInstance, kind: "health" | "logs") => {
    setError(""); setDetailBusyId(instance.id);
    try {
      const deployments = await listRuntimeDeployments(instance.id);
      const target = kind === "health"
        ? deployments.find((deployment) => deployment.status === "running")
        : deployments[0];
      if (!target) {
        setError(kind === "health"
          ? "This instance has no running deployment to inspect."
          : "This instance has no deployment history yet.");
        return;
      }
      if (kind === "health") {
        const health = await getRuntimeDeploymentHealth(target.deploymentId);
        const safeSummary = {
          deploymentStatus: health.deploymentStatus,
          effectiveHealth: health.effectiveHealth,
          recordedHealth: health.recordedHealth,
          containerRunning: health.container?.running ?? false,
          httpReachable: health.runtime?.reachable ?? false,
          httpStatus: health.runtime?.httpStatus ?? null,
        };
        setDetailDialog({ title: `${instance.name} — health`, contents: JSON.stringify(safeSummary, null, 2) });
      } else {
        const result = await getRuntimeDeploymentLogs(target.deploymentId);
        setDetailDialog({ title: `${instance.name} — ${result.source === "archived" ? "archived" : "live"} logs`,
          contents: result.logs || "No log entries found." });
      }
    } catch (err) { setError(errorMessage(err)); }
    finally { setDetailBusyId(""); }
  };

  return <ProtectedRoute><AppShell><Box sx={{ display: "flex", flexDirection: "column", gap: 2.5 }}>
    <Box sx={{display:"flex",justifyContent:"space-between",alignItems:"flex-start",gap:2,flexWrap:"wrap"}}>
      <Box>
        <Typography sx={{fontSize:11,textTransform:"uppercase",letterSpacing:1,color:"text.secondary"}}>Tenant runtime governance</Typography>
        <Typography variant="h4">Runtime Control</Typography>
        <Typography color="text.secondary">Instances, version jobs, quotas and non-secret configuration for the selected organization.</Typography>
      </Box>
      <Button variant="outlined" startIcon={<RefreshOutlined />} disabled={!selectedTenantId || loading}
        onClick={() => selectedTenantId && void reload(selectedTenantId)}>Refresh</Button>
    </Box>
    {selectedTenant && <Paper variant="outlined" sx={{p:2,borderRadius:0}}>
      <Typography sx={{ fontWeight: 700 }}>
  {selectedTenant.tenant.name}
</Typography>
      <Typography variant="caption" color="text.secondary">{selectedTenant.tenant.slug}</Typography>
    </Paper>}
    {!selectedTenantId && !tenantLoading && <Alert severity="warning">Select an active tenant to view runtime instances.</Alert>}
    {error && <Alert severity="error" onClose={()=>setError("")}>{error}</Alert>}
    {message && <Alert severity="success" onClose={()=>setMessage("")}>{message}</Alert>}
    {loading && <CircularProgress size={28}/>}
    {selectedTenantId && !loading && <>
      <Box sx={{display:"grid",gridTemplateColumns:{xs:"1fr",md:"repeat(3, 1fr)"},gap:2}}>
        <Paper variant="outlined" sx={{p:2,borderRadius:0}}><Typography color="text.secondary" variant="caption">INSTANCES</Typography><Typography variant="h5">{instances.length}</Typography></Paper>
        <Paper variant="outlined" sx={{p:2,borderRadius:0}}><Typography color="text.secondary" variant="caption">UPGRADE JOBS</Typography><Typography variant="h5">{jobs.length}</Typography></Paper>
        <Paper variant="outlined" sx={{p:2,borderRadius:0}}><Typography color="text.secondary" variant="caption">CONCURRENT CONTAINER QUOTA</Typography><Typography variant="h5">{quota?.maxRunningContainers ?? "Not set"}</Typography></Paper>
      </Box>
      {!!selectedTenantId && quota && <RuntimeQuotaManager tenantId={selectedTenantId} quota={quota} onSaved={(next) => setQuota(next)} />}
      <Paper variant="outlined" sx={{borderRadius:0,overflow:"hidden"}}>
        <Box sx={{px:2.5,py:2,borderBottom:"1px solid",borderColor:"divider"}}>
          <Typography variant="h6">Runtime application management</Typography>
          <Typography variant="caption" color="text.secondary">
             Stop disables this application's launch for the entire tenant and stops its running containers.
             Start an explicitly stopped instance to restore access after health checks. Both actions are permission-checked.
          </Typography>
        </Box>
        {!instances.length ? <Typography sx={{p:2.5}} color="text.secondary">No instances found for this tenant.</Typography> :
          <TableContainer sx={{maxHeight:440}}>
            <Table size="small" stickyHeader>
              <TableHead><TableRow>
                <TableCell sx={{fontWeight:700}}>Instance</TableCell>
                <TableCell sx={{fontWeight:700}}>State</TableCell>
                <TableCell sx={{fontWeight:700}} align="right">Actions</TableCell>
              </TableRow></TableHead>
              <TableBody>{instances.map((i) => {
                const waiting = lifecycleBusyId === i.id || detailBusyId === i.id;
                return <TableRow key={i.id} hover selected={currentId === i.id}>
                  <TableCell sx={{minWidth:220}}>
                    <Typography sx={{fontSize:13,fontWeight:600}}>{i.name}</Typography>
                    <Typography variant="caption" color="text.secondary">{i.instanceKey}</Typography>
                  </TableCell>
                  <TableCell><Chip size="small" variant="outlined" label={i.status}
                    color={i.status === "running" ? "success" : i.status === "failed" ? "error" : "default"}/></TableCell>
                  <TableCell align="right" sx={{minWidth:360}}>
                    <Box sx={{display:"flex",justifyContent:"flex-end",gap:1,flexWrap:"wrap"}}>
                      <Button size="small" variant="outlined" color="error" startIcon={<StopCircleOutlined />}
                        disabled={i.status !== "running" || Boolean(lifecycleBusyId) || Boolean(detailBusyId) || busy}
                        onClick={()=>setPendingAction({id:i.id,name:i.name,action:"stop"})}>Stop</Button>
                      <Button size="small" variant="outlined" startIcon={<RefreshOutlined />}
                        disabled={i.status !== "stopped" || Boolean(lifecycleBusyId) || Boolean(detailBusyId) || busy}
                        onClick={()=>setPendingAction({id:i.id,name:i.name,action:"restart"})}>Start</Button>
                      <Button size="small" variant="outlined" startIcon={<MonitorHeartOutlined />}
                        disabled={i.status !== "running" || waiting || Boolean(lifecycleBusyId)}
                        onClick={()=>void inspectRuntime(i,"health")}>Health</Button>
                      <Button size="small" variant="outlined" startIcon={<ArticleOutlined />}
                        disabled={waiting || Boolean(lifecycleBusyId)}
                        onClick={()=>void inspectRuntime(i,"logs")}>Logs</Button>
                    </Box>
                  </TableCell>
                </TableRow>;
              })}</TableBody>
            </Table>
          </TableContainer>}
      </Paper>
      <Paper variant="outlined" sx={{p:2.5,borderRadius:0}}>
        <Typography variant="h6" sx={{mb:1.5}}>Instance configuration</Typography>
        <TextField select label="Instance" fullWidth size="small" value={currentId} onChange={(ev)=>setCurrentId(ev.target.value)} sx={{mb:2}}>
          {instances.map((i)=><MenuItem value={i.id} key={i.id}>{i.name} — {i.status}</MenuItem>)}
        </TextField>
        {!instances.length && <Typography color="text.secondary">No instances are registered for this tenant.</Typography>}
        {!!currentId && <>
          <Alert severity="info" sx={{mb:2}}>Use non-secret variables only. Credentials, tokens and passwords must not be entered here. Values apply only when a new container starts.</Alert>
          {config?.instanceId === currentId ? (
            <RuntimeEnvironmentVariablesEditor
              key={`${currentId}:${config.revision ?? "new"}`}
              initialVariables={config.variables}
              revision={config.revision}
              busy={busy}
              onSave={save}
            />
          ) : (
            <Typography variant="caption" color="text.secondary">Loading configuration…</Typography>
          )}
        </>}
      </Paper>
      {!!currentId && <RuntimeUpgradeReadinessPanel key={currentId} instanceId={currentId} />}
      <Paper variant="outlined" sx={{p:2.5,borderRadius:0}}>
        <Typography variant="h6">Automatic upgrade jobs</Typography>
        <Typography variant="caption" color="text.secondary">Trusted worker is disabled until explicitly started by platform operations. Ambiguous subscriptions are excluded.</Typography>
        <Divider sx={{my:2}}/>
        {jobs.length===0 && <Typography color="text.secondary">No queued or historical automatic-upgrade jobs.</Typography>}
        {jobs.map((j)=><Box key={j.id} sx={{display:"flex",justifyContent:"space-between",alignItems:"center",gap:2,p:1.5,borderBottom:"1px solid",borderColor:"divider"}}>
          <Box sx={{minWidth:0}}><Typography sx={{ fontWeight: 600, fontSize: 13 }}>{instances.find(i=>i.id===j.instanceId)?.name ?? j.instanceId}</Typography>
            <Typography variant="caption" sx={{display:"block",wordBreak:"break-all"}} color="text.secondary">Target: {j.targetVersionId} · Attempts: {j.attempts}</Typography>
            {j.errorCode && <Typography color="error" sx={{ fontSize: 11 }}>{j.errorCode}</Typography>}
          </Box>
          <Chip size="small" label={j.status} variant="outlined" color={j.status==="succeeded"?"success":j.status==="failed"?"error":"default"}/>
        </Box>)}
      </Paper>
    </>}
    <Dialog open={Boolean(pendingAction)} onClose={()=>{if (!lifecycleBusyId) setPendingAction(null);}} maxWidth="sm" fullWidth>
      <DialogTitle>{pendingAction?.action === "stop" ? "Stop application instance?" : "Start application?"}</DialogTitle>
      <DialogContent>
        <Typography variant="body2">{pendingAction?.action === "stop"
          ? `Stop ${pendingAction.name}? ALL running containers for this application in the selected tenant will be stopped. Users cannot open the application until an administrator selects Start. The subscription remains active.`
          : `Start ${pendingAction?.name}? A new container will be deployed with saved configuration. Access is restored only if the new container is healthy. Active subscription and quota are required.`}</Typography>
      </DialogContent>
      <DialogActions sx={{px:3,pb:2}}>
        <Button disabled={Boolean(lifecycleBusyId)} onClick={()=>setPendingAction(null)}>Cancel</Button>
        <Button variant="contained" color={pendingAction?.action === "stop" ? "error" : "primary"}
          disabled={Boolean(lifecycleBusyId)} onClick={()=>void runLifecycle()}>
          {lifecycleBusyId ? "Working..." : pendingAction?.action === "stop" ? "Confirm stop" : "Confirm start"}
        </Button>
      </DialogActions>
    </Dialog>
    <Dialog open={Boolean(detailDialog)} onClose={()=>setDetailDialog(null)} maxWidth="md" fullWidth>
      <DialogTitle>{detailDialog?.title}</DialogTitle>
      <DialogContent>
        {detailDialog?.title.endsWith("logs") && <Alert severity="warning" sx={{mb:2}}>
          Application logs may contain sensitive information written by the application. Handle them carefully.
        </Alert>}
        <Box component="pre" sx={{fontFamily:"monospace",fontSize:12,whiteSpace:"pre-wrap",wordBreak:"break-word",
        bgcolor:"#f4f6f8",p:2,maxHeight:"55vh",overflow:"auto"}}>{detailDialog?.contents}</Box>
      </DialogContent>
      <DialogActions sx={{px:3,pb:2}}><Button onClick={()=>setDetailDialog(null)}>Close</Button></DialogActions>
    </Dialog>
  </Box></AppShell></ProtectedRoute>;
}
