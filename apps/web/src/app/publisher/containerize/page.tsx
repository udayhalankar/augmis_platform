"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import axios from "axios";
import {
  Alert, Box, Button, Chip, CircularProgress, Divider, FormControl,
  InputLabel, MenuItem, Paper, Select, Stack, TextField, Typography,
} from "@mui/material";
import UploadFileOutlined from "@mui/icons-material/UploadFileOutlined";
import ArrowBackOutlined from "@mui/icons-material/ArrowBackOutlined";
import CheckCircleOutlined from "@mui/icons-material/CheckCircleOutlined";
import ErrorOutlineOutlined from "@mui/icons-material/ErrorOutlineOutlined";
import RuleOutlined from "@mui/icons-material/RuleOutlined";
import AppShell from "@/components/app-shell";
import ProtectedRoute from "@/components/protected-route";
import {
  analyzePublisherSource,
  loadPublishers,
  type SourceAnalysisReport,
  type SourceValidationCheck,
  type PublisherWorkspace,
  previewGeneratedAaps, downloadGeneratedAaps,
  type GeneratedAapsDraft, type GenerateAapsConfig,
} from "@/lib/publisher-center";

const requirements = [
  "Source archive safety", "Application source structure",
  "React frontend and build configuration", "FastAPI backend and dependencies",
  "PostgreSQL declaration and schema", "Application health endpoint",
  "Source credentials and secret files", "AAPS manifest and Dockerfile",
  "Isolated Docker image build", "Disposable startup, database and API tests",
  "Immutable-build release qualification",
];

const stateLabels: Record<string, string> = {
  passed: "Passed", failed: "Failed", action_required: "Action Required",
  not_checked: "Not Checked",
};
const stateColors = {
  passed: "success", failed: "error", action_required: "warning", not_checked: "default",
} as const;

function ResultLine({ item }: { item: SourceValidationCheck }) {
  const status = item.status;
  return (
    <Box sx={{ py: 1.5, borderBottom: "1px solid", borderColor: "divider" }}>
  <Stack
  direction={{ xs: "column", md: "row" }}
  spacing={2}
  sx={{
    justifyContent: "space-between",
    alignItems: { md: "center" },
  }}
>
        <Typography variant="body2" sx={{ fontWeight: 600 }}>{item.label}</Typography>
        <Chip size="small" label={stateLabels[status] || status} color={stateColors[status] || "default"} variant="outlined" />
      </Stack>
      <Typography sx={{ color: "text.secondary", fontSize: 12, mt: 0.75 }}>{item.problem}</Typography>
      {item.location && <Typography sx={{ fontSize: 12, mt: 0.5 }}>File: <code>{item.location}</code></Typography>}
      {status !== "not_checked" && <Typography sx={{ fontSize: 11, color: "text.secondary", mt: 0.5 }}>Code: <code>{item.code}</code></Typography>}
      {item.correction && (status === "failed" || status === "action_required") && (
        <Typography sx={{ fontSize: 12, mt: 0.75 }}><strong>Correction:</strong> {item.correction}</Typography>
      )}
    </Box>
  );
}

export default function ContainerizeSourcePage() {
  const [publishers, setPublishers] = useState<PublisherWorkspace[]>([]);
  const [publisherId, setPublisherId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<SourceAnalysisReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [generation, setGeneration] = useState<GeneratedAapsDraft | null>(null);
  const [generationIssue, setGenerationIssue] = useState("");
  const [config, setConfig] = useState<GenerateAapsConfig>({
    appName: "", appKey: "", version: "1.0.0",
    routesJson: "", schemaJson: "", outputDir: "dist",
  });
  const [generating, setGenerating] = useState(false);
  const [downloading, setDownloading] = useState(false);

  function updateConfig<K extends keyof GenerateAapsConfig>(key: K, value: GenerateAapsConfig[K]) {
    setConfig((c) => ({ ...c, [key]: value }));
    setGeneration(null);
    setGenerationIssue("");
  }

  function generationError(failure: unknown) {
    if (axios.isAxiosError(failure)) {
      const detail = failure.response?.data?.detail;
      if (detail && typeof detail === "object") {
        return `${String(detail.code || "GEN_ERROR")}: ${String(detail.problem || "Generation failed")}. Correction: ${String(detail.correction || "Check the source ZIP")}${detail.location ? ` (File: ${detail.location})` : ""}`;
      }
    }
    return "AAPS generation failed. Check source analysis, backend configuration and API availability.";
  }

  const canGenerate = Boolean(report && (report.analysisPassed || (
    report.classification === "supported" && config.schemaJson.trim() &&
    report.checks.filter((c) => c.status === "failed" || c.status === "action_required")
      .every((c) => c.id === "database" && c.code === "POSTGRES_SCHEMA_REQUIRED")
  )));

  async function prepareDraft() {
    if (!publisherId || !file || !canGenerate || generating) return;
    setGenerating(true);
    setGeneration(null);
    setGenerationIssue("");
    try {
      const result = await previewGeneratedAaps(publisherId, file, config);
      if (result.sourceSha256 !== report.sourceSha256) {
        throw new Error("Source ZIP changed since analysis. Analyze this file again.");
      }
      setGeneration(result);
    } catch (failure: unknown) {
      setGenerationIssue(failure instanceof Error && !axios.isAxiosError(failure)
        ? failure.message : generationError(failure));
    } finally { setGenerating(false); }
  }

  async function downloadDraft() {
    if (!publisherId || !file || !generation || downloading) return;
    setDownloading(true);
    setGenerationIssue("");
    try {
      const data = await downloadGeneratedAaps(publisherId, file, config);
      if (!data.size) throw new Error("Generated AAPS was empty.");
      const url = URL.createObjectURL(data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${config.appKey}-${config.version}-draft-aaps.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (failure: unknown) {
      setGenerationIssue(failure instanceof Error && !axios.isAxiosError(failure)
        ? failure.message : generationError(failure));
    } finally { setDownloading(false); }
  }


  useEffect(() => {
    let alive = true;
    loadPublishers().then((items) => {
      if (!alive) return;
      setPublishers(items);
      setPublisherId((current) => current || items[0]?.id || "");
    }).catch(() => {
      if (alive) setError("Could not load publisher workspaces. Sign in and verify publisher permissions.");
    });
    return () => { alive = false; };
  }, []);

  async function analyze() {
    if (!publisherId || !file || loading) return;
    setError("");
    setReport(null);
    setGeneration(null);
    setLoading(true);
    try {
      const result = await analyzePublisherSource(publisherId, file);
      setReport(result);
    } catch (failure: unknown) {
      if (axios.isAxiosError(failure)) {
        const detail = failure.response?.data?.detail;
        setError(typeof detail === "string" ? detail : "Analysis request failed. Check authentication, ZIP size and API availability.");
      } else {
        setError("Could not complete source analysis.");
      }
    } finally { setLoading(false); }
  }

  const checks = report?.checks.map((c) => generation && c.id === "artifacts" ? ({ ...c, status: "passed" as const, code: "AAPS_GENERATED_CONTRACT_VALIDATED", problem: "Draft manifest and Dockerfile reviewed against the AAPS contract; image has not been built.", correction: "" }) : c) ?? requirements.map((label, index) => ({
    id: String(index), label, status: "not_checked" as const,
    code: "NOT_RUN", location: null, problem: "Waiting for source analysis.", correction: "",
  }));

  return (
    <ProtectedRoute><AppShell>
      <Stack spacing={3}>
        <Box>
          <Button component={Link} href="/publisher" startIcon={<ArrowBackOutlined />} sx={{ mb: 1 }}>Publisher Center</Button>
          <Typography sx={{ fontSize: 11, color: "text.secondary", textTransform: "uppercase", letterSpacing: 0.8 }}>Publisher Workspace / C1-D5.2</Typography>
          <Typography variant="h4">App Containerization &amp; Validator</Typography>
          <Typography variant="body2" color="text.secondary">Upload source, check compatibility and see the exact changes needed before containerization.</Typography>
        </Box>
        <Paper variant="outlined" sx={{ p: 2.5 }}>
          <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} sx={{ mb: 2 }}>
            {["1 Analyze", "2 Configure", "3 Generate", "4 Build & Test", "5 Review"].map((x, index) => (
              <Box key={x} sx={{ border: "1px solid", borderColor: "divider", p: 1, flex: 1, bgcolor: index < 3 ? "action.hover" : "background.paper" }}>
                <Typography sx={{ fontSize: 12, fontWeight: index === 0 ? 700 : 400 }}>{x}</Typography>
                <Typography sx={{ fontSize: 11, color: "text.secondary" }}>{index < 3 ? "Available" : "Next increment"}</Typography>
              </Box>
            ))}
          </Stack>
          <Typography variant="h6" sx={{ mb: 2 }}>Source application</Typography>
<Stack
  direction={{ xs: "column", md: "row" }}
  spacing={2}
  sx={{
    alignItems: { md: "center" },
  }}
>
            <FormControl size="small" sx={{ minWidth: 250 }}>
              <InputLabel id="publisher-select-label">Publisher</InputLabel>
              <Select labelId="publisher-select-label" label="Publisher" value={publisherId} onChange={(event) => { setPublisherId(event.target.value); setReport(null); setGeneration(null); setGenerationIssue(""); }}>
                {publishers.map((p) => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)}
              </Select>
            </FormControl>
            <Button variant="outlined" component="label" startIcon={<UploadFileOutlined />}>
              Select source ZIP
              <input hidden type="file" accept=".zip,application/zip" onChange={(event) => {
                setFile(event.target.files?.[0] ?? null); setReport(null); setError(""); setGeneration(null); setGenerationIssue(""); event.target.value = "";
              }} />
            </Button>
            <Typography sx={{ fontSize: 12, overflowWrap: "anywhere" }}>{file ? `${file.name} (${(file.size / 1024).toFixed(0)} KB)` : "No file selected"}</Typography>
            <Button variant="contained" disabled={!publisherId || !file || loading} onClick={analyze} startIcon={loading ? <CircularProgress size={16} color="inherit" /> : <RuleOutlined />}>
              {loading ? "Analyzing…" : "Analyze source"}
            </Button>
          </Stack>
          <Alert severity="info" sx={{ mt: 2 }}>Source analysis does not execute code, build an image or register an application. The existing Static Web upload route remains unchanged.</Alert>
          {error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}
        </Paper>
        <Paper variant="outlined" sx={{ p: 2.5 }}>
          <Typography variant="h6">Configure &amp; Generate AAPS</Typography>
          <Typography color="text.secondary" variant="body2" sx={{ mb: 2 }}>
            Supported template: React frontend + FastAPI backend, optional PostgreSQL with explicit AAPS schema mapping. No Docker build occurs here.
          </Typography>
          <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ mb: 2 }}>
            <TextField size="small" label="Application name" required value={config.appName} onChange={(e) => updateConfig("appName", e.target.value)} fullWidth />
            <TextField size="small" label="Application key" required value={config.appKey} onChange={(e) => updateConfig("appKey", e.target.value)} fullWidth helperText="lowercase letters, digits and hyphens" />
            <TextField size="small" label="Version" required value={config.version} onChange={(e) => updateConfig("version", e.target.value)} sx={{ minWidth: 150 }} />
          </Stack>
          <FormControl size="small" sx={{ minWidth: 240, mb: 2 }}>
            <InputLabel id="build-output-label">React output directory</InputLabel>
            <Select labelId="build-output-label" label="React output directory" value={config.outputDir}
              onChange={(e) => updateConfig("outputDir", e.target.value as "dist" | "build")}>
              <MenuItem value="dist">dist (Vite/default)</MenuItem><MenuItem value="build">build (React Scripts)</MenuItem>
            </Select>
          </FormControl>
          <TextField fullWidth size="small" label="API gateway routes JSON (optional if already declared in source)"
            value={config.routesJson} onChange={(e) => updateConfig("routesJson", e.target.value)} multiline minRows={2}
            placeholder={'[{"path":"/api/items","methods":["GET","POST"]}]'} sx={{ mb: 2 }}
            helperText="Use explicit permitted routes. No routes are invented." />
          <TextField fullWidth size="small" label="PostgreSQL declarative schema JSON (optional if source already declares one)"
            value={config.schemaJson} onChange={(e) => updateConfig("schemaJson", e.target.value)} multiline minRows={2}
            placeholder={'{"tables":[{"name":"items","columns":[{"name":"title","type":"text"}]}]}'} sx={{ mb: 2 }}
            helperText="Required for PostgreSQL if not already in augmis-app.yaml or db/aaps-schema.json." />
          <Stack direction={{ xs: "column", md: "row" }} spacing={2} sx={{ alignItems: { md: "center" } }}>
            <Button variant="contained" disabled={!canGenerate || !file || !publisherId || generating || !config.appName || !config.appKey}
              onClick={prepareDraft} startIcon={generating ? <CircularProgress size={16} color="inherit" /> : <RuleOutlined />}>
              {generating ? "Generating…" : "Generate & Validate Draft"}
            </Button>
            <Button variant="outlined" disabled={!generation || downloading} onClick={downloadDraft} startIcon={<UploadFileOutlined />}>
              {downloading ? "Preparing download…" : "Download Draft AAPS ZIP"}
            </Button>
          </Stack>
          {generationIssue && <Alert severity="error" sx={{ mt: 2 }}>{generationIssue}</Alert>}
          {generation && <Alert severity="success" sx={{ mt: 2 }}>
            AAPS manifest contract validated. Dockerfile: {generation.dockerfileMode}. Artifact SHA-256: {generation.artifactSha256}.
            <strong> Build, runtime and C1-D2 qualification remain Not Checked.</strong> This does not enable Publisher submission.
          </Alert>}
        </Paper>
        <Paper variant="outlined" sx={{ p: 2.5 }}>
       <Stack
  direction={{ xs: "column", md: "row" }}
  spacing={1}
  sx={{
    mb: 2,
    justifyContent: "space-between",
  }}
>
            <Box>
              <Typography variant="h6">Requirements &amp; validation results</Typography>
              <Typography color="text.secondary" variant="body2">Passed / Failed / Action Required / Not Checked. Only verified tests are marked Passed.</Typography>
            </Box>
            {report && <Chip color={report.analysisPassed ? "success" : "warning"} variant="outlined" label={report.analysisPassed ? "Source analysis passed" : "Corrections required"} />}
          </Stack>
          {report && <>
            <Stack
  direction={{ xs: "column", sm: "row" }}
  sx={{
    mb: 1,
    gap: 1,
  }}
>
              <Chip size="small" label={`Stack: ${report.detectedStack}`} />
              <Chip size="small" label={`Classification: ${report.classification.replaceAll("_", " ")}`} />
              <Chip size="small" label={`Passed: ${report.summary.passed}`} color="success" variant="outlined" />
              <Chip size="small" label={`Failed: ${report.summary.failed}`} color="error" variant="outlined" />
              <Chip size="small" label={`Action required: ${report.summary.actionRequired}`} color="warning" variant="outlined" />
            </Stack>
            <Typography sx={{ fontSize: 11, color: "text.secondary" }}>Source SHA-256: <code>{report.sourceSha256}</code></Typography>
          </>}
          <Divider sx={{ my: 1 }} />
          {checks.map((item) => <ResultLine key={item.id} item={item} />)}
         <Stack
  direction={{ xs: "column", md: "row" }}
  spacing={2}
  sx={{
    mt: 2,
    alignItems: { md: "center" },
    justifyContent: "space-between",
  }}
>
            <Typography variant="body2" color="text.secondary">{report?.publisherSubmissionReason ?? "Publisher submission requires verified AAPS generation, build and qualification; these steps have not run."}</Typography>
            <Button disabled variant="contained" startIcon={report?.analysisPassed ? <CheckCircleOutlined /> : <ErrorOutlineOutlined />} sx={{ minWidth: 190 }}>Submit to Publisher</Button>
          </Stack>
        </Paper>
      </Stack>
    </AppShell></ProtectedRoute>
  );
}
