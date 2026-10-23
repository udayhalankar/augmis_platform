import api from "@/lib/api";


export type PublisherWorkspace = {
  id: string;
  name: string;
  slug: string;
};


export type PublisherMembership = {
  membershipId: string;
  status: string;

  publisher: PublisherWorkspace;
};


export type PublisherApplication = {
  id: string;
  publisherId: string;
  appKey: string;
  name: string;
  description: string | null;
  status: string;
};


export type ApplicationVersion = {
  id: string;
  version: string;

  // Technical/build lifecycle:
  // validated | build_failed | image_ready
  status: string;

  // Commercial publication lifecycle:
  // draft | published | retired
  publicationStatus: string;

  buildType: string;
  deploymentMode: string;
  createdAt: string;
};


export type ApplicationVersionList = {
  application: {
    id: string;
    publisherId: string;
    appKey: string;
    name: string;
    status: string;
  };

  count: number;

  items: ApplicationVersion[];
};


export type OfferEntitlement = {
  id?: string;
  code: string;
  value: Record<string, unknown> | null;
  status?: string;
};


export type ApplicationOffer = {
  id: string;

  applicationId: string;

  offerKey: string;

  name: string;

  description: string | null;

  deliveryType: string;

  status: string;

  versionPolicy: string;

  pinnedVersionId:
    string | null;

  autoUpgrade: boolean;

  entitlements:
    OfferEntitlement[];
};


export type OfferSavePayload = {
  offer_key?: string;

  name: string;

  description:
    string | null;

  delivery_type?:
    "hosted_dedicated";

  version_policy:
    string;

  pinned_version_id:
    string | null;

  auto_upgrade:
    boolean;

  entitlements: Array<{
    code: string;

    value:
      Record<string, unknown>;
  }>;
};


export async function createApplicationOffer(
  applicationId: string,
  payload: OfferSavePayload
): Promise<ApplicationOffer> {

  const response =
    await api.post<ApplicationOffer>(
      `/api/v1/applications/${applicationId}/offers`,
      payload
    );

  return response.data;
}


export async function updateApplicationOffer(
  offerId: string,
  payload: Omit<
    OfferSavePayload,
    "offer_key" |
    "delivery_type"
  >
): Promise<ApplicationOffer> {

  const response =
    await api.patch<ApplicationOffer>(
      `/api/v1/offers/${offerId}`,
      {
        name:
          payload.name,

        description:
          payload.description,

        version_policy:
          payload.version_policy,

        pinned_version_id:
          payload.pinned_version_id,

        auto_upgrade:
          payload.auto_upgrade,

        entitlements:
          payload.entitlements,
      }
    );

  return response.data;
}


export type ApplicationWorkspace = {
  versions: ApplicationVersionList;
  offers: ApplicationOffer[];
};


export async function loadPublishers():
Promise<PublisherWorkspace[]> {

  const response =
    await api.get<PublisherMembership[]>(
      "/api/v1/me/publishers"
    );

  return response.data
    .filter(
      (membership) =>
        membership.status === "active"
    )
    .map(
      (membership) =>
        membership.publisher
    );
}


export async function loadPublisherApplications(
  publisherId: string
): Promise<PublisherApplication[]> {

  const response =
    await api.get<PublisherApplication[]>(
      "/api/v1/applications"
    );

  return response.data.filter(
    (application) =>
      application.publisherId ===
      publisherId
  );
}


export type ApplicationUploadResult = {
  status: string;

  publisher: {
    id: string;
    name: string;
  };

  application: {
    id: string;
    appKey: string;
    name: string;
  };

  version: {
    id: string;
    version: string;
    buildType: string;
    deploymentMode: string;
  };

  package: {
    id: string;
    sha256: string;
    sizeBytes: number;
    status: string;
  };
};


export type StaticApplicationUploadPayload = {
  appName: string;
  appKey: string;
  version: string;
  description?: string;
  file: File;
};


export async function loadApplicationWorkspace(
  applicationId: string
): Promise<ApplicationWorkspace> {

  const [
    versionsResponse,
    offersResponse,
  ] = await Promise.all([

    api.get<ApplicationVersionList>(
      `/api/v1/applications/${applicationId}/versions`
    ),

    api.get<ApplicationOffer[]>(
      `/api/v1/applications/${applicationId}/offers`
    ),
  ]);


  return {
    versions:
      versionsResponse.data,

    offers:
      offersResponse.data,
  };
}


export async function uploadApplicationPackage(
  publisherId: string,
  file: File
): Promise<ApplicationUploadResult> {

  const formData =
    new FormData();

  formData.append(
    "file",
    file
  );

  const response =
    await api.post<ApplicationUploadResult>(
      `/api/v1/publishers/${publisherId}/applications/upload`,
      formData
    );

  return response.data;
}


export async function uploadStaticApplication(
  publisherId: string,
  payload: StaticApplicationUploadPayload
): Promise<ApplicationUploadResult> {

  const formData =
    new FormData();

  formData.append(
    "file",
    payload.file
  );

  formData.append(
    "app_name",
    payload.appName.trim()
  );

  formData.append(
    "app_key",
    payload.appKey.trim()
  );

  formData.append(
    "version",
    payload.version.trim()
  );

  formData.append(
    "description",
    (payload.description || "").trim()
  );

  const response =
    await api.post<ApplicationUploadResult>(
      `/api/v1/publishers/${publisherId}/applications/upload-static`,
      formData
    );

  return response.data;
}


export type ApplicationVersionDetail = {
  id: string;

  application: {
    id: string;
    publisherId: string;
    appKey: string;
    name: string;
  };

  version: string;

  status: string;

  publicationStatus: string;

  buildType: string;

  deploymentMode: string;

  package: {
    id: string;
    status: string;
    filename: string;
    sha256: string | null;
    sizeBytes: number;
  } | null;

  latestBuild: {
    id: string;
    status: string;
    imageRef: string | null;
    startedAt: string | null;
    finishedAt: string | null;
  } | null;

  createdAt: string;
};


export type ApplicationBuildResult = {
  status: string;

  build: {
    id: string;
    status: string;
    imageRef: string;
  };

  application: {
    id: string;
    name: string;
    appKey: string;
  };

  version: string;
};


export async function loadApplicationVersionDetail(
  versionId: string
): Promise<ApplicationVersionDetail> {

  const response =
    await api.get<ApplicationVersionDetail>(
      `/api/v1/application-versions/${versionId}`
    );

  return response.data;
}


export async function loadStaticApplicationContent(
  versionId: string
): Promise<string> {

  const response =
    await api.get<string>(
      `/api/v1/application-versions/${versionId}/static-content`,
      {
        responseType: "text",
      }
    );

  return response.data;
}


export async function buildApplicationPackage(
  packageId: string
): Promise<ApplicationBuildResult> {

  const response =
    await api.post<ApplicationBuildResult>(
      `/api/v1/application-packages/${packageId}/build`
    );

  return response.data;
}


export type ApplicationVersionLifecycleResult = {
  status: string;
  versionId: string;
  applicationId: string;
  version: string;
  buildType?: string;

  technicalStatus?: string;
  publicationStatus?: string;

  applicationStatus?: string;
};


export async function publishApplicationVersion(
  versionId: string
): Promise<ApplicationVersionLifecycleResult> {

  const response =
    await api.post<ApplicationVersionLifecycleResult>(
      `/api/v1/application-versions/${versionId}/publish`
    );

  return response.data;
}


export async function retireApplicationVersion(
  versionId: string
): Promise<ApplicationVersionLifecycleResult> {

  const response =
    await api.post<ApplicationVersionLifecycleResult>(
      `/api/v1/application-versions/${versionId}/retire`
    );

  return response.data;
}


export type OfferLifecycleResult = {
  status: string;
  offerId: string;
  applicationId?: string;
  offerKey?: string;
  updatedAt?: string;
};


export async function activateApplicationOffer(
  offerId: string
): Promise<OfferLifecycleResult> {

  const response =
    await api.post<OfferLifecycleResult>(
      `/api/v1/offers/${offerId}/activate`
    );

  return response.data;
}


export async function retireApplicationOffer(
  offerId: string
): Promise<OfferLifecycleResult> {

  const response =
    await api.post<OfferLifecycleResult>(
      `/api/v1/offers/${offerId}/retire`
    );

  return response.data;
}


// C1-D5.1: inspection-only source ZIP analyzer; not Publisher submission.
export type SourceValidationCheck = {
  id: string;
  label: string;
  status: "passed" | "failed" | "action_required" | "not_checked";
  code: string;
  location: string | null;
  problem: string;
  correction: string;
};

export type SourceAnalysisReport = {
  schemaVersion: string;
  sourceSha256: string;
  sourceRoot: string | null;
  filesInspected: number;
  detectedStack: string;
  classification: "supported" | "guided_mapping" | "unsupported";
  analysisPassed: boolean;
  publisherSubmissionEligible: boolean;
  publisherSubmissionReason: string;
  summary: { passed: number; failed: number; actionRequired: number; notChecked: number };
  checks: SourceValidationCheck[];
};

export async function analyzePublisherSource(
  publisherId: string, file: File
): Promise<SourceAnalysisReport> {
  const data = new FormData();
  data.append("file", file);
  const response = await api.post<SourceAnalysisReport>(
    `/api/v1/publishers/${publisherId}/containerization/analyze`, data,
  );
  return response.data;
}

// C1-D5.2: preparation only. It does not register, build or publish.
export type GeneratedAapsDraft = {
  stage: "C1-D5.2";
  status: "generated";
  sourceSha256: string;
  artifactSha256: string;
  artifactBytes: number;
  applicationKey: string;
  version: string;
  dockerfileMode: "preserved" | "generated";
  manifestStatus: "contract_validated";
  buildStatus: "not_checked";
  runtimeStatus: "not_checked";
  qualificationStatus: "not_checked";
  publisherSubmissionEligible: false;
  message: string;
};

export type GenerateAapsConfig = {
  appKey: string; appName: string; version: string;
  routesJson: string; schemaJson: string; outputDir: "dist" | "build";
};

function draftForm(file: File, settings: GenerateAapsConfig, mode: "preview" | "download") {
  const form = new FormData();
  form.append("file", file);
  form.append("app_key", settings.appKey);
  form.append("app_name", settings.appName);
  form.append("version", settings.version);
  form.append("routes_json", settings.routesJson);
  form.append("schema_json", settings.schemaJson);
  form.append("output_dir", settings.outputDir);
  form.append("mode", mode);
  return form;
}

export async function previewGeneratedAaps(publisherId: string, file: File, config: GenerateAapsConfig) {
  const response = await api.post<GeneratedAapsDraft>(
    `/api/v1/publishers/${publisherId}/containerization/generate`,
    draftForm(file, config, "preview"),
  );
  return response.data;
}

export async function downloadGeneratedAaps(publisherId: string, file: File, config: GenerateAapsConfig) {
  const response = await api.post<Blob>(
    `/api/v1/publishers/${publisherId}/containerization/generate`,
    draftForm(file, config, "download"), { responseType: "blob" },
  );
  return response.data;
}


// C1-D5.3: pre-submission execution of existing Docker build and disposable smoke services.
// This is NOT trusted Publisher submission evidence; the server-side C1-D2 gate remains intact.
export type DraftBuildTestCheck = Pick<SourceValidationCheck,
  "id" | "status" | "code" | "location" | "problem" | "correction">;

export type DraftBuildTestResult = {
  stage: "C1-D5.3";
  sourceSha256: string;
  artifactSha256: string;
  buildStatus: "passed" | "failed" | "action_required" | "not_checked";
  runtimeStatus: "passed" | "failed" | "action_required" | "not_checked";
  qualificationStatus: "not_checked";
  imageId: string | null;
  buildLog: string;
  smokeChecks: Record<string, boolean>;
  checks: Record<"build" | "runtime" | "qualification", DraftBuildTestCheck>;
  publisherSubmissionEligible: false;
};

export async function runPublisherDraftBuildTest(
  publisherId: string, file: File, config: GenerateAapsConfig,
  expectedSourceSha256: string, expectedArtifactSha256: string,
): Promise<DraftBuildTestResult> {
  const form = draftForm(file, config, "preview");
  form.delete("mode");
  form.append("expected_source_sha256", expectedSourceSha256);
  form.append("expected_artifact_sha256", expectedArtifactSha256);
  const response = await api.post<DraftBuildTestResult>(
    `/api/v1/publishers/${publisherId}/containerization/build-test`, form,
  );
  return response.data;
}


// C1-D5.4 uses only existing registry/build lifecycle plus a server-side C1-D2 gate.
export type RegisteredContainerizationDraft = {
  publisherId: string;
  packageId: string;
  versionId: string;
  buildId: string | null;
  artifactSha256: string;
};

export type ContainerizationReleaseReview = {
  status: string;
  eligible: boolean;
  code: string;
  problem: string;
  correction: string;
  qualificationStatus: string;
  qualificationFailureCode: string | null;
  artifactSha256: string;
  immutableImageId: string;
  packageId: string;
  versionId: string;
  buildId: string;
  publicationStatus?: "draft";
  message?: string;
};

export async function getContainerizationReleaseReview(draft: RegisteredContainerizationDraft) {
  if (!draft.buildId) throw new Error("Build this registered draft before release review.");
  const response = await api.get<ContainerizationReleaseReview>(
    `/api/v1/publishers/${draft.publisherId}/containerization/release-review`,
    { params: { package_id: draft.packageId, version_id: draft.versionId,
        build_id: draft.buildId, artifact_sha256: draft.artifactSha256 } },
  );
  return response.data;
}

export async function submitQualifiedContainerizationDraft(draft: RegisteredContainerizationDraft) {
  if (!draft.buildId) throw new Error("Registered build is required.");
  const form = new FormData();
  form.append("package_id", draft.packageId);
  form.append("version_id", draft.versionId);
  form.append("build_id", draft.buildId);
  form.append("artifact_sha256", draft.artifactSha256);
  const response = await api.post<ContainerizationReleaseReview>(
    `/api/v1/publishers/${draft.publisherId}/containerization/submit`, form,
  );
  return response.data;
}



// C1-D5.4 recovery only: read existing publisher/version records; NEVER upload or mutate.
// The existing backend release-review remains authoritative for release eligibility.
export async function resumeExistingContainerizationDraft(
  publisherId: string, appKey: string, version: string, artifactSha256: string,
): Promise<RegisteredContainerizationDraft> {
  const applications = await loadPublisherApplications(publisherId);
  const application = applications.find((candidate) => candidate.appKey === appKey);
  if (!application) {
    throw new Error("C1D54_RESUME_NOT_FOUND: No registered application with this key belongs to the selected publisher.");
  }
  const response = await api.get<ApplicationVersionList>(
    `/api/v1/applications/${application.id}/versions`,
  );
  if (response.data.application.publisherId !== publisherId ||
      response.data.application.appKey !== appKey) {
    throw new Error("C1D54_RESUME_SCOPE: Registered application does not match this publisher/key.");
  }
  const item = response.data.items.find((candidate) => candidate.version === version);
  if (!item) {
    throw new Error("C1D54_RESUME_VERSION_NOT_FOUND: No previously registered version matches this draft.");
  }
  const detail = await loadApplicationVersionDetail(item.id);
  if (detail.id !== item.id || detail.version !== version ||
      detail.application.id !== application.id ||
      detail.application.publisherId !== publisherId ||
      detail.application.appKey !== appKey ||
      detail.publicationStatus !== "draft" || detail.buildType !== "dockerfile") {
    throw new Error("C1D54_RESUME_NOT_DRAFT: Existing version is not the selected unpublished Docker draft.");
  }
  if (!detail.package || detail.package.status !== "validated" ||
      detail.package.sha256 !== artifactSha256) {
    throw new Error("C1D54_RESUME_SHA_MISMATCH: Registered ZIP does not match the exact currently generated and tested artifact. No recovery performed.");
  }
  return {
    publisherId,
    packageId: detail.package.id,
    versionId: detail.id,
    buildId: detail.latestBuild?.status === "ready" ? detail.latestBuild.id : null,
    artifactSha256,
  };
}

// Compare the exact binary ZIP delivered by the generator before registering it.
export async function exactAapsBlobSha256(blob: Blob): Promise<string> {
  const bytes = await blob.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (n) => n.toString(16).padStart(2, "0")).join("");
}
