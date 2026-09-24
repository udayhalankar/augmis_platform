// apps/web/src/app/publisher/page.tsx
"use client";

import {
  useCallback,
  useEffect,
  useState,
} from "react";

import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  MenuItem,
  Select,
  Stack,
  Typography,
} from "@mui/material";

import OfferLifecycleDialog, {
  OfferLifecycleAction,
} from "@/components/offer-lifecycle-dialog";

import BuildOutlined
  from "@mui/icons-material/BuildOutlined";

import VisibilityOutlined
  from "@mui/icons-material/VisibilityOutlined";


import axios
  from "axios";

import UploadFileOutlined
  from "@mui/icons-material/UploadFileOutlined";

import ApplicationUploadDialog
  from "@/components/application-upload-dialog";

import StaticAppPreviewDialog
  from "@/components/static-app-preview-dialog";

import RefreshOutlined
  from "@mui/icons-material/RefreshOutlined";

import AppShell
  from "@/components/app-shell";

import ProtectedRoute
  from "@/components/protected-route";

import AddOutlined
  from "@mui/icons-material/AddOutlined";

import EditOutlined
  from "@mui/icons-material/EditOutlined";

import OfferEditorDialog
  from "@/components/offer-editor-dialog";

import {
  ApplicationOffer,
  ApplicationVersion,
  ApplicationUploadResult,
  ApplicationWorkspace,
  loadApplicationWorkspace,
  loadPublisherApplications,
  ApplicationBuildResult,
  ApplicationVersionDetail,
  buildApplicationPackage,
  loadStaticApplicationContent,
  loadApplicationVersionDetail,
  publishApplicationVersion,
  retireApplicationVersion,
  activateApplicationOffer,
  retireApplicationOffer,
  loadPublishers,
  PublisherApplication,
  PublisherWorkspace,
} from "@/lib/publisher-center";


function statusColor(
  status: string
):
  | "success"
  | "warning"
  | "error"
  | "default"
  | "info" {

  const normalized =
    status.toLowerCase();

  if (
    normalized === "active" ||
    normalized === "image_ready" ||
    normalized === "ready" ||
    normalized === "validated" ||
    normalized === "published"
  ) {

    return "success";
  }


  if (
    normalized === "draft" ||
    normalized === "building"
  ) {

    return "warning";
  }


  if (
    normalized === "failed" ||
    normalized === "build_failed" ||
    normalized === "rejected"
  ) {

    return "error";
  }


  if (
    normalized === "retired"
  ) {

    return "default";
  }


  return "info";
}


function formatStatus(
  value: string
): string {

  return value
    .replace(
      /_/g,
      " "
    )
    .replace(
      /\b\w/g,
      (character) =>
        character.toUpperCase()
    );
}


function formatDate(
  value: string
): string {

  return new Intl.DateTimeFormat(
    undefined,
    {
      dateStyle: "medium",
    }
  ).format(
    new Date(value)
  );
}


export default function PublisherPage() {

  const [
  buildingVersionId,
  setBuildingVersionId,
  ] = useState("");

  const [
  offerEditorOpen,
  setOfferEditorOpen,
  ] = useState(false);


  const [
    editingOffer,
    setEditingOffer,
  ] =
    useState<
      ApplicationOffer | null
    >(null);

  const [
    offerLifecycleId,
    setOfferLifecycleId,
  ] = useState("");


  const [
    offerMessage,
    setOfferMessage,
  ] = useState("");


  const [
    offerError,
    setOfferError,
  ] = useState("");


  const [
    buildMessage,
    setBuildMessage,
  ] = useState("");


  const [
    buildError,
    setBuildError,
  ] = useState("");

  const [
    previewOpen,
    setPreviewOpen,
  ] = useState(false);


  const [
    previewVersionLabel,
    setPreviewVersionLabel,
  ] = useState("");


  const [
    previewHtml,
    setPreviewHtml,
  ] = useState("");


  const [
    previewLoading,
    setPreviewLoading,
  ] = useState(false);


  const [
    previewError,
    setPreviewError,
  ] = useState("");


  const [
    lifecycleVersionId,
    setLifecycleVersionId,
  ] = useState("");


  const [
    lifecycleMessage,
    setLifecycleMessage,
  ] = useState("");


  const [
    lifecycleError,
    setLifecycleError,
  ] = useState("");


  const openCreateOffer =
  () => {

    setEditingOffer(null);

    setOfferEditorOpen(
      true
    );
  };


const openEditOffer =
  (
    offer:
      ApplicationOffer
  ) => {

    setEditingOffer(
      offer
    );

    setOfferEditorOpen(
      true
    );
  };


const handleOfferLifecycle =
  async (
    offer:
      ApplicationOffer,

    action:
      "activate" |
      "retire"
  ) => {

    if (
      action === "retire" &&
      !window.confirm(
        `Retire offer ${offer.name}?`
      )
    ) {
      return;
    }


    setOfferLifecycleId(
      offer.id
    );

    setOfferMessage(
      ""
    );

    setOfferError(
      ""
    );


    try {

      if (
        action === "activate"
      ) {

        await activateApplicationOffer(
          offer.id
        );

        setOfferMessage(
          `${offer.name} activated successfully.`
        );

      } else {

        await retireApplicationOffer(
          offer.id
        );

        setOfferMessage(
          `${offer.name} retired successfully.`
        );
      }


      if (
        selectedApplicationId
      ) {

        await loadWorkspace(
          selectedApplicationId
        );
      }

    } catch (error) {

      if (
        axios.isAxiosError(
          error
        )
      ) {

        const detail =
          error.response?.data
            ?.detail;


        if (
          typeof detail ===
          "string"
        ) {

          setOfferError(
            detail
          );

        } else {

          setOfferError(
            `Offer could not be ${action === "activate" ? "activated" : "retired"}.`
          );
        }

      } else if (
        error instanceof Error
      ) {

        setOfferError(
          error.message
        );

      } else {

        setOfferError(
          `Offer could not be ${action === "activate" ? "activated" : "retired"}.`
        );
      }

    } finally {

      setOfferLifecycleId(
        ""
      );
    }
  };


const refreshWorkspace =
  async () => {

    if (
      selectedApplicationId
    ) {

      await loadWorkspace(
        selectedApplicationId
      );
    }
  };

  const handlePreviewVersion =
    async (
      version:
        ApplicationVersion
          ) => {

            setPreviewOpen(
              true
            );

            setPreviewVersionLabel(
              version.version
            );

            setPreviewHtml(
              ""
            );

            setPreviewError(
              ""
            );

            setPreviewLoading(
              true
            );


            try {

              const html =
                await loadStaticApplicationContent(
                  version.id
                );


              setPreviewHtml(
                html
              );

            } catch (error) {

              if (
                axios.isAxiosError(
                  error
                )
              ) {

                const detail =
                  error.response?.data
                    ?.detail;


                if (
                  typeof detail ===
                  "string"
                ) {

                  setPreviewError(
                    detail
                  );

                } else {

                  setPreviewError(
                    "Static application preview could not be loaded."
                  );
                }

              } else if (
                error instanceof Error
              ) {

                setPreviewError(
                  error.message
                );

              } else {

                setPreviewError(
                  "Static application preview could not be loaded."
                );
              }

            } finally {

              setPreviewLoading(
                false
              );
            }
          };

  const handleVersionLifecycle =
    async (
      version:
        ApplicationVersion,

      action:
        "publish" |
        "retire"
    ) => {

      if (
        action === "retire" &&
        !window.confirm(
          `Retire ${selectedApplication?.name || "this application"} version ${version.version}?`
        )
      ) {
        return;
      }


      setLifecycleVersionId(
        version.id
      );

      setLifecycleMessage(
        ""
      );

      setLifecycleError(
        ""
      );


      try {

        const result =
          action === "publish"
            ? await publishApplicationVersion(
                version.id
              )
            : await retireApplicationVersion(
                version.id
              );


        setLifecycleMessage(
          action === "publish"
            ? `${selectedApplication?.name || "Application"} ${result.version} published successfully.`
            : `${selectedApplication?.name || "Application"} ${result.version} retired successfully.`
        );


        if (
          selectedPublisherId
        ) {

          await loadApplications(
            selectedPublisherId
          );
        }


        if (
          selectedApplicationId
        ) {

          await loadWorkspace(
            selectedApplicationId
          );
        }

      } catch (error) {

        if (
          axios.isAxiosError(
            error
          )
        ) {

          const detail =
            error.response?.data
              ?.detail;


          if (
            typeof detail ===
            "string"
          ) {

            setLifecycleError(
              detail
            );

          } else if (
            typeof detail?.message ===
            "string"
          ) {

            setLifecycleError(
              detail.message
            );

          } else {

            setLifecycleError(
              `Application could not be ${action === "publish" ? "published" : "retired"}.`
            );
          }

        } else if (
          error instanceof Error
        ) {

          setLifecycleError(
            error.message
          );

        } else {

          setLifecycleError(
            `Application could not be ${action === "publish" ? "published" : "retired"}.`
          );
        }

      } finally {

        setLifecycleVersionId(
          ""
        );
      }
    };


  const handleBuildVersion =
  async (
    versionId: string
  ) => {

    setBuildingVersionId(
      versionId
    );

    setBuildMessage("");

    setBuildError("");


    try {

      const detail:
        ApplicationVersionDetail =
          await loadApplicationVersionDetail(
            versionId
          );


      if (!detail.package) {

        throw new Error(
          "This version has no linked application package."
        );
      }


      const result:
        ApplicationBuildResult =
          await buildApplicationPackage(
            detail.package.id
          );


      setBuildMessage(
        `${result.application.name} ${result.version} built successfully as ${result.build.imageRef}`
      );


      if (
        selectedApplicationId
      ) {

        await loadWorkspace(
          selectedApplicationId
        );
      }

    } catch (error) {

      if (
        axios.isAxiosError(
          error
        )
      ) {

        const detail =
          error.response?.data
            ?.detail;


        if (
          typeof detail ===
          "string"
        ) {

          setBuildError(
            detail
          );

        } else if (
          typeof detail?.message ===
          "string"
        ) {

          setBuildError(
            detail.message
          );

        } else {

          setBuildError(
            "Application build failed."
          );
        }

      } else if (
        error instanceof Error
      ) {

        setBuildError(
          error.message
        );

      } else {

        setBuildError(
          "Application build failed."
        );
      }

    } finally {

      setBuildingVersionId(
        ""
      );
    }
  };

  

  const [
    publishers,
    setPublishers,
  ] = useState<
    PublisherWorkspace[]
  >([]);

  const handleUploaded =
  async (
    result:
      ApplicationUploadResult
  ) => {

    if (
      !selectedPublisherId
    ) {

      return;
    }


    await loadApplications(
      selectedPublisherId
    );


    setSelectedApplicationId(
      result.application.id
    );


    await loadWorkspace(
      result.application.id
    );
  };

  const [
  uploadOpen,
  setUploadOpen,
  ] = useState(false);

  const [
    selectedPublisherId,
    setSelectedPublisherId,
  ] = useState("");


  const [
    applications,
    setApplications,
  ] = useState<
    PublisherApplication[]
  >([]);


  const [
    selectedApplicationId,
    setSelectedApplicationId,
  ] = useState("");

  const selectedPublisher =
  publishers.find(
    (publisher) =>
      publisher.id ===
      selectedPublisherId
  ) ?? null;

  const [
    workspace,
    setWorkspace,
  ] =
    useState<
      ApplicationWorkspace | null
    >(null);


  const [
    loadingPublishers,
    setLoadingPublishers,
  ] = useState(true);


  const [
    loadingApplications,
    setLoadingApplications,
  ] = useState(false);


  const [
    loadingWorkspace,
    setLoadingWorkspace,
  ] = useState(false);


  const [
    error,
    setError,
  ] = useState("");


  // =====================================================
  // LOAD PUBLISHERS
  // =====================================================

  const loadPublisherContext =
    useCallback(
      async () => {

        setLoadingPublishers(
          true
        );

        setError("");

        try {

          const result =
            await loadPublishers();

          setPublishers(
            result
          );

          if (
            result.length > 0
          ) {

            setSelectedPublisherId(
              (current) =>
                current ||
                result[0].id
            );

          }

        } catch {

          setError(
            "Publisher workspaces could not be loaded."
          );

        } finally {

          setLoadingPublishers(
            false
          );
        }
      },
      []
    );


  // =====================================================
  // LOAD APPLICATIONS
  // =====================================================

  const loadApplications =
    useCallback(
      async (
        publisherId: string
      ) => {

        if (!publisherId) {
          return;
        }

        setLoadingApplications(
          true
        );

        setError("");

        setWorkspace(
          null
        );

        try {

          const result =
            await loadPublisherApplications(
              publisherId
            );

          setApplications(
            result
          );


          setSelectedApplicationId(
            (current) => {

              if (
                current &&
                result.some(
                  (application) =>
                    application.id ===
                    current
                )
              ) {

                return current;
              }

              return (
                result[0]?.id ??
                ""
              );
            }
          );

        } catch {

          setError(
            "Applications could not be loaded."
          );

        } finally {

          setLoadingApplications(
            false
          );
        }
      },
      []
    );


  // =====================================================
  // LOAD APPLICATION WORKSPACE
  // =====================================================

  const loadWorkspace =
    useCallback(
      async (
        applicationId: string
      ) => {

        if (!applicationId) {

          setWorkspace(
            null
          );

          return;
        }


        setLoadingWorkspace(
          true
        );

        setError("");

        try {

          const result =
            await loadApplicationWorkspace(
              applicationId
            );

          setWorkspace(
            result
          );

        } catch {

          setError(
            "Application versions and offers could not be loaded."
          );

        } finally {

          setLoadingWorkspace(
            false
          );
        }
      },
      []
    );


  // =====================================================
  // INITIAL PUBLISHER LOAD
  // =====================================================

  useEffect(
    () => {

      loadPublisherContext();

    },
    [
      loadPublisherContext,
    ]
  );


  // =====================================================
  // PUBLISHER CHANGED
  // =====================================================

  useEffect(
    () => {

      if (
        selectedPublisherId
      ) {

        loadApplications(
          selectedPublisherId
        );
      }

    },
    [
      selectedPublisherId,
      loadApplications,
    ]
  );


  // =====================================================
  // APPLICATION CHANGED
  // =====================================================

  useEffect(
    () => {

      if (
        selectedApplicationId
      ) {

        loadWorkspace(
          selectedApplicationId
        );

      } else {

        setWorkspace(
          null
        );
      }

    },
    [
      selectedApplicationId,
      loadWorkspace,
    ]
  );


  const selectedApplication =
    applications.find(
      (application) =>
        application.id ===
        selectedApplicationId
    ) ?? null;


  const refreshAll =
    async () => {

      if (
        selectedPublisherId
      ) {

        await loadApplications(
          selectedPublisherId
        );
      }

      if (
        selectedApplicationId
      ) {

        await loadWorkspace(
          selectedApplicationId
        );
      }
    };


  return (
    <ProtectedRoute>

      <AppShell>

        <Stack
          spacing={3}
        >

          {/* ===========================================
              HEADER
          ============================================ */}

          <Box
            sx={{
              display: "flex",

              alignItems:
                "flex-start",

              justifyContent:
                "space-between",

              gap: 2,

              flexWrap:
                "wrap",
            }}
          >

            <Box>

              <Typography
                sx={{
                  fontSize: 12,

                  color:
                    "text.secondary",

                  textTransform:
                    "uppercase",

                  letterSpacing:
                    0.8,

                  mb: 0.5,
                }}
              >
                Publisher Workspace
              </Typography>


              <Typography
                variant="h4"
              >
                Publisher Center
              </Typography>


              <Typography
                sx={{
                  mt: 0.5,

                  color:
                    "text.secondary",
                }}
              >
                Manage applications,
                immutable versions,
                builds and commercial
                offers.
              </Typography>

            </Box>


            <Stack
                direction="row"
                spacing={1.5}
                sx={{
                  alignItems: "center",
                  flexWrap: "wrap",
                }}
              >

                {publishers.length > 0 && (

                  <Select
                    size="small"

                    value={
                      selectedPublisherId
                    }

                    onChange={
                      (event) =>
                        setSelectedPublisherId(
                          event.target.value
                        )
                    }

                    sx={{
                      minWidth: 230,
                      bgcolor: "#ffffff",
                    }}
                  >

                    {publishers.map(
                      (publisher) => (

                        <MenuItem
                          key={
                            publisher.id
                          }
                          value={
                            publisher.id
                          }
                        >
                          {publisher.name}
                        </MenuItem>

                      )
                    )}

                  </Select>

                )}


                <Button
                  variant="contained"

                  startIcon={
                    <UploadFileOutlined />
                  }

                  disabled={
                    !selectedPublisherId
                  }

                  onClick={
                    () =>
                      setUploadOpen(
                        true
                      )
                  }
                >
                  Upload Application
                </Button>


                <Button
                  variant="outlined"

                  startIcon={
                    <RefreshOutlined />
                  }

                  onClick={
                    refreshAll
                  }

                  disabled={
                    loadingApplications ||
                    loadingWorkspace
                  }
                >
                  Refresh
                </Button>

              </Stack>

          </Box>


          {/* ===========================================
              ERROR
          ============================================ */}

          {error && (

            <Alert
              severity="error"
            >
              {error}
            </Alert>

          )}


          {/* ===========================================
              INITIAL LOADING
          ============================================ */}

          {loadingPublishers && (

            <Box
              sx={{
                minHeight: 280,

                bgcolor:
                  "#ffffff",

                border:
                  "1px solid",

                borderColor:
                  "divider",

                display:
                  "grid",

                placeItems:
                  "center",
              }}
            >
              <CircularProgress
                size={28}
              />
            </Box>

          )}


          {!loadingPublishers &&
            publishers.length === 0 && (

            <Alert
              severity="info"
            >
              Your account has no
              active publisher
              workspace.
            </Alert>

          )}


          {!loadingPublishers &&
            publishers.length > 0 && (

            <Box
              sx={{
                display:
                  "grid",

                gridTemplateColumns: {
                  xs:
                    "1fr",

                  lg:
                    "330px minmax(0, 1fr)",
                },

                gap: 2,

                alignItems:
                  "start",
              }}
            >

              {/* =======================================
                  APPLICATION LIST
              ======================================== */}

              <Box
                sx={{
                  bgcolor:
                    "#ffffff",

                  border:
                    "1px solid",

                  borderColor:
                    "divider",
                }}
              >

                <Box
                  sx={{
                    px: 2.5,
                    py: 1.8,

                    borderBottom:
                      "1px solid",

                    borderColor:
                      "divider",
                  }}
                >

                  <Typography
                    sx={{
                      fontWeight:
                        600,
                    }}
                  >
                    Applications
                  </Typography>


                  <Typography
                    sx={{
                      mt: 0.25,

                      fontSize:
                        12,

                      color:
                        "text.secondary",
                    }}
                  >
                    {applications.length}
                    {" "}
                    registered
                  </Typography>

                </Box>


                {loadingApplications ? (

                  <Box
                    sx={{
                      py: 6,

                      display:
                        "grid",

                      placeItems:
                        "center",
                    }}
                  >
                    <CircularProgress
                      size={24}
                    />
                  </Box>

                ) : applications.length === 0 ? (

                  <Box
                    sx={{
                      p: 2.5,

                      fontSize:
                        13,

                      color:
                        "text.secondary",
                    }}
                  >
                    No applications
                    registered for this
                    publisher.
                  </Box>

                ) : (

                  applications.map(
                    (
                      application,
                      index
                    ) => {

                      const active =
                        application.id ===
                        selectedApplicationId;

                      return (

                        <Box
                          key={
                            application.id
                          }

                          onClick={
                            () =>
                              setSelectedApplicationId(
                                application.id
                              )
                          }

                          sx={{
                            px: 2.5,
                            py: 2,

                            cursor:
                              "pointer",

                            bgcolor:
                              active
                                ? "#edf4f8"
                                : "#ffffff",

                            borderLeft:
                              active
                                ? "3px solid #1f5f8b"
                                : "3px solid transparent",

                            borderBottom:
                              index <
                              applications.length - 1
                                ? "1px solid"
                                : "none",

                            borderColor:
                              active
                                ? "#1f5f8b"
                                : "divider",

                            "&:hover": {
                              bgcolor:
                                active
                                  ? "#edf4f8"
                                  : "#f8fafb",
                            },
                          }}
                        >

                          <Typography
                            sx={{
                              fontSize:
                                14,

                              fontWeight:
                                600,
                            }}
                          >
                            {application.name}
                          </Typography>


                          <Typography
                            sx={{
                              mt: 0.4,

                              fontSize:
                                11,

                              color:
                                "text.secondary",

                              fontFamily:
                                "monospace",
                            }}
                          >
                            {application.appKey}
                          </Typography>


                          <Chip
                            size="small"

                            label={
                              formatStatus(
                                application.status
                              )
                            }

                            color={
                              statusColor(
                                application.status
                              )
                            }

                            variant="outlined"

                            sx={{
                              mt: 1.2,

                              height: 22,

                              fontSize:
                                10,
                            }}
                          />

                        </Box>

                      );
                    }
                  )

                )}

              </Box>

              

              {/* =======================================
                  APPLICATION DETAIL
              ======================================== */}

              <Box
                sx={{
                  minWidth: 0,
                }}
              >

                {buildMessage && (

                <Alert
                  severity="success"
                  onClose={
                    () =>
                      setBuildMessage("")
                  }
                >
                  {buildMessage}
                </Alert>

              )}


              {buildError && (

                <Alert
                  severity="error"
                  onClose={
                    () =>
                      setBuildError("")
                  }
                >
                  {buildError}
                </Alert>

              )}


              {lifecycleMessage && (

                <Alert
                  severity="success"
                  onClose={
                    () =>
                      setLifecycleMessage("")
                  }
                >
                  {lifecycleMessage}
                </Alert>

              )}


              {lifecycleError && (

                <Alert
                  severity="error"
                  onClose={
                    () =>
                      setLifecycleError("")
                  }
                >
                  {lifecycleError}
                </Alert>

              )}


              {offerMessage && (

                <Alert
                  severity="success"
                  onClose={
                    () =>
                      setOfferMessage("")
                  }
                >
                  {offerMessage}
                </Alert>

              )}


              {offerError && (

                <Alert
                  severity="error"
                  onClose={
                    () =>
                      setOfferError("")
                  }
                >
                  {offerError}
                </Alert>

              )}

                {!selectedApplication && (

                  <Box
                    sx={{
                      bgcolor:
                        "#ffffff",

                      border:
                        "1px solid",

                      borderColor:
                        "divider",

                      p: 3,

                      color:
                        "text.secondary",
                    }}
                  >
                    Select an application.
                  </Box>

                )}


                {selectedApplication && (

                  <Stack spacing={2}>

                    {/* APP SUMMARY */}

                    <Box
                      sx={{
                        bgcolor:
                          "#ffffff",

                        border:
                          "1px solid",

                        borderColor:
                          "divider",
                      }}
                    >

                      <Box
                        sx={{
                          px: 2.5,
                          py: 2,

                          display:
                            "flex",

                          justifyContent:
                            "space-between",

                          gap: 2,

                          flexWrap:
                            "wrap",
                        }}
                      >

                        <Box>

                          <Typography
                            sx={{
                              fontSize:
                                20,

                              fontWeight:
                                600,
                            }}
                          >
                            {selectedApplication.name}
                          </Typography>


                          <Typography
                            sx={{
                              mt: 0.4,

                              fontSize:
                                12,

                              color:
                                "text.secondary",
                            }}
                          >
                            {selectedApplication.description ??
                              "No application description."}
                          </Typography>

                        </Box>


                        <Chip
                          size="small"

                          label={
                            formatStatus(
                              selectedApplication.status
                            )
                          }

                          color={
                            statusColor(
                              selectedApplication.status
                            )
                          }

                          variant="outlined"
                        />

                      </Box>


                      <Box
                        sx={{
                          px: 2.5,
                          py: 1.4,

                          bgcolor:
                            "#f7f9fa",

                          borderTop:
                            "1px solid",

                          borderColor:
                            "divider",

                          display:
                            "flex",

                          gap: 4,

                          flexWrap:
                            "wrap",
                        }}
                      >

                        <MetaItem
                          label="App Key"
                          value={
                            selectedApplication.appKey
                          }
                        />

                        <MetaItem
                          label="Application ID"
                          value={
                            selectedApplication.id
                          }
                          mono
                        />

                      </Box>

                    </Box>


                    {loadingWorkspace ? (

                      <Box
                        sx={{
                          minHeight:
                            250,

                          bgcolor:
                            "#ffffff",

                          border:
                            "1px solid",

                          borderColor:
                            "divider",

                          display:
                            "grid",

                          placeItems:
                            "center",
                        }}
                      >
                        <CircularProgress
                          size={26}
                        />
                      </Box>

                    ) : workspace && (

                      <>

                        {/* ===============================
                            VERSIONS
                        ================================ */}

                        <VersionPanel
                          versions={
                            workspace
                              .versions
                              .items
                          }

                          buildingVersionId={
                            buildingVersionId
                          }

                          onBuild={
                            handleBuildVersion
                          }

                          onPreview={
                            handlePreviewVersion
                          }

                          lifecycleVersionId={
                            lifecycleVersionId
                          }

                          onPublish={
                            (version) =>
                              handleVersionLifecycle(
                                version,
                                "publish"
                              )
                          }

                          onRetire={
                            (version) =>
                              handleVersionLifecycle(
                                version,
                                "retire"
                              )
                          }
                        />



                        {/* ===============================
                            OFFERS
                        ================================ */}

                        <OfferPanel
                          offers={
                            workspace.offers
                          }

                          onCreate={
                            openCreateOffer
                          }

                          onEdit={
                            openEditOffer
                          }

                          busyOfferId={
                            offerLifecycleId
                          }

                          onActivate={
                            (offer) =>
                              handleOfferLifecycle(
                                offer,
                                "activate"
                              )
                          }

                          onRetire={
                            (offer) =>
                              handleOfferLifecycle(
                                offer,
                                "retire"
                              )
                          }
                        />

                      </>

                    )}

                  </Stack>

                )}

              </Box>

            </Box>

          )}

        </Stack>

<StaticAppPreviewDialog
  open={
    previewOpen
  }

  applicationName={
    selectedApplication
      ?.name ||
    "Static Application"
  }

  version={
    previewVersionLabel
  }

  html={
    previewHtml
  }

  loading={
    previewLoading
  }

  error={
    previewError
  }

  onClose={
    () => {

      setPreviewOpen(
        false
      );

      setPreviewVersionLabel(
        ""
      );

      setPreviewHtml(
        ""
      );

      setPreviewError(
        ""
      );
    }
  }
/>

        {selectedApplication &&
  workspace && (

  <OfferEditorDialog
    open={
      offerEditorOpen
    }

    applicationId={
      selectedApplication.id
    }

    versions={
      workspace
        .versions
        .items
    }

    offer={
      editingOffer
    }

    onClose={
      () => {

        setOfferEditorOpen(
          false
        );

        setEditingOffer(
          null
        );
      }
    }

    onSaved={
      refreshWorkspace
    }
  />

)}

          {selectedPublisher && (

  <ApplicationUploadDialog
    open={
      uploadOpen
    }

    publisherId={
      selectedPublisher.id
    }

    publisherName={
      selectedPublisher.name
    }

    onClose={
      () =>
        setUploadOpen(
          false
        )
    }

    onUploaded={
      handleUploaded
    }
  />

)}


      </AppShell>

    </ProtectedRoute>
  );
}


function MetaItem({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {

  return (
    <Box>

      <Typography
        sx={{
          fontSize: 10,

          color:
            "text.secondary",

          textTransform:
            "uppercase",

          letterSpacing:
            0.5,
        }}
      >
        {label}
      </Typography>


      <Typography
        sx={{
          mt: 0.3,

          fontSize: 12,

          fontWeight:
            600,

          fontFamily:
            mono
              ? "monospace"
              : "inherit",

          wordBreak:
            "break-all",
        }}
      >
        {value}
      </Typography>

    </Box>
  );
}


function VersionPanel({
  versions,
  buildingVersionId,
  onBuild,
  onPreview,
  lifecycleVersionId,
  onPublish,
  onRetire,
}: {
  versions:
    ApplicationVersion[];

  buildingVersionId:
    string;

  onBuild: (
    versionId: string
  ) => Promise<void>;

  onPreview: (
    version:
      ApplicationVersion
  ) => Promise<void>;

  lifecycleVersionId:
    string;

  onPublish: (
    version:
      ApplicationVersion
  ) => Promise<void>;

  onRetire: (
    version:
      ApplicationVersion
  ) => Promise<void>;
}){

  return (
    <Box
      sx={{
        bgcolor: "#ffffff",

        border:
          "1px solid",

        borderColor:
          "divider",
      }}
    >

      <Box
        sx={{
          px: 2.5,
          py: 1.7,

          borderBottom:
            "1px solid",

          borderColor:
            "divider",

          display:
            "flex",

          justifyContent:
            "space-between",

          gap: 2,
        }}
      >

        <Box>

          <Typography
            sx={{
              fontWeight:
                600,
            }}
          >
            Versions
          </Typography>


          <Typography
            sx={{
              fontSize: 12,

              color:
                "text.secondary",
            }}
          >
            Immutable application
            versions
          </Typography>

        </Box>


        <Typography
          sx={{
            fontSize: 12,

            color:
              "text.secondary",
          }}
        >
          {versions.length}
        </Typography>

      </Box>


      {versions.length === 0 ? (

        <Box
          sx={{
            p: 2.5,

            fontSize: 13,

            color:
              "text.secondary",
          }}
        >
          No versions registered.
        </Box>

      ) : (

        <Box
          sx={{
            overflowX:
              "auto",
          }}
        >

          <Box
            sx={{
              minWidth: 1120,
            }}
          >

            <Box
              sx={{
                display:
                  "grid",

                gridTemplateColumns:
                  "110px 135px 130px 130px 140px 1fr 250px",

                px: 2.5,
                py: 1,

                bgcolor:
                  "#f7f9fa",
              }}
            >

              {[
                "Version",
                "Technical",
                "Publication",
                "Build Type",
                "Deployment",
                "Created",
                "Action",
              ].map(
                (column) => (

                  <Typography
                    key={
                      column
                    }
                    sx={{
                      fontSize: 10,

                      fontWeight:
                        600,

                      color:
                        "text.secondary",

                      textTransform:
                        "uppercase",

                      letterSpacing:
                        0.5,
                    }}
                  >
                    {column}
                  </Typography>

                )
              )}

            </Box>


            {versions.map(
              (version) => {

                const isStatic =
                  version.buildType ===
                    "static_web";


                const canBuild =
                  !isStatic &&
                  (
                    version.status ===
                      "validated" ||
                    version.status ===
                      "build_failed"
                  );


                const building =
                  buildingVersionId ===
                  version.id;
                

                const lifecycleBusy =
                  lifecycleVersionId ===
                  version.id;


                const normalizedStatus =
                  String(
                    version.status || ""
                  ).toLowerCase();


                const publicationStatus =
                  String(
                    version.publicationStatus ||
                    "draft"
                  ).toLowerCase();


                const technicallyReady =
                  (
                    isStatic &&
                    normalizedStatus ===
                      "validated"
                  ) ||
                  (
                    !isStatic &&
                    normalizedStatus ===
                      "image_ready"
                  );


                const canPublish =
                  technicallyReady &&
                  publicationStatus ===
                    "draft";


                const canRetire =
                  publicationStatus ===
                    "published";

                return (

                  <Box
                    key={
                      version.id
                    }
                    sx={{
                      display:
                        "grid",

                      gridTemplateColumns:
                        "110px 135px 130px 130px 140px 1fr 250px",

                      px: 2.5,
                      py: 1.5,

                      borderTop:
                        "1px solid",

                      borderColor:
                        "divider",

                      alignItems:
                        "center",
                    }}
                  >

                    <Typography
                      sx={{
                        fontSize:
                          13,

                        fontWeight:
                          600,

                        fontFamily:
                          "monospace",
                      }}
                    >
                      {version.version}
                    </Typography>


                    <Box>

                      <Chip
                        size="small"

                        label={
                          formatStatus(
                            version.status
                          )
                        }

                        color={
                          statusColor(
                            version.status
                          )
                        }

                        variant="outlined"

                        sx={{
                          height: 22,

                          fontSize:
                            10,
                        }}
                      />

                    </Box>


                    <Box>

                      <Chip
                        size="small"

                        label={
                          formatStatus(
                            version.publicationStatus ||
                            "draft"
                          )
                        }

                        color={
                          statusColor(
                            version.publicationStatus ||
                            "draft"
                          )
                        }

                        variant="outlined"

                        sx={{
                          height: 22,

                          fontSize:
                            10,
                        }}
                      />

                    </Box>


                    <Typography
                      sx={{
                        fontSize:
                          12,
                      }}
                    >
                      {version.buildType}
                    </Typography>


                    <Typography
                      sx={{
                        fontSize:
                          12,
                      }}
                    >
                      {version.deploymentMode}
                    </Typography>


                    <Typography
                      sx={{
                        fontSize:
                          12,

                        color:
                          "text.secondary",
                      }}
                    >
                      {formatDate(
                        version.createdAt
                      )}
                    </Typography>


                    <Box
                      sx={{
                        display:
                          "flex",

                        alignItems:
                          "center",

                        gap:
                          0.75,

                        flexWrap:
                          "wrap",
                      }}
                    >

                      {isStatic && (

                        <Button
                          size="small"
                          variant="outlined"

                          startIcon={
                            <VisibilityOutlined />
                          }

                          disabled={
                            lifecycleBusy
                          }

                          onClick={
                            () =>
                              onPreview(
                                version
                              )
                          }
                        >
                          Preview
                        </Button>

                      )}


                      {canBuild && (

                        <Button
                          size="small"
                          variant="outlined"

                          startIcon={
                            building
                              ? (
                                  <CircularProgress
                                    size={14}
                                  />
                                )
                              : (
                                  <BuildOutlined />
                                )
                          }

                          disabled={
                            building ||
                            Boolean(
                              buildingVersionId
                            ) ||
                            Boolean(
                              lifecycleVersionId
                            )
                          }

                          onClick={
                            () =>
                              onBuild(
                                version.id
                              )
                          }
                        >
                          {building
                            ? "Building..."
                            : version.status ===
                                "build_failed"
                              ? "Retry Build"
                              : "Build Image"}
                        </Button>

                      )}


                      {canPublish && (

                        <Button
                          size="small"
                          variant="contained"

                          disabled={
                            lifecycleBusy ||
                            Boolean(
                              lifecycleVersionId
                            ) ||
                            Boolean(
                              buildingVersionId
                            )
                          }

                          onClick={
                            () =>
                              onPublish(
                                version
                              )
                          }
                        >
                          {lifecycleBusy
                            ? "Publishing..."
                            : "Publish"}
                        </Button>

                      )}


                      {canRetire && (

                        <Button
                          size="small"
                          variant="outlined"
                          color="warning"

                          disabled={
                            lifecycleBusy ||
                            Boolean(
                              lifecycleVersionId
                            )
                          }

                          onClick={
                            () =>
                              onRetire(
                                version
                              )
                          }
                        >
                          {lifecycleBusy
                            ? "Retiring..."
                            : "Retire"}
                        </Button>

                      )}


                      {!isStatic &&
                       !canBuild &&
                       !canPublish &&
                       !canRetire && (

                        <Typography
                          sx={{
                            fontSize:
                              11,

                            color:
                              "text.secondary",
                          }}
                        >
                          —
                        </Typography>

                      )}

                    </Box>

                  </Box>

                );
              }
            )}

          </Box>

        </Box>

      )}

    </Box>
  );
}


function OfferPanel({
  offers,
  onCreate,
  onEdit,
  busyOfferId,
  onActivate,
  onRetire,
}: {
  offers:
    ApplicationOffer[];

  onCreate:
    () => void;

  onEdit:
    (
      offer:
        ApplicationOffer
    ) => void;

  busyOfferId:
    string;

  onActivate:
    (
      offer:
        ApplicationOffer
    ) => Promise<void>;

  onRetire:
    (
      offer:
        ApplicationOffer
    ) => Promise<void>;
}) {

  return (
    <Box
      sx={{
        bgcolor:
          "#ffffff",

        border:
          "1px solid",

        borderColor:
          "divider",
      }}
    >

      <Box
        sx={{
          px: 2.5,
          py: 1.7,

          borderBottom:
            "1px solid",

          borderColor:
            "divider",

          display:
            "flex",

          justifyContent:
            "space-between",

          gap: 2,
        }}
      >

        <Box>

          <Typography
            sx={{
              fontWeight:
                600,
            }}
          >
            Commercial Offers
          </Typography>


          <Typography
            sx={{
              fontSize: 12,

              color:
                "text.secondary",
            }}
          >
            Publisher offer catalog
          </Typography>

        </Box>


        <Stack
  direction="row"
  spacing={1.5}
  sx={{
    alignItems: "center",
  }}
>

  <Typography
    sx={{
      fontSize: 12,

      color:
        "text.secondary",
    }}
  >
    {offers.length}
        </Typography>


        <Button
          size="small"

          variant="contained"

          startIcon={
            <AddOutlined />
          }

          onClick={
            onCreate
          }
        >
          Create Offer
        </Button>

      </Stack>

      </Box>


      {offers.length === 0 ? (

        <Box
          sx={{
            p: 2.5,

            fontSize: 13,

            color:
              "text.secondary",
          }}
        >
          No commercial offers
          defined.
        </Box>

      ) : (

        <Box
          sx={{
            overflowX:
              "auto",
          }}
        >

          <Box
            sx={{
              minWidth: 650,
            }}
          >

            <OfferTableHeader />


            {offers.map(
              (offer) => (

                <Box
                  key={
                    offer.id
                  }
                  sx={{
                    display:
                      "grid",

                    gridTemplateColumns:
                      "1.4fr 1fr 1fr 120px 190px",

                    px: 2.5,
                    py: 1.5,

                    borderTop:
                      "1px solid",

                    borderColor:
                      "divider",

                    alignItems:
                      "center",
                  }}
                >

                  <Typography
                    sx={{
                      fontSize: 13,

                      fontWeight:
                        600,
                    }}
                  >
                    {offer.name}
                  </Typography>


                  <Typography
                    sx={{
                      fontSize: 12,

                      fontFamily:
                        "monospace",

                      color:
                        "text.secondary",
                    }}
                  >
                    {offer.offerKey}
                  </Typography>


                  <Typography
                    sx={{
                      fontSize: 12,
                    }}
                  >
                    {formatStatus(
                      offer.deliveryType
                    )}
                  </Typography>


                  <Box>
                    <Chip
                      size="small"

                      label={
                        formatStatus(
                          offer.status
                        )
                      }

                      color={
                        statusColor(
                          offer.status
                        )
                      }

                      variant="outlined"

                      sx={{
                        height: 22,

                        fontSize:
                          10,
                      }}
                    />
                  </Box>

                  <Box
                    sx={{
                      display:
                        "flex",

                      alignItems:
                        "center",

                      gap:
                        0.75,

                      flexWrap:
                        "wrap",
                    }}
                  >

                    {offer.status ===
                      "draft" && (

                      <>

                        <Button
                          size="small"

                          startIcon={
                            <EditOutlined />
                          }

                          disabled={
                            busyOfferId ===
                              offer.id
                          }

                          onClick={
                            () =>
                              onEdit(
                                offer
                              )
                          }
                        >
                          Edit
                        </Button>


                        <Button
                          size="small"

                          variant="contained"

                          disabled={
                            Boolean(
                              busyOfferId
                            )
                          }

                          onClick={
                            () =>
                              onActivate(
                                offer
                              )
                          }
                        >
                          {busyOfferId ===
                            offer.id
                            ? "Activating..."
                            : "Activate"}
                        </Button>

                      </>

                    )}


                    {offer.status ===
                      "active" && (

                      <Button
                        size="small"

                        variant="outlined"

                        color="warning"

                        disabled={
                          Boolean(
                            busyOfferId
                          )
                        }

                        onClick={
                          () =>
                            onRetire(
                              offer
                            )
                        }
                      >
                        {busyOfferId ===
                          offer.id
                          ? "Retiring..."
                          : "Retire"}
                      </Button>

                    )}


                    {offer.status ===
                      "retired" && (

                      <Typography
                        sx={{
                          fontSize:
                            11,

                          color:
                            "text.secondary",
                        }}
                      >
                        —
                      </Typography>

                    )}

                  </Box>

                </Box>

              )
            )}

          </Box>

        </Box>

      )}

    </Box>
  );
}

function OfferTableHeader() {

  return (
    <Box
      sx={{
        display:
          "grid",

        gridTemplateColumns:
          "1.4fr 1fr 1fr 120px 190px",

        px: 2.5,
        py: 1,

        bgcolor:
          "#f7f9fa",
      }}
    >

      {[
        "Offer",
        "Offer Key",
        "Delivery",
        "Status",
        "Action",
      ].map(
        (column) => (

          <Typography
            key={
              column
            }
            sx={{
              fontSize: 10,

              fontWeight:
                600,

              color:
                "text.secondary",

              textTransform:
                "uppercase",

              letterSpacing:
                0.5,
            }}
          >
            {column}
          </Typography>

        )
      )}

    </Box>
  );
}