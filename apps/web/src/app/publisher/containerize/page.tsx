"use client";

import { useEffect, useRef, useState } from "react";
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
  runPublisherDraftBuildTest, type DraftBuildTestResult,
  uploadApplicationPackage, buildApplicationPackage,
  exactAapsBlobSha256, getContainerizationReleaseReview, submitQualifiedContainerizationDraft,
  type RegisteredContainerizationDraft, type ContainerizationReleaseReview,
  resumeExistingContainerizationDraft,
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
  const [building, setBuilding] = useState(false);
  const [buildResult, setBuildResult] = useState<DraftBuildTestResult | null>(null);
  const [buildIssue, setBuildIssue] = useState("");
  const [registered, setRegistered] = useState<RegisteredContainerizationDraft | null>(null);
  const [releaseReview, setReleaseReview] = useState<ContainerizationReleaseReview | null>(null);
  const [releaseBusy, setReleaseBusy] = useState(false);
  const [releaseIssue, setReleaseIssue] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const draftRevision = useRef(0);

  function resetRelease() {
    setRegistered(null); setReleaseReview(null); setReleaseIssue(""); setSubmitted(false);
  }

  function releaseError(failure: unknown): string {
    if (axios.isAxiosError(failure)) {
      const d = failure.response?.data?.detail;
      if (d && typeof d === "object") {
        return `${String(d.code || "C1D54_ERROR")}: ${String(d.problem || d.message || "Publisher review failed")}. ${String(d.correction || "")}`;
      }
      if (typeof d === "string") return d;
    }
    return failure instanceof Error ? failure.message : "Publisher release action failed.";
  }

  function updateConfig<K extends keyof GenerateAapsConfig>(key: K, value: GenerateAapsConfig[K]) {
    setConfig((c) => ({ ...c, [key]: value }));
    setGeneration(null);
    setGenerationIssue("");
    draftRevision.current += 1;
    setBuildResult(null);
    setBuildIssue("");
    resetRelease();
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
    const analyzed = report;
    if (!publisherId || !file || !analyzed || !canGenerate || generating) return;
    setGenerating(true);
    setGeneration(null);
    setGenerationIssue("");
    setBuildResult(null);
    setBuildIssue("");
    resetRelease();
    try {
      const result = await previewGeneratedAaps(publisherId, file, config);
      if (result.sourceSha256 !== analyzed.sourceSha256) {
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


  async function buildTest() {
    const analyzed = report;
    const draft = generation;
    if (!publisherId || !file || !analyzed || !draft || building || generating) return;
    const revisionAtStart = draftRevision.current;
    setBuilding(true);
    setBuildResult(null);
    setBuildIssue("");
    resetRelease();
    try {
      const result = await runPublisherDraftBuildTest(
        publisherId, file, config, analyzed.sourceSha256, draft.artifactSha256,
      );
      if (result.sourceSha256 !== analyzed.sourceSha256 ||
          result.artifactSha256 !== draft.artifactSha256) {
        throw new Error("Build response does not match the analyzed and validated artifact.");
      }
      if (revisionAtStart === draftRevision.current) setBuildResult(result);
    } catch (failure: unknown) {
      if (axios.isAxiosError(failure)) {
        const d = failure.response?.data?.detail;
        setBuildIssue(d && typeof d === "object"
          ? `${String(d.code || "C1D53_ERROR")}: ${String(d.problem || "Build & Test failed")}. ${String(d.correction || "")}`
          : "Build & Test request failed. Check API and Docker availability.");
      } else {
        setBuildIssue(failure instanceof Error ? failure.message : "Build & Test failed.");
      }
    } finally { setBuilding(false); }
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
    setBuildResult(null);
    setBuildIssue("");
    resetRelease();
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



  const passedPreflight = Boolean(
    generation && report && buildResult && buildResult.buildStatus === "passed" &&
    buildResult.runtimeStatus === "passed" &&
    generation.sourceSha256 === report.sourceSha256 &&
    buildResult.sourceSha256 === report.sourceSha256 &&
    buildResult.artifactSha256 === generation.artifactSha256,
  );

  async function registerReleaseDraft() {
    const draft = generation;
    const analyzed = report;
    if (!passedPreflight || !file || !publisherId || !draft || !analyzed ||
        releaseBusy || registered) return;
    const revision = draftRevision.current;
    setReleaseBusy(true);
    setReleaseIssue("");
    try {
      const blob = await downloadGeneratedAaps(publisherId, file, config);
      const sha = await exactAapsBlobSha256(blob);
      if (sha !== draft.artifactSha256 || draft.sourceSha256 !== analyzed.sourceSha256 ||
          revision !== draftRevision.current) {
        throw new Error("C1D54_ARTIFACT_CHANGED: Downloaded package differs from the validated, tested draft. Regenerate and retest.");
      }
      const aapsFile = new File([blob], `${config.appKey}-${config.version}-draft-aaps.zip`,
        { type: "application/zip" });
      // Existing upload endpoint registers an UNPUBLISHED draft for trusted qualification.
      const saved = await uploadApplicationPackage(publisherId, aapsFile);
      if (saved.publisher.id !== publisherId || saved.package.sha256 !== sha ||
          saved.application.appKey !== config.appKey || saved.version.version !== config.version) {
        throw new Error("C1D54_REGISTRY_MISMATCH: Registered package/version does not match the exact generated artifact. Do not submit.");
      }
      if (revision !== draftRevision.current) return;
      setRegistered({ publisherId, packageId: saved.package.id,
        versionId: saved.version.id, buildId: null, artifactSha256: sha });
    } catch (failure: unknown) {
      setReleaseIssue(axios.isAxiosError(failure) && failure.response?.status === 409
        ? "C1D54_ALREADY_REGISTERED: This application version already exists. Use Resume Existing Registered Draft to verify its exact AAPS SHA-256 and continue."
        : releaseError(failure));
    } finally { setReleaseBusy(false); }
  }


  // Restore a server-persisted technical draft after page refresh or duplicate-upload 409.
  // Never treats preflight results as trusted release qualification.
  async function resumeRegisteredDraft() {
    const draft = generation;
    if (!publisherId || !draft || !passedPreflight || registered || releaseBusy) return;
    setReleaseBusy(true);
    setReleaseIssue("");
    setReleaseReview(null);
    try {
      const found = await resumeExistingContainerizationDraft(
        publisherId, config.appKey, config.version, draft.artifactSha256,
      );
      if (found.publisherId !== publisherId ||
          found.artifactSha256 !== draft.artifactSha256) {
        throw new Error("C1D54_RESUME_ARTIFACT_MISMATCH: Existing record is not this exact AAPS draft.");
      }
      setRegistered(found);
    } catch (failure: unknown) {
      setReleaseIssue(releaseError(failure));
    } finally { setReleaseBusy(false); }
  }

  async function buildRegisteredDraft() {
    const draft = registered;
    if (!draft || draft.buildId || !passedPreflight || releaseBusy) return;
    setReleaseBusy(true);
    setReleaseIssue("");
    try {
      const built = await buildApplicationPackage(draft.packageId);
      if (built.build.status !== "ready" || built.application.appKey !== config.appKey ||
          built.version !== config.version) {
        throw new Error("C1D54_REGISTERED_BUILD_MISMATCH: Registered build did not return the selected version.");
      }
      setRegistered({ ...draft, buildId: built.build.id });
      setReleaseReview(null);
    } catch (failure: unknown) {
      setReleaseIssue(releaseError(failure));
    } finally { setReleaseBusy(false); }
  }

  async function refreshReleaseReview() {
    const draft = registered;
    if (!draft?.buildId || !passedPreflight || releaseBusy) return;
    setReleaseBusy(true);
    setReleaseIssue("");
    try {
      const result = await getContainerizationReleaseReview(draft);
      if (result.artifactSha256 !== draft.artifactSha256 ||
          result.packageId !== draft.packageId || result.versionId !== draft.versionId ||
          result.buildId !== draft.buildId) {
        throw new Error("C1D54_RELEASE_EVIDENCE_MISMATCH: Server review does not match registered artifact.");
      }
      setReleaseReview(result);
    } catch (failure: unknown) {
      setReleaseReview(null);
      setReleaseIssue(releaseError(failure));
    } finally { setReleaseBusy(false); }
  }

  async function submitPublisherDraft() {
    const draft = registered;
    if (!draft?.buildId || !releaseReview?.eligible || submitted || releaseBusy ||
        !passedPreflight) return;
    setReleaseBusy(true);
    setReleaseIssue("");
    try {
      // Server rechecks exact stored ZIP, pinned build and trusted C1-D2 qualification.
      const result = await submitQualifiedContainerizationDraft(draft);
      if (result.status !== "SUBMITTED_DRAFT" || result.artifactSha256 !== draft.artifactSha256 ||
          result.versionId !== draft.versionId || result.publicationStatus !== "draft") {
        throw new Error("C1D54_SUBMISSION_MISMATCH: Server did not confirm the exact qualified draft.");
      }
      setSubmitted(true);
      setReleaseReview(result);
    } catch (failure: unknown) {
      setReleaseIssue(releaseError(failure));
      setReleaseReview(null);
    } finally { setReleaseBusy(false); }
  }

  const checks = report?.checks.map((c) => {
    if (releaseReview && c.id === "qualification") {
      return { ...c, status: releaseReview.eligible ? "passed" as const :
        releaseReview.status === "failed" ? "failed" as const : "not_checked" as const,
        code: releaseReview.code, problem: releaseReview.problem,
        correction: releaseReview.correction, location: "Registered C1-D2 qualification" };
    }
    if (buildResult && (c.id === "build" || c.id === "runtime" || c.id === "qualification")) {
      return { ...c, ...buildResult.checks[c.id] };
    }
    if (generation && c.id === "artifacts") {
      return { ...c, status: "passed" as const,
        code: "AAPS_GENERATED_CONTRACT_VALIDATED",
        problem: "Draft manifest and Dockerfile validated against the AAPS contract.", correction: "" };
    }
    return c;
  }) ?? requirements.map((label, index) => ({
    id: String(index), label, status: "not_checked" as const,
    code: "NOT_RUN", location: null, problem: "Waiting for source analysis.", correction: "",
  }));

  return (
    <ProtectedRoute><AppShell>
      <Stack spacing={3}>
        <Box>
          <Button component={Link} href="/publisher" startIcon={<ArrowBackOutlined />} sx={{ mb: 1 }}>Publisher Center</Button>
          <Typography sx={{ fontSize: 11, color: "text.secondary", textTransform: "uppercase", letterSpacing: 0.8 }}>Publisher Workspace / C1-D5.4</Typography>
          <Typography variant="h4">App Containerization &amp; Validator</Typography>
          <Typography variant="body2" color="text.secondary">Upload source, check compatibility and see the exact changes needed before containerization.</Typography>
        </Box>
        <Paper variant="outlined" sx={{ p: 2.5 }}>
          <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} sx={{ mb: 2 }}>
            {["1 Analyze", "2 Configure", "3 Generate", "4 Build & Test", "5 Review"].map((x, index) => (
              <Box key={x} sx={{ border: "1px solid", borderColor: "divider", p: 1, flex: 1, bgcolor: index < 4 ? "action.hover" : "background.paper" }}>
                <Typography sx={{ fontSize: 12, fontWeight: index === 0 ? 700 : 400 }}>{x}</Typography>
                <Typography sx={{ fontSize: 11, color: "text.secondary" }}>{"Available"}</Typography>
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
              <Select labelId="publisher-select-label" label="Publisher" value={publisherId} onChange={(event) => { setPublisherId(event.target.value); setReport(null); setGeneration(null); setGenerationIssue(""); draftRevision.current += 1; setBuildResult(null); setBuildIssue(""); resetRelease(); }}>
                {publishers.map((p) => <MenuItem key={p.id} value={p.id}>{p.name}</MenuItem>)}
              </Select>
            </FormControl>
            <Button variant="outlined" component="label" startIcon={<UploadFileOutlined />}>
              Select source ZIP
              <input hidden type="file" accept=".zip,application/zip" onChange={(event) => {
                setFile(event.target.files?.[0] ?? null); setReport(null); setError(""); setGeneration(null); setGenerationIssue(""); draftRevision.current += 1; setBuildResult(null); setBuildIssue(""); resetRelease(); event.target.value = "";
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
            {!buildResult && <strong> Build, runtime and C1-D2 qualification remain Not Checked.</strong>} Publisher submission remains disabled until C1-D5.4.
          </Alert>}
        </Paper>
        <Paper variant="outlined" sx={{ p: 2.5 }}>
          <Typography variant="h6">Build &amp; Test — C1-D5.3</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Execute the existing Docker build engine and C1-D2 disposable PostgreSQL, health and API smoke checks
            against the exact validated artifact SHA-256. This does not register or publish an app.
          </Typography>
          <Button variant="contained" disabled={!generation || building || generating || downloading}
            onClick={buildTest} startIcon={building ? <CircularProgress size={16} color="inherit" /> : <RuleOutlined />}>
            {building ? "Building and testing…" : "Build & Test Exact Draft"}
          </Button>
          {buildIssue && <Alert severity="error" sx={{ mt: 2 }}>{buildIssue}</Alert>}
          {buildResult && <>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ mt: 2 }}>
              <Chip variant="outlined" color={buildResult.buildStatus === "passed" ? "success" : "error"}
                label={`Docker build: ${stateLabels[buildResult.buildStatus] || buildResult.buildStatus}`} />
              <Chip variant="outlined" color={buildResult.runtimeStatus === "passed" ? "success" : buildResult.runtimeStatus === "not_checked" ? "default" : "warning"}
                label={`Disposable runtime: ${stateLabels[buildResult.runtimeStatus] || buildResult.runtimeStatus}`} />
              <Chip variant="outlined" label="C1-D2 release qualification: Not Checked" />
            </Stack>
            {buildResult.imageId && <Typography variant="caption" sx={{ display: "block", mt: 1, overflowWrap: "anywhere" }}>
              Immutable image: <code>{buildResult.imageId}</code>
            </Typography>}
            {Object.entries(buildResult.smokeChecks).length > 0 && <Box sx={{ mt: 1 }}>
              {Object.entries(buildResult.smokeChecks).map(([name, passed]) => (
                <Chip key={name} label={`${name}: ${passed ? "Passed" : "Failed"}`}
                  color={passed ? "success" : "error"} variant="outlined" size="small" sx={{ mr: 0.75, mb: 0.75 }} />
              ))}
            </Box>}
            <Typography variant="subtitle2" sx={{ mt: 2 }}>Existing Docker build log</Typography>
            <Box component="pre" sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere",
              maxHeight: 340, overflow: "auto", p: 1.5, bgcolor: "action.hover", fontSize: 11,
              border: "1px solid", borderColor: "divider" }}>
              {buildResult.buildLog || "Docker build did not produce a log."}
            </Box>
            <Alert severity="info" sx={{ mt: 1 }}>
              Pre-submission test only. Formal C1-D2 release qualification and Publisher registration
              remain disabled until the C1-D5.4 server-side integration.
            </Alert>
          </>}
        </Paper>

        <Paper variant="outlined" sx={{ p: 2.5 }}>
          <Typography variant="h6">Review &amp; Submit to Publisher — C1-D5.4</Typography>
          <Typography color="text.secondary" variant="body2" sx={{ mb: 2 }}>
            Register the exact tested AAPS as an unpublished technical draft, then use the existing
            Docker build and trusted C1-D2 qualification worker. Final submission records an audited
            review handoff; it does not publish an application or create an offer.
          </Typography>
          <Stack direction={{ xs: "column", md: "row" }} spacing={1} sx={{ mb: 1 }}>
            <Button variant="outlined" disabled={!passedPreflight || !!registered || releaseBusy || submitted}
              onClick={registerReleaseDraft}>
              1 Register Exact Draft for Qualification
            </Button>
            <Button variant="outlined" disabled={!passedPreflight || !!registered || releaseBusy || submitted}
              onClick={resumeRegisteredDraft}>
              Resume Existing Registered Draft
            </Button>
            <Button variant="outlined" disabled={!registered || !!registered.buildId || releaseBusy || submitted}
              onClick={buildRegisteredDraft}>
              2 Build Registered Draft &amp; Queue C1-D2
            </Button>
            <Button variant="outlined" disabled={!registered?.buildId || releaseBusy || submitted}
              onClick={refreshReleaseReview}>
              3 Refresh Trusted Qualification
            </Button>
          </Stack>
          {releaseBusy && <CircularProgress size={18} sx={{ my: 1 }} />}
          {registered && <Typography sx={{ fontSize: 12, overflowWrap: "anywhere" }}>
            Package: <code>{registered.packageId}</code> · Version: <code>{registered.versionId}</code>
            {registered.buildId ? <> · Build: <code>{registered.buildId}</code></> : " · Not built"}
            <Typography component="span" sx={{ display: "block", fontSize: 11 }}>
              Exact registered AAPS SHA-256: <code>{registered.artifactSha256}</code>
            </Typography>
          </Typography>}
          {releaseReview && <Alert severity={releaseReview.eligible ? "success" : "info"} sx={{ mt: 1 }}>
            <strong>{releaseReview.code}</strong>: {releaseReview.problem}
            {releaseReview.correction && <> Correction: {releaseReview.correction}</>}
            {releaseReview.qualificationFailureCode && <> Worker code: {releaseReview.qualificationFailureCode}</>}
          </Alert>}
          {releaseIssue && <Alert severity="error" sx={{ mt: 1 }}>{releaseIssue}</Alert>}
          {submitted && <Alert severity="success" sx={{ mt: 1 }}>
            Qualified draft submitted for Publisher review and audited. It remains unpublished.
          </Alert>}
          <Typography color="text.secondary" sx={{ fontSize: 12, mt: 1 }}>
            A registered draft appears in the Publisher registry before qualification by design: the
            existing trusted C1-D2 worker requires its persisted version and build records.
            A pending worker result never enables final submission.
          </Typography>
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
            <Typography variant="body2" color="text.secondary">{submitted ? "Qualified draft submitted for Publisher review; publication remains a separate action." : "Submission requires server-verified matching package, registered build and trusted C1-D2 qualification."}</Typography>
            <Button disabled={!releaseReview?.eligible || !passedPreflight || releaseBusy || submitted}
              onClick={submitPublisherDraft} variant="contained"
              startIcon={releaseReview?.eligible ? <CheckCircleOutlined /> : <ErrorOutlineOutlined />}
              sx={{ minWidth: 190 }}>{submitted ? "Submitted for Review" : "Submit to Publisher"}</Button>
          </Stack>
        </Paper>
      </Stack>
    </AppShell></ProtectedRoute>
  );
}
